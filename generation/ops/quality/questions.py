import json
import re
import csv
import random
from fuzzywuzzy import fuzz
from typing import List, Dict, Optional, Tuple, Any
from core.types import TranscriptOutput, TranscriptSupplements, OverlaysData, TranscriptTiming, VideoPlan, MCQ, Concept

from core.helpers import print_json
from stages.transcript import format_concept, qc_llm_call, generate_questions_per_concept

from stages.text_overlays import identify_question_timings
from core.clients.s3 import does_file_exist, download, delete_file_from_s3, load_json_from_s3, S3_BUCKET, get_s3_client, upload_file_to_s3, save_json_to_s3
from core.clients.sheets import upload_csv_to_gsheet
from core.context import APVideoContext as Context, prep_content_gen_input, get_lesson_context
from core.clients.sheets import write_to_cell
from prompts.prompts import content_guidelines, QC_FINDER_SYSTEM_PROMPT, QC_FINDER_USER_PROMPT, MCQ_PER_CONCEPT_SYSTEM_PROMPT, MCQ_FIXER_USER_PROMPT, MCQ_PER_CONCEPT_USER_PROMPT
from core.helpers import (
    exception_handler, extract_tag_content, llm_call, print_json,
    replace_spaces, retrieve_markdown_element)
from core.clients.openai import (LLM, assistant_message, chat_complete, llm_complete, system_message,
                          user_message)
generations_sheet_id = "16UfbuX-mfce8fzLh6MpRb7SShWMc6jMLJu1djrD1zsI"
generations_sheet_name = "AP World History - Dump2"

FILTER_QUESTIONS_SYSTEM_PROMPT = """You are tasked with evaluating a set of Multiple Choice Questions (MCQs) designed to assess knowledge of a specific syllabus. Your goal is to identify and remove less critical questions while retaining the most important ones. User will provide the syllabus outlining the core concept, the original set of MCQs, and will specify the number of MCQs to be removed. 

Follow these steps:

1. Analyze each question in relation to the syllabus content.
2. Evaluate the importance of each question based on these criteria:
   a) How well it aligns with core concepts in the syllabus
   b) Its relevance to key learning outcomes
   c) The likelihood of similar content appearing in an AP World History exam
   d) How well it assesses critical thinking and understanding rather than mere memorization

3. Identify the questions that are least aligned with these criteria. These are candidates for removal.

4. Select the {n} questions that are least critical and remove them from the set.

5. Keep the remaining questions that best represent core knowledge and critical thinking as defined in the syllabus.

In your analysis, consider:
- Which questions address the most important takeaways from the concept being assessed?
- Which questions are most likely to appear in an AP World History exam?
- Which questions best evaluate a student's overall understanding of the subject matter?

After your analysis, provide your final list of kept questions. Your output should consist of only the final list of questions that were not removed, presented as a Python list of strings where each string is a kept question.

Present your final output within <final_questions> tags. Do not include any explanation or reasoning in this final output - it should contain only the Python list of kept questions. Example Output:
<final_questions>
[
  "<question 1 - verbatim question field of the first mcq kept>",
  "<question 2 - verbatim question field of the second mcq kept>",
  ...
]
</final_questions>"""

FILTER_QUESTIONS_USER_PROMPT = """First, carefully review the provided syllabus:

<syllabus>
{syllabus}
</syllabus>

Now, examine the following set of MCQs:

<mcqs>
{mcqs}
</mcqs>

Your task is to remove {n} questions from this set. Your final list should contain {total} questions."""

def publish_json(data: dict, sheet_name: str):
    json.dump(data, open('./qc_results.json', 'w'))
    with open('./qc_results.json') as f, open('output.csv', 'w', newline='') as csvfile:
        data = json.load(f)
        writer = csv.writer(csvfile)
        writer.writerow(['Unit', 'Lesson Id', 'Section Name', 'Concept Name', 'QC', 'Content', 'Original MCQs', 'Corrected MCQs'])
        writer.writerows([
            [unit, lesson_id, section_name, concept_name, concept_data.get('qc', ''), 
            concept_data.get('content', ''), json.dumps(concept_data.get('original_mcqs', {}), indent=2), 
            json.dumps(concept_data.get('corrected_mcqs', {}), indent=2), concept_data.get('post_eval', '')]
            for unit, lessons in data.items()
            for lesson_id, sections in lessons.items()
            for section_name, concepts in sections.items()
            for concept_name, concept_data in concepts.items()
        ])
    upload_csv_to_gsheet('output.csv', "1b1m-zpLGf8YFt-AGo_SlYOtEW4puPaBa8sAMAPxTtwU", sheet_name)

def aggregate_stats(stats_list: List[dict]) -> dict:
    if not stats_list:
        return {}
    
    # Initialize the aggregated stats structure
    aggregated_stats = {
        "answer_options_count": {
            "a": {"total": 0, "correct": 0},
            "b": {"total": 0, "correct": 0},
            "c": {"total": 0, "correct": 0},
            "d": {"total": 0, "correct": 0}
        },
        "longest_answer": {"correct": 0, "incorrect": 0},
        "average_answer": {"correct": 0, "incorrect": 0},
    }
    
    # For calculating weighted averages
    total_correct_answers = 0
    total_incorrect_answers = 0
    sum_correct_avg_length = 0
    sum_incorrect_avg_length = 0
    
    # Iterate through each stats dictionary
    for stats in stats_list:
        # Aggregate answer options counts
        for option in ["a", "b", "c", "d"]:
            if option in stats["answer_options_count"]:
                # Handle both the new and old format for backward compatibility
                if isinstance(stats["answer_options_count"][option], dict):
                    aggregated_stats["answer_options_count"][option]["total"] += stats["answer_options_count"][option]["total"]
                    aggregated_stats["answer_options_count"][option]["correct"] += stats["answer_options_count"][option]["correct"]
                else:
                    # Old format support
                    aggregated_stats["answer_options_count"][option]["total"] += stats["answer_options_count"][option]
        
        # Aggregate longest answer counts
        aggregated_stats["longest_answer"]["correct"] += stats["longest_answer"]["correct"]
        aggregated_stats["longest_answer"]["incorrect"] += stats["longest_answer"]["incorrect"]
        
        # Calculate weights for average answer lengths
        # We need to derive the counts of correct and incorrect answers from the stats
        correct_count = sum(option["correct"] for option in stats["answer_options_count"].values()) if isinstance(stats["answer_options_count"]["a"], dict) else 0
        
        # If we can't determine the correct count from the structure, estimate from the longest_answer stats
        if correct_count == 0:
            correct_count = stats["longest_answer"]["correct"]
            incorrect_count = stats["longest_answer"]["incorrect"]
        else:
            total_options = sum(option["total"] for option in stats["answer_options_count"].values())
            incorrect_count = total_options - correct_count
        
        # Add to running totals for weighted average calculation
        if stats["average_answer"]["correct"] > 0:
            total_correct_answers += correct_count
            sum_correct_avg_length += stats["average_answer"]["correct"] * correct_count
        
        if stats["average_answer"]["incorrect"] > 0:
            total_incorrect_answers += incorrect_count
            sum_incorrect_avg_length += stats["average_answer"]["incorrect"] * incorrect_count
    
    # Calculate weighted averages
    if total_correct_answers > 0:
        aggregated_stats["average_answer"]["correct"] = sum_correct_avg_length / total_correct_answers
    
    if total_incorrect_answers > 0:
        aggregated_stats["average_answer"]["incorrect"] = sum_incorrect_avg_length / total_incorrect_answers
    
    return aggregated_stats

def compute_stats(supplementary_data: TranscriptSupplements) -> dict:
    stats = {
        "answer_options_count": {
            "a": {"total": 0, "correct": 0},
            "b": {"total": 0, "correct": 0},
            "c": {"total": 0, "correct": 0},
            "d": {"total": 0, "correct": 0}
        },
        "longest_answer": {"correct": 0, "incorrect": 0},
        "average_answer": {"correct": 0, "incorrect": 0},
    }
    
    correct_answers_length = []
    incorrect_answers_length = []
    
    # Iterate through all questions in the supplementary data
    for section_dict in supplementary_data.questions.values():
        for mcq_list in section_dict.values():
            for mcq in mcq_list:
                # Find the longest answer option for this question
                longest_length = 0
                is_longest_correct = True
                
                # Count answer options by ID and track lengths
                correct_option = next(opt for opt in mcq.answer_options if opt.correct)
                # print(f"\nCorrect Option  : {correct_option.answer} - {len(correct_option.answer)}")
                for option in mcq.answer_options:
                    option_id = option.id.lower()
                    if option_id in stats["answer_options_count"]:
                        stats["answer_options_count"][option_id]["total"] += 1
                        if option.correct:
                            stats["answer_options_count"][option_id]["correct"] += 1
                    
                    # Track answer lengths
                    answer_length = len(option.answer)
                    
                    # Update which answer is longest
                    if (len(correct_option.answer) <= len(option.answer)) and (not option.correct):
                        is_longest_correct = False
                        # print(f"InCorrect Option: {option.answer} - {len(option.answer)}")
                    
                    # Collect lengths for average calculation
                    if option.correct:
                        correct_answers_length.append(answer_length)
                    else:
                        incorrect_answers_length.append(answer_length)

                # Increment the count for longest answer
                if is_longest_correct:
                    stats["longest_answer"]["correct"] += 1
                else:
                    stats["longest_answer"]["incorrect"] += 1
    
    # Calculate average lengths
    if correct_answers_length:
        stats["average_answer"]["correct"] = sum(correct_answers_length) / len(correct_answers_length)
    
    if incorrect_answers_length:
        stats["average_answer"]["incorrect"] = sum(incorrect_answers_length) / len(incorrect_answers_length)
    
    return stats

def find_transcript_json_keys(unit_folder_names: List[str]) -> List[str]:
    client = get_s3_client()
    base_path = "college_board/AP World History: Video Lessons 2"
    all_json_keys = []
    
    for unit_folder in unit_folder_names:
        transcript_path = f"{base_path}/{unit_folder}/contents/subsection/Video Transcript/"
        
        paginator = client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=S3_BUCKET, Prefix=transcript_path)
        
        for page in pages:
            if 'Contents' not in page:
                print(f"No files found in {transcript_path}")
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                
                # Skip directories or non-JSON files
                if key.endswith('.json'):
                    all_json_keys.append(key)
    
    print(f"Found {len(all_json_keys)} JSON files to process")
    return all_json_keys

def shuffle_mcq_options_in_file(file_key: str) -> None:
    stats = {
        "answer_options_count": {"a": 0, "b": 0, "c": 0, "d": 0},
        "longest_answer": {"correct": 0, "incorrect": 0},
        "average_answer": {"correct": 0, "incorrect": 0},
    }
    try:
        transcript = TranscriptOutput(**load_json_from_s3(file_key))  # Assuming this properly maps to TranscriptOutput
                  
        questions = transcript.supplementary_content.questions
        
        # # Iterate through all question sections and categories
        # for section_name, categories in questions.items():
        #     for concept_name, mcq_list in categories.items():
        #         for mcq_idx, mcq in enumerate(mcq_list):
        #             if len(mcq.answer_options) > 1:
        #                 shuffled_options = mcq.answer_options.copy()
        #                 random.shuffle(shuffled_options)
                        
        #                 # Update the option IDs based on new order
        #                 option_ids = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
        #                 for i, option in enumerate(shuffled_options):
        #                     option.id = option_ids[i]
                        
        #                 questions[section_name][concept_name][mcq_idx].answer_options = shuffled_options
        # transcript.supplementary_content.questions = questions
        stats = compute_stats(transcript.supplementary_content)


        # save_json_to_s3(transcript.model_dump(), file_key)

        # TranscriptOutput(**load_json_from_s3(file_key))
        return stats
        
    except Exception as e:
        print(f"Error processing file {file_key}: {str(e)}")

def qc_mcqs(mcqs: dict, concept: Concept, transcript: str, perform_fix: bool = True) -> None:
    allow_right_answer_longest = random.random() < 0.25

    qc_context = f"<transcript>\n{transcript}\n</transcript>"
    if (not allow_right_answer_longest) and perform_fix:
        violated_mcqs = []
        for i, mcq in enumerate(mcqs, 1):
            correct_option_length = len(next(opt for opt in mcq["answer_options"] if opt["correct"])["answer"])*0.95
            is_longest = all(len(opt["answer"]) < correct_option_length for opt in mcq["answer_options"] if not opt["correct"])
            violated_mcqs.append(str(i)) if is_longest else None
        qc_context += f"\n\nCorrect answer is the longest for MCQs: {', '.join(violated_mcqs)}. Suggest a fix for the MCQ options as you evaluate Answer Length Balance. Do not overextend incorrect answer options, as this would make the correct answer noticeably shorter. Instead, slightly extend exactly {random.choice([1, 2])} of the incorrect options for each invalid MCQ to ensure the correct answer is not the longest." if violated_mcqs else "\n\nSkip evaluation of Answer Length Balance."
    else: 
        qc_context += "\n\nSkip evaluation of Answer Length Balance."

    main_guidelines = content_guidelines['MCQs']

    guidelines = main_guidelines['guidelines'].get('MCQs', None)

    _, finder_output = llm_call(
        system_prompt=QC_FINDER_SYSTEM_PROMPT.format(content_type='MCQs', 
                                                        content_description=guidelines['description'],
                                                        quality_criteria=guidelines['guidelines'],
                                                        context=main_guidelines['context'],
                                                        general_content=main_guidelines['name']
                                                        ),
        user_prompt=QC_FINDER_USER_PROMPT.format(
            transcript_segment=f"<mcqs>\n{json.dumps(mcqs, indent=2)}\n</mcqs>",
            context=qc_context
        ),
        model=LLM.CLAUDE_3_7_SONNET
    )
    any_fail = any(x.lower() == 'fail' for x in re.findall(r'<evaluation>(.*?)</evaluation>', finder_output, flags=re.DOTALL))
    
    corrected_mcqs = []
    if any_fail and perform_fix:
        history = [
            system_message(MCQ_PER_CONCEPT_SYSTEM_PROMPT.format(n_questions=max(len(concept.facts), 2))),
            user_message(MCQ_PER_CONCEPT_USER_PROMPT.format(concept_transcript=transcript, concept_syllabus=format_concept(concept))),
            assistant_message(f"<mcq_set>{json.dumps(mcqs, indent=2)}</mcq_set>")
        ]
        _, corrected_mcqs = llm_call(
            system_prompt='',
            user_prompt=main_guidelines['fixer'].format(finder=finder_output),
            model=LLM.CLAUDE_3_7_SONNET_THINKING,
            history=history,
            tag='mcq_set',
            is_json=True
        )

    return dict(
        qc = finder_output,
        content=transcript,
        original_mcqs=mcqs,
        corrected_mcqs=corrected_mcqs,
        any_fail=any_fail
    ) 

def qc_lesson_mcqs(transcript_key: str) -> None:

    transcript = TranscriptOutput(**load_json_from_s3(transcript_key))

    video_plan = VideoPlan(**load_json_from_s3(transcript_key.replace('Video Transcript', 'Video Plan'))['video_plan'])
    questions = transcript.supplementary_content.questions
    output = {}
    for section_name, section in transcript.lesson_transcript_breakdown.sections.items():
        output[section_name] = {}
        video_section = next(section for section in video_plan.sections if section.section_title == section_name)
        for concept_name, transcript_concept in section.explanations.items():   
            concept = next(concept for concept in video_section.concepts if concept.concept_name == concept_name)
            
            mcqs_dict = [{k: v for k, v in mcq.model_dump().items() if k in ['question', 'answer_options']} for mcq in questions[section_name][concept_name]]

            qc = qc_mcqs(mcqs_dict, concept, transcript_concept.explanation)

            output[section_name][concept_name] = qc

            if qc['any_fail']:
                post_eval = qc_mcqs(qc['corrected_mcqs'], concept, transcript_concept.explanation, perform_fix=False)
                output[section_name][concept_name]['post_eval'] = post_eval['qc'] if post_eval['any_fail'] else 'All good'

            if qc['corrected_mcqs']:
                questions[section_name][concept_name] = [MCQ(**mcq, transcript=transcript_concept.explanation) for mcq in qc['corrected_mcqs']]
    transcript.supplementary_content.questions = questions

    save_json_to_s3(transcript.model_dump(), transcript_key)
    TranscriptOutput(**load_json_from_s3(transcript_key))
    return output

def filter_mcqs(mcqs: List[dict], concept: Concept) -> Tuple[List[dict], List[dict]]:
    total = min(len(mcqs), len(concept.facts), 2)
    remove_n = len(mcqs) - total
    if remove_n == 0:
        return mcqs, []

    _, questions = llm_call(
        system_prompt=FILTER_QUESTIONS_SYSTEM_PROMPT.format(n=remove_n),
        user_prompt=FILTER_QUESTIONS_USER_PROMPT.format(
            syllabus=format_concept(concept), 
            mcqs=json.dumps(mcqs, indent=2),
            total=total,
            n=remove_n
        ),
        model=LLM.CLAUDE_3_7_SONNET_THINKING,
        tag="final_questions",
        is_json=True
    )

    keep_indices = []
    for question in questions:
        score, index = max([(fuzz.ratio(question, original_question['question']), ii) for ii, original_question in enumerate(mcqs)])
        keep_indices.append(index)
        # print(score)
        assert score > 90
    keep_indices = set(keep_indices)

    final_mcqs   = [mcqs[i] for i in keep_indices if i < len(mcqs)]
    removed_mcqs = [mcqs[i] for i in range(len(mcqs)) if i not in keep_indices]

    assert len(keep_indices) == total
    return final_mcqs, removed_mcqs

def filter_lesson_mcqs(transcript_key: str) -> None:

    transcript = TranscriptOutput(**load_json_from_s3(transcript_key))

    video_plan = VideoPlan(**load_json_from_s3(transcript_key.replace('Video Transcript', 'Video Plan'))['video_plan'])
    questions = transcript.supplementary_content.questions
    output = []
    for section_name, section in transcript.lesson_transcript_breakdown.sections.items():
        video_section = next(section for section in video_plan.sections if section.section_title == section_name)
        for concept_name, transcript_concept in section.explanations.items():   
            concept = next(concept for concept in video_section.concepts if concept.concept_name == concept_name)
            # print(f"{section_name} --- {concept_name} --- {len(concept.facts)}")
            mcqs_dict = [{k: v for k, v in mcq.model_dump().items() if k in ['question', 'answer_options']} for mcq in questions[section_name][concept_name]]

            final_mcqs, removed_mcqs = filter_mcqs(mcqs_dict, concept)
            questions[section_name][concept_name] = [MCQ(**mcq, transcript=transcript_concept.explanation) for mcq in final_mcqs]
            output.append(len(final_mcqs))
    transcript.supplementary_content.questions = questions
    # print_json(transcript.model_dump()['supplementary_content']['questions'])
    print(f"Max {max(output)} in lesson. Total is {sum(output)}")

    save_json_to_s3(transcript.model_dump(), transcript_key)
    TranscriptOutput(**load_json_from_s3(transcript_key))
    return output

def update_question_timings_overlay(transcript_key: str) -> None:
    try:
        overlays_key = transcript_key.replace('Video Transcript', 'Text Overlays')
        avatars_key = transcript_key.replace('Video Transcript', 'Avatar Clips')
        
        overlays = OverlaysData(**load_json_from_s3(overlays_key))
    
        transcript = TranscriptOutput(**load_json_from_s3(transcript_key))
        transcript_timings = TranscriptTiming(timings=load_json_from_s3(avatars_key)['lesson_timings'])
        
        overlays.questions = identify_question_timings(transcript, transcript_timings)
        save_json_to_s3(overlays.model_dump(), overlays_key)

        OverlaysData(**load_json_from_s3(overlays_key))        
    except Exception as e:
        print(f"Error processing file {transcript_key}: {str(e)}")

def update_question_in_fresh_gen(transcript_key: str) -> None:
    shotstack_key = transcript_key.replace('Video Transcript', 'ShotStack')
    overlays_key = transcript_key.replace('Video Transcript', 'Text Overlays')

    sheet_link = load_json_from_s3(shotstack_key)['lesson_video']['output_data']['sheet_link']
    start_row, end_row = [int(row) for row in sheet_link.split('range=')[1].split(':')]
    print(start_row, end_row)
    overlays = OverlaysData(**load_json_from_s3(overlays_key))
    video_split_timings = {k.replace('Section: ', ''):v for k, v in overlays.video_splits.items()}

    quesitons = {section_title: [concept_questions.model_dump() for concept_questions in section_questions.values()] for section_title, section_questions in overlays.questions.items()}
    section_wise_questions = [json.dumps(quesitons.get(k, {}), indent=2) for ii, (k, v) in enumerate(video_split_timings.items())]
    
    write_to_cell(
        generations_sheet_id,
        generations_sheet_name,
        [[q] for q in section_wise_questions],
        start_row,
        13, 
        end_row,
        13
    )
    return 

if __name__ == "__main__":
    context = prep_content_gen_input({
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons 2",
            "grade": "Grade 11",
            "subject": "AP World History - vUnit_5_new",
            "category": "High School: AP World History: Modern"
        },
        "Input": get_lesson_context('Explain the causes and effects of economic strategies of different states and empires.')
    })
    context = Context(**context)
    # context.section = "Trans-Saharan Trade Routes from c. 1200 to c. 1450"
    # delete_files_from_layer(context, 'Scenes Breakdown')

    # print(publish_edited_characters())

    folders = [
        # "AP World History - vUnit_1", 
        # "AP World History - vUnit_2_new", 
        # "AP World History - vUnit_3_new", 
        # "AP World History - vUnit_4_new", 
        "AP World History - vUnit_5_new", 
        "AP World History - vUnit_6_new", 
        "AP World History - vUnit_7_new", 
        "AP World History - vUnit_8_new", 
        "AP World History - vUnit_9_new", 
    ]

    # keys = ["college_board/AP World History: Video Lessons 2/AP World History - vUnit_2_new/contents/subsection/Video Transcript/56e14854.json"]
    keys = find_transcript_json_keys(folders)
    aggregate = []

    qc_results = {}
    for key in keys:
        # print(key)
        # stats = shuffle_mcq_options_in_file(key)
        # aggregate.append(stats)
        print(key[48:])
        # unit = key.split('AP World History - ')[1].split('/')[0]
        # if unit not in qc_results:
        #     qc_results[unit] = {}
        # qc_results[unit][key.split('/')[-1][:-5]] = filter_lesson_mcqs(key)

        # update_question_timings_overlay(key)
        try:
            update_question_in_fresh_gen(key)
        except Exception as e:
            print(f"Couldnt update {key[48:]}. {e}")
    # publish_json(qc_results, f"MCQ Fixes - {unit}")
    # print_json(aggregate_stats(aggregate))