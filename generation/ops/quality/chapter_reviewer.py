import copy
import json
import logging
import os
from typing import List, Dict, Set, Tuple, Any

from core.types import LessonMetadataWithContext
from core.context import APVideoContext as Context
from core.clients.s3 import does_file_exist, load_json_from_s3, save_json_to_s3
from core.clients.openai import chat_complete, LLM, ensure_json
from core.types import LessonMetadata, KeyConcept, QCStatus
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
import concurrent.futures
import csv
from prompts.util_prompts import get_suggest_improvements_prompt, get_verify_changes_prompt


# Set up logging
import logging
from core.logger import Logger
logger = Logger("MetadataFixer", logging.DEBUG)

METADATA_MODEL = LLM.O1_PREVIEW

def gather_chapter_lessons(event) -> Dict[str, List[LessonMetadataWithContext]]:
    """
    Gather all lessons for all chapters in the lesson plan
    Returns a dictionary with chapter titles as keys and lists of LessonMetadataWithContext as values
    """
    logger.log_info("Starting to gather chapter lessons")
    input_context = Context(**event.get("ExecutionInput"), **event.get("Input"))
    
    # Load the lesson plan
    lesson_plan = load_json_from_s3(input_context.get_lesson_plan_path())
    logger.log_info(f"Loaded lesson plan from {input_context.get_lesson_plan_path()}")
    
    chapter_lessons = {}
    
    def process_subsection(context):
        metadata_path = context.metadata_path
        if does_file_exist(metadata_path):
            metadata_dict = load_json_from_s3(metadata_path)['lesson_metadata']
            metadata = LessonMetadata(**metadata_dict)
            logger.log_info(f"Added lesson metadata for {context.subsection}")
            return context, metadata
        else:
            logger.log_info(f"Lesson metadata not found for {context.subsection}")
            return None
    
    subsection_tasks = []
    for unit_title, unit_lesson_plan in lesson_plan.get("Units", {}).items():
        for chapter_title, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
            chapter_lessons[chapter_title] = []
            for section_title, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
                for subsection_title, subsection_lesson_plan in section_lesson_plan.get("Subsections", {}).items():
                    context = Context(
                        grade=input_context.grade,
                        subject=input_context.subject,
                        course=input_context.course,
                        curriculum=input_context.curriculum,
                        unit=unit_title,
                        chapter=chapter_title,
                        section=section_title,
                        subsection=subsection_title
                    )
                    subsection_tasks.append(context)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        results = list(executor.map(process_subsection, subsection_tasks))
        
    for result in results:
        if result:
            context, metadata = result
            chapter_lessons[context.chapter].append(LessonMetadataWithContext(context=context, metadata=metadata))
    
    logger.log_info(f"Gathered lessons for {len(chapter_lessons)} chapters")
    return chapter_lessons

def save_review_results(chapter_title: str, review_results: List[Dict]):
    """Save review results to a local JSON file."""
    filename = f"/tmp/review_results_{chapter_title.replace(' ', '_')}.json"
    with open(filename, 'w') as f:
        json.dump(review_results, f, indent=2)
    logger.log_info(f"Saved review results for chapter '{chapter_title}' to {filename}")

def review_chapter(chapter_title: str, lessons: List[LessonMetadataWithContext]) -> None:
    logger.log_info(f"Starting review for chapter: {chapter_title}")
    processed_lessons = []
    review_results = []

    for i, lesson in enumerate(lessons):
        if i==0:
            # Skip the first lesson as there are no previous lessons to compare it to, not skipping requires handling of empty processed_lessons in downstream code
            processed_lessons.append(lesson)
            continue
        if lesson.metadata.qc_status != QCStatus.PASSED:
            logger.log_info(f"Reviewing lesson {i+1}/{len(lessons)}: {lesson.context.subsection}")
            review_result = review_lesson(lesson, processed_lessons)
            
            # Store the review result
            review_results.append({
                'subsection': lesson.context.subsection,
                'review_result': copy.deepcopy(review_result)
            })
            
            # Apply changes to any lesson that has been reviewed so far
            if not review_result['changes_made']:  
                logger.log_info(f"No changes made in lesson: {lesson.context.subsection}")
        
        # Add the current lesson to the context for the next iteration
        processed_lessons.append(lesson)

    # Save review results to a local file
    save_review_results(chapter_title, review_results)
    logger.log_info(f"Completed review for chapter: {chapter_title}")

def review_lesson(
    current_lesson: LessonMetadataWithContext,
    processed_lessons: List[LessonMetadataWithContext]
) -> Dict[str, Any]:
    logger.log_info(f"Analyzing lesson in chapter: {current_lesson.context.chapter}")
    analysis_result = analyze_lessons(current_lesson, processed_lessons)
    
    if analysis_result['potential_redundancies']:
        redundancies = analysis_result['potential_redundancies']
        logger.log_info(f"Found {len(redundancies)} potential redundancies")
        
        
        if redundancies:
            logger.log_info(f"{len(redundancies)} redundancies remain after similarity filtering")
            improvement_result = suggest_improvements(
                current_lesson,
                processed_lessons, 
                redundancies
            )
            if improvement_result['improvements']:
                logger.log_info(f"Suggested {len(improvement_result['improvements'])} improvements")
                verification_result = verify_changes(
                    current_lesson,
                    processed_lessons, 
                    improvement_result['improvements']
                )
                if verification_result['changes_approved']:
                    logger.log_info("Changes approved after verification")
                    apply_changes(processed_lessons + [current_lesson], improvement_result['improvements'])
                    return {
                        'changes_made': True,
                        'analysis': redundancies,
                        'improvements': improvement_result['improvements'],
                        'verification': verification_result['verification']
                    }
                else:
                    logger.log_info("Changes not approved after verification")
            else:
                logger.log_info("No improvements suggested")
        else:
            logger.log_info("No redundancies remain after similarity filtering")
    else:
        logger.log_info("No potential redundancies found in analysis")
    
    return {'changes_made': False}


def analyze_lessons(
    current_lesson: LessonMetadataWithContext,
    processed_lessons: List[LessonMetadataWithContext]
) -> Dict[str, List[Dict[str, str]]]:
    logger.log_info(f"Analyzing lessons for potential redundancies in chapter: {current_lesson.context.chapter}")
    
    # Extract all key phrases from previous lessons with their lesson info
    previous_phrases_with_metadata = []
    previous_phrases = []
    for lesson in processed_lessons:
        for concept in lesson.metadata.key_concepts:
            for phrase in concept.key_phrases:
                previous_phrases.append(phrase)
                previous_phrases_with_metadata.append({
                    "content": phrase,
                    "metadata": {"lesson": lesson.context.subsection}
                })
    
    # Extract key phrases from the current lesson
    current_phrases = [
        phrase
        for concept in current_lesson.metadata.key_concepts
        for phrase in concept.key_phrases
    ]
    
    # Initialize OpenAI embeddings
    embeddings = OpenAIEmbeddings()
    
    # Create a FAISS index with previous phrases and metadata
    faiss_index = FAISS.from_texts(
        texts=[doc["content"] for doc in previous_phrases_with_metadata],
        embedding=embeddings,
        metadatas=[doc["metadata"] for doc in previous_phrases_with_metadata]
    )
    
    # Set a similarity threshold
    similarity_threshold = 0.1  # Adjust this value as needed
    
    # Find potential redundancies
    potential_redundancies = []
    for current_phrase in current_phrases:
        similar_phrases = faiss_index.similarity_search_with_score(current_phrase, k=1)
        for similar_doc, score in similar_phrases:
            if score <= similarity_threshold:
                potential_redundancies.append({
                    'phrase1': current_phrase,
                    'phrase2': similar_doc.page_content,
                    'lesson1': current_lesson.context.subsection,
                    'lesson2': similar_doc.metadata["lesson"]
                })
    
    result = {"potential_redundancies": potential_redundancies}
    logger.log_info(f"Analysis complete. Found {len(result['potential_redundancies'])} potential redundancies")
    return result

def suggest_improvements(
    current_lesson: LessonMetadataWithContext,
    processed_lessons: List[LessonMetadataWithContext],
    potential_redundancies: List[Dict]
) -> Dict:
    logger.log_info(f"Suggesting improvements for {len(potential_redundancies)} redundancies in chapter: {current_lesson.context.chapter}")
    
    prompt = get_suggest_improvements_prompt(
        current_lesson.context.chapter,
        current_lesson.context.subsection,
        processed_lessons,
        current_lesson,
        potential_redundancies
    )

    response = chat_complete([{"role": "user", "content": prompt}], model=METADATA_MODEL)
    result = ensure_json(response) if response else {"improvements": []}
    logger.log_info(f"Suggested {len(result.get('improvements', []))} improvements") # type: ignore
    return result # type: ignore

def verify_changes(
    current_lesson: LessonMetadataWithContext,
    processed_lessons: List[LessonMetadataWithContext],
    improvements: List[Dict]
) -> Dict:
    logger.log_info(f"Verifying {len(improvements)} suggested changes for chapter: {current_lesson.context.chapter}")
    
    prompt = get_verify_changes_prompt(
        current_lesson.context.chapter,
        current_lesson.context.subsection,
        processed_lessons,
        current_lesson,
        improvements
    )

    response = chat_complete([{"role": "user", "content": prompt}], model=LLM.GPT_4_O)
    result = ensure_json(response) if response else {"changes_approved": False, "verification": ""}
    return result # type: ignore

def apply_changes(
    lessons: List[LessonMetadataWithContext], 
    improvements: List[Dict[str, Any]]
) -> None:
    logger.log_info(f"Applying {len(improvements)} improvements")
    
    map_title_to_metadata = {}
    for lesson in lessons:
        map_title_to_metadata[lesson.context.subsection] = lesson.metadata
    
    for improvement in improvements:
        lesson_metadata = map_title_to_metadata.get(improvement['lesson'])
        if not lesson_metadata:
            logger.log_info(f"Lesson '{improvement['lesson']}' not found in the metadata.")
            continue

        if improvement['type'] == 'rewrite':
            if improvement['target'] == 'key_phrase':
                phrase_found = False
                for concept in lesson_metadata.key_concepts:
                    if improvement['original'] in concept.key_phrases:
                        index = concept.key_phrases.index(improvement['original'])
                        concept.key_phrases[index] = improvement['suggested']
                        phrase_found = True
                        logger.log_info(f"Rewrote key phrase in lesson '{improvement['lesson']}'")
                        break
                if not phrase_found:
                    logger.log_info(f"Key phrase '{improvement['original']}' not found in lesson '{improvement['lesson']}'.")
            elif improvement['target'] == 'key_concept':
                concept_found = False
                for concept in lesson_metadata.key_concepts:
                    if concept.title == improvement['original']:
                        concept.title = improvement['suggested']
                        concept_found = True
                        logger.log_info(f"Rewrote key concept in lesson '{improvement['lesson']}'")
                        break
                if not concept_found:
                    logger.log_info(f"Key concept '{improvement['original']}' not found in lesson '{improvement['lesson']}'.")
        elif improvement['type'] == 'delete':
            if improvement['target'] == 'key_phrase':
                original_length = sum(len(concept.key_phrases) for concept in lesson_metadata.key_concepts)
                for concept in lesson_metadata.key_concepts:
                    concept.key_phrases = [kp for kp in concept.key_phrases if kp != improvement['original']]
                new_length = sum(len(concept.key_phrases) for concept in lesson_metadata.key_concepts)
                if original_length == new_length:
                    logger.log_info(f"Key phrase '{improvement['original']}' not found for deletion in lesson '{improvement['lesson']}'.")
                else:
                    logger.log_info(f"Deleted key phrase from lesson '{improvement['lesson']}'")
            elif improvement['target'] == 'key_concept':
                logger.log_info(f"Deleting key concept is not supported, requested to delete key concept {improvement['original']} from lesson '{improvement['lesson']}'")
                
        elif improvement['type'] == 'add':
            if improvement['target'] == 'key_phrase':
                target_phrase = improvement['placement']['target_phrase']
                position = improvement['placement']['position']
                new_phrase = improvement['suggested']
                
                phrase_added = False
                for concept in lesson_metadata.key_concepts:
                    if target_phrase in concept.key_phrases:
                        target_index = concept.key_phrases.index(target_phrase)
                        if position == 'after':
                            concept.key_phrases.insert(target_index + 1, new_phrase)
                        else:  # 'before'
                            concept.key_phrases.insert(target_index, new_phrase)
                        phrase_added = True
                        logger.log_info(f"Added new key phrase '{new_phrase}' {position} '{target_phrase}' in lesson '{improvement['lesson']}'")
                        break
                
                if not phrase_added:
                    logger.log_info(f"Target phrase '{target_phrase}' not found. Could not add new key phrase in lesson '{improvement['lesson']}'.")
            elif improvement['target'] == 'key_concept':
                logger.log_info(f"Adding new key concept is not supported, requested to add key concept {improvement['suggested']} to lesson '{improvement['lesson']}'")
                
    
def process_chapter(args: Tuple[str, List[LessonMetadataWithContext]]) -> str:
    chapter_title, lessons = args
    logger.log_info(f"Reviewing chapter: {chapter_title}")
    review_chapter(chapter_title, lessons)
    
    # Save the updated lessons back to S3
    for lesson in lessons:
        context = lesson.context
        metadata_path = context.metadata_path
        existing_metadata = load_json_from_s3(metadata_path)
        existing_metadata['lesson_metadata'] = lesson.metadata.dict()
        
        if lesson.metadata.qc_status == QCStatus.PASSED:
            logger.log_info(f"Skipping lesson as it is qc passed: {context.subsection}")
            continue
        else:
            save_json_to_s3(existing_metadata, metadata_path)
            logger.log_info(f"Updated metadata for lesson: {context.subsection}")
    
    return chapter_title

def chapter_level_review(event, context):
    logger.log_info("Starting chapter level review")
    chapter_lessons = gather_chapter_lessons(event)
    
    # Create tasks for concurrent processing
    chapter_tasks = [(chapter_title, lessons) for chapter_title, lessons in chapter_lessons.items()]
    
    # Process chapters concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        completed_chapters = list(executor.map(process_chapter, chapter_tasks))
    
    logger.log_info(f"Completed review for chapters: {', '.join(completed_chapters)}")
    return {"message": "Chapter level review completed successfully"}

if __name__ == "__main__":
    logger.log_info("Starting chapter level reviewer script")
    event = {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons",
            "grade": "Grade 11",
            "subject": "AP World History - vMayank",
            "category": "High School: AP World History: Modern"
        },
        "Input": {}
    }
    
    result = chapter_level_review(event, None)
    logger.log_info(f"Script completed. Result: {result}") 