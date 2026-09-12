from core.context import APVideoContext
from core.clients.s3 import does_file_exist, load_json_from_s3
from core.types import LessonMetadata, KeyConcept
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.vectorstores import FAISS
import json


def analyze_phrases(event):
    input_context = APVideoContext(**event.get("ExecutionInput"), **event.get("Input"))
    lesson_plan = load_json_from_s3(input_context.get_lesson_plan_path())
    
    # Lists to store key phrases, objectives and their metadata
    key_phrases_with_metadata = []
    objectives_with_metadata = []
    
    for unit_title, unit_lesson_plan in lesson_plan.get("Units", {}).items():
        for chapter_title, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
            for section_title, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
                for subsection_title, subsection_lesson_plan in section_lesson_plan.get("Subsections", {}).items():
                    context = APVideoContext(
                        grade=input_context.grade,
                        subject=input_context.subject,
                        course=input_context.course,
                        curriculum=input_context.curriculum,
                        unit=unit_title,
                        chapter=chapter_title,
                        section=section_title,
                        subsection=subsection_title
                    )
                    if not does_file_exist(context.metadata_path):
                        print(f"Metadata file not found for {subsection_title}")
                        continue

                    metadata_dict = load_json_from_s3(context.metadata_path)
                    
                    # Convert dictionary to LessonMetadata object
                    lesson_metadata = LessonMetadata(**metadata_dict['lesson_metadata'])
                    
                    # Extract key phrases and objectives with their metadata
                    for key_concept in lesson_metadata.key_concepts:
                        # Add key phrases
                        for phrase in key_concept.key_phrases:
                            key_phrases_with_metadata.append({
                                'text': phrase,
                                'metadata': {
                                    'subsection': subsection_title,
                                    'section': section_title,
                                    'chapter': chapter_title,
                                    'unit': unit_title,
                                    'key_concept': key_concept.title,
                                    'standard_id': subsection_lesson_plan["StandardId"]
                                }
                            })
                        
                        # Add learning objectives
                        for objective in key_concept.learning_objectives:
                            objectives_with_metadata.append({
                                'text': objective,
                                'metadata': {
                                    'subsection': subsection_title,
                                    'section': section_title,
                                    'chapter': chapter_title,
                                    'unit': unit_title,
                                    'key_concept': key_concept.title,
                                    'standard_id': subsection_lesson_plan["StandardId"]
                                }
                            })
    
    print("\nCreating FAISS vector stores...")
    embeddings = OpenAIEmbeddings()
    
    # Create vector store for key phrases
    key_phrases_texts = [item['text'] for item in key_phrases_with_metadata]
    key_phrases_metadatas = [item['metadata'] for item in key_phrases_with_metadata]
    print(f"Creating vector store with {len(key_phrases_texts)} key phrases")
    
    key_phrases_vectorstore = FAISS.from_texts(
        texts=key_phrases_texts,
        embedding=embeddings,
        metadatas=key_phrases_metadatas
    )
    print("Vector store created successfully")
    
    clusters = []
    processed = set()
    
    print("Loading subsections to process...")
    with open('subsections_to_process.csv', 'r') as csvfile:
        import csv
        csv_reader = csv.reader(csvfile)
        subsections_to_process = [row[0].lower() for row in csv_reader]
    print(f"Loaded {len(subsections_to_process)} subsections to process")
    
    print("\nStarting clustering analysis...")
    for i, phrase in enumerate(key_phrases_texts):
        if i in processed:
            continue
            
        print(f"\nAnalyzing phrase {i+1}/{len(key_phrases_texts)}: {phrase}")
        # Find similar phrases
        similar_docs = key_phrases_vectorstore.similarity_search_with_score(phrase, k=5)
        print(f"Found {len(similar_docs)} similar documents")
        
        # Filter for phrases with high similarity (low distance)
        similarity_threshold = 0.1
        cluster = []
        for doc, score in similar_docs:
            if score < similarity_threshold:
                # Get original index of this document
                doc_idx = key_phrases_texts.index(doc.page_content)
                cluster.append({
                    'phrase': key_phrases_texts[doc_idx],
                    'standard_id': key_phrases_metadatas[doc_idx]['standard_id'],
                    'subsection': key_phrases_metadatas[doc_idx]['subsection']
                })
                processed.add(doc_idx)
                
        if len(cluster) > 1:  # Only keep clusters with multiple phrases
            print(f"Found cluster with {len(cluster)} phrases")
            # Only add cluster if at least one subsection matches subsections_to_process
            should_add = False
            for entry in cluster:
                if entry['subsection'].lower() in subsections_to_process:
                    should_add = True
                    break
                    
            if not should_add:
                print("Skipping cluster - no matching subsections")
                continue
            clusters.append(cluster)
            print("Added cluster to results")
            
    print(f"\nAnalysis complete. Found {len(clusters)} clusters of similar key phrases")

    # Save clusters to JSON file
    cluster_output_file = 'key_phrase_clusters.json'
    with open(cluster_output_file, 'w') as f:
        json.dump(clusters, f, indent=2)

    print(f"Saved key phrase clusters to {cluster_output_file}")

    # Uncomment below only if you want to debug/investigate potential learning objectives of offending key phrases
    # this can come in handy when working on the last mile of the phrases approval and when the culprit is bad objectives like that of unit 2 in world history.
    
    # Create vector store for objectives
    # objectives_texts = [item['text'] for item in objectives_with_metadata]
    # objectives_metadatas = [item['metadata'] for item in objectives_with_metadata]
    # objectives_vectorstore = FAISS.from_texts(
    #     texts=objectives_texts,
    #     embedding=embeddings,
    #     metadatas=objectives_metadatas
    # )
    
    # # Load the phrases json file
    # input_json_path = "key_phrase_clusters.json" # Update with actual path
    # output_json_path = "key_phrase_clusters_enriched.json" # Update with actual path
    
    # with open(input_json_path, 'r') as f:
    #     phrases_data = json.load(f)

    # # Process each phrase group
    # for phrase_group in phrases_data:
    #     for phrase_obj in phrase_group:
    #         # Get the phrase text
    #         phrase = phrase_obj["phrase"]
            
    #         # Search for similar objectives with scores
    #         similar_objectives = objectives_vectorstore.similarity_search_with_score(
    #             phrase,
    #             k=2,
    #             filter={"standard_id": phrase_obj["standard_id"]}
    #         )

    #         # Filter objectives above threshold and get top 2
    #         filtered_objectives = [
    #             (doc, score) for doc, score in similar_objectives 
    #         ]
            
    #         # Add matched objectives and metadata to phrase object
    #         for i, (doc, score) in enumerate(filtered_objectives, 1):
    #             phrase_obj[f"objective_{i}"] = doc.page_content
    #             phrase_obj[f"objective_{i}_score"] = float(score)
    #             phrase_obj[f"objective_{i}_l1"] = doc.metadata["standard_id"]
    #             phrase_obj[f"objective_{i}_key_concept"] = doc.metadata["key_concept"]

    # # Save updated json
    # with open(output_json_path, 'w') as f:
    #     json.dump(phrases_data, f, indent=2)


if __name__ == "__main__":
    event = {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons",
            "grade": "Grade 11",
            "subject": "AP World History - v1",
            "category": "High School: AP World History: Modern"
        },
        "Input": {},
    }
    analyze_phrases(event)