import json
import os
import re
import csv
import subprocess
import random
from typing import List, Dict, Optional, Text, Tuple, Any
from core.types import AvatarAsset, TextSlide, TranscriptOutput, TranscriptSupplements, OverlaysData, TranscriptTiming, VideoPlan, MCQ, Concept
from core.media.clip_timings import (
    identify_word_index_in_transcript, match_segment_timings)
from core.helpers import print_json
from stages.transcript import format_concept, qc_llm_call, generate_questions_per_concept
from prompts.overlay_prompts import (
    TEXT_SLIDE_CONTENT_SYSTEM, TEXT_SLIDE_CONTENT_USER, text_slide_content_examples, TEXT_SLIDE_TIMINGS_USER_PROMPT, TEXT_SLIDE_TIMINGS_SYSTEM_PROMPT, text_slides_timings_examples)
from fuzzywuzzy import fuzz
from stages.text_overlays import identify_question_timings, slides_timings_identifier
from core.media.html_to_video import html_to_mov, render_text_slide_template
from core.clients.s3 import does_file_exist, download, delete_file_from_s3, load_json_from_s3, S3_BUCKET, get_s3_client, upload_file_to_s3, save_json_to_s3
from core.clients.sheets import upload_csv_to_gsheet
from core.context import APVideoContext as Context, prep_content_gen_input, get_lesson_context
from core.clients.sheets import write_to_cell
from core.helpers import (
    exception_handler, extract_tag_content, llm_call, print_json,
    replace_spaces, retrieve_markdown_element)
from core.clients.openai import (LLM, assistant_message, chat_complete, llm_complete, system_message,
                          user_message)
generations_sheet_id = "16UfbuX-mfce8fzLh6MpRb7SShWMc6jMLJu1djrD1zsI"
generations_sheet_name = "AP World History - Dump2"

def match_point_timings(slide, concept_transcript, transcript_timings)-> TextSlide:
    slide_content = {"title": slide.title, "points": [phrase.content for element in slide.elements for phrase in element.contents]}
    history, point_matches = llm_call(
        system_prompt="",
        user_prompt=TEXT_SLIDE_TIMINGS_USER_PROMPT.format(
            points=json.dumps(slide_content["points"], indent=2),
            transcript=concept_transcript
        ),
        model=LLM.CLAUDE_3_7_SONNET_THINKING,
        history=[system_message(TEXT_SLIDE_TIMINGS_SYSTEM_PROMPT), *text_slides_timings_examples],
        is_json=True
    )
    # json.dump(point_matches, open('./point_timings.json', 'w'), indent=4, sort_keys=False)
    # input("Check Timings")
    # point_matches = json.load(open('./point_timings.json', 'r'))

    failed_matches, text_slide = slides_timings_identifier(slide, point_matches, concept_transcript, transcript_timings, slide.start_time)
    if failed_matches:
        print(f"FAILED MATCHES", failed_matches)
        _, point_matches = llm_call(
            system_prompt='',
            user_prompt=f"Some identified phrases did not exactly match the text in the transcript. Remember, each identified phrase must match a substring in the transcript exactly. You may need to slightly adjust these mismatches to align with the transcript verbatim. If the match was completely incorrect, try to identify the closest semantic match in the transcript.\n<unmatched_phrases>\n{failed_matches}\n</unmatched_phrases>\nPlease correct only these phrases, leaving the rest of the JSON as it is. Without asking any further questions, return the best JSON you can.",
            model=LLM.CLAUDE_3_7_SONNET,
            history=history,
            tag='answer',
            is_json=True
        )
        _, text_slide = slides_timings_identifier(slide, point_matches, concept_transcript, transcript_timings)
    return text_slide

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


def identify_section_concept(video_plan: VideoPlan, slide: TextSlide):
    plan = [
        {k: v if k == "section_title" else 
            [{kk: vv for kk, vv in concept.items() if kk in ['concept_name', 'facts']} 
            for concept in v if concept.get('visual', {}).get('type') == "text_slide"] if k == "concepts" else v
        for k, v in section.items() if k in ["section_title", "concepts"]}
        for section in video_plan.model_dump()['sections']
    ]

    _, section_concept = llm_call(
        system_prompt="""For the provided text slide identify which Section and Concept it corresponds to. Return the Section Title and Concept Name for the matching section and concept as a json inside <match> tags with schema:
<match>
{
    "section_title": <section_title>,
    "concept_name": <concept_name>
}
</match>
Before determining the match perform a thorough analyse. For you information the matching concept must have a visual of type diagram. Match primarily based on the concept, not the section. Determine the section from the matched concept
        """,
        user_prompt=f"""
The Video Plan with section and concepts you will need to match the slide too 
<video_plan>
{json.dumps(plan, indent=2)}
<video_plan>

The slide you will need to match:
<slide>
{json.dumps(slide.model_dump(), indent=2)}
</slide>
""",
        model=LLM.CLAUDE_3_7_SONNET,
        tag="match",
        is_json=True
    )
    return section_concept

def fix_diagram(transcript: str, concept_data: dict, slide: TextSlide, slide_characters: int):
    slide = {
        "title": slide.title,
        "points": [point.content for point in slide.elements]
    }
    
    json.dump(slide, open('./slide.json', 'w'), indent=4, sort_keys=False)
    subprocess.run(['git', 'add', './slide.json'])

    history, fixed_points = llm_call(
        history=[
            system_message(TEXT_SLIDE_CONTENT_SYSTEM.format(figure_name=concept_data.get('figure_name', ''))),
            *text_slide_content_examples,
            user_message(TEXT_SLIDE_CONTENT_USER.format(
                concept=json.dumps({k:v for k,v in concept_data.items() if v and k in ['concept_name', 'concept', 'facts', 'cross_unit_facts']}, indent=2), 
                transcript=transcript
            )),
            assistant_message(f"<answer>\n```\n{json.dumps(slide, indent=2)}\n```\n</answer>")
        ],
        system_prompt='',
        user_prompt=f"""The bullet points are too long, exceeding the 540 character limit by {slide_characters-540} characters. Please shorten them to meet the requirement. 
- It's best to trim from the beginning and end rather than the middle. 
- Focus on removing less important parts based on the syllabus, which outlines key learning points. If a bullet point includes details not in the syllabus, consider it unnecessary and remove it. 
- Avoid replacing phrases with shorter ones to keep the content consistent with the transcript. Always prioritize removing less crucial details over making them more concise.

Trim just the necessary amount do not overdo and risk :
 - losing key learnings from the syllabus
 - causing significant mismatch between transcript and bullet point contents, by removing partial phrases from the bullets.""",
        model=LLM.CLAUDE_3_7_SONNET,
        tag="answer",
        is_json=True
    )
    fixed_points['title'] = slide['title']
    json.dump(fixed_points, open('./slide.json', 'w'), indent=4, sort_keys=False)

    input(f"Validate Fixed Points ({slide_characters} => {sum([len(point) for point in fixed_points['points']])})")

    return json.load(open("./slide.json", "r"))

def build_text_slide_object(slide_content: dict, concept_transcript: str, transcript_timings: TranscriptTiming, original_slide: TextSlide):

    json.dump(original_slide.model_dump(), open('./slide_object.json', 'w'), indent=4, sort_keys=False)
    subprocess.run(['git', 'add', './slide_object.json'])

    start_index, _ = match_segment_timings(transcript_timings, " ".join(concept_transcript.split()[0:10]))
    _, end_index = match_segment_timings(transcript_timings, " ".join(concept_transcript.split()[-10:]))
    concept_transcript_timings = transcript_timings.timings[start_index: end_index+1]
    new_slide = match_point_timings(slide_content, concept_transcript, TranscriptTiming(timings=concept_transcript_timings), original_slide)
    
    original_slide.elements = new_slide.elements
    
    json.dump(original_slide.model_dump(), open('./slide_object.json', 'w'), indent=4, sort_keys=False)
    
    input(f"Validate Updated Slide ({sum([len(e.content) for e in new_slide.elements])})")

    return TextSlide(**json.load(open("./slide_object.json", "r")))


def qc_lesson_slides_length(transcript_key: str) -> None:

    overlays = OverlaysData(**load_json_from_s3(transcript_key.replace('Video Transcript', 'Text Overlays')))
    transcript_timings = TranscriptTiming(timings=load_json_from_s3(transcript_key.replace('Video Transcript', 'Avatar Clips'))['lesson_timings'])
    video_plan = VideoPlan(**load_json_from_s3(transcript_key.replace('Video Transcript', 'Video Plan'))['video_plan'])
    transcript = TranscriptOutput(**load_json_from_s3(transcript_key))

    data = {}
    for ii, slide in enumerate(overlays.text_slides):

        slide_character_length = sum([len(point.content) for point in slide.elements])
        print(slide_character_length)
        if slide_character_length>517 or slide.title in ['Second Great Awakening']:

            section_concept = identify_section_concept(video_plan, slide)
            
            video_section = next(section for section in video_plan.sections if fuzz.ratio(section.section_title, section_concept['section_title'])>90)
            concept = next(concept for concept in video_section.concepts if fuzz.ratio(concept.concept_name, section_concept['concept_name'])>90 )
            
            print(concept.concept_name, section_concept['concept_name'])

            concept_transcript = transcript.lesson_transcript_breakdown.sections[video_section.section_title].explanations[concept.concept_name].explanation
            fixed_slide = fix_diagram(concept_transcript, concept.model_dump(), slide, min(slide_character_length, 520))

            new_slide = build_text_slide_object(fixed_slide, concept_transcript, transcript_timings, slide)
            
            data[os.path.basename(new_slide.src)[:-4]] = {ii: new_slide.model_dump()}
    return data

def fix_text_slides(context: Context) -> None:
    transcript_key = context.transcripts_path

    id = os.path.basename(transcript_key)[:-5]
    slides = json.load(open("./slide_lengths.json", "r"))
    if id not in slides: 
        return
    else:
        slides = slides[id]

    overlays = OverlaysData(**load_json_from_s3(transcript_key.replace('Video Transcript', 'Text Overlays')))

    for slide_id, slide in slides.items():
        ii, slide = list(slide.items())[0]
        print(f"\tSlide {ii}: {slide['title']}")
        slide['src'] = slide['src'].replace('.mp4', '.mov') 
        render_text_slide_template(context, TextSlide(**slide))
        overlays.text_slides[int(ii)] = TextSlide(**slide)
        
        save_json_to_s3(overlays.model_dump(), transcript_key.replace('Video Transcript', 'Text Overlays'))
    delete_file_from_s3(transcript_key.replace('Video Transcript', 'ShotStack'))

if __name__ == "__main__":
    from core.context import prep_content_gen_input
    from config.courses import get_execution_input
    from core.clients.s3 import download
    exec_input    = get_execution_input(
        subject = "AP US History - vUnit_4_new", 
        subsection = "Explain how and why innovation in technology, agriculture, and commerce affected various segments of American society over time."
    )
    context = Context(**prep_content_gen_input(exec_input))

    folders = [
        "AP us History - vUnit_4_new", 

        # "AP World History - vUnit_1", 
        # "AP World History - vUnit_2_new", 
        # "AP World History - vUnit_3_new", 
        # "AP World History - vUnit_4_new", 
        # "AP World History - vUnit_5_new", 
        # "AP World History - vUnit_6_new",
        # "AP World History - vUnit_7_new", 
        # "AP World History - vUnit_8_new", 
        # "AP World History - vUnit_9_new",
    ]

    # keys = [
    #     "college_board/AP World History: Video Lessons 2/AP World History - vUnit_4_new/contents/subsection/Video Transcript/7320561d.json",
    #     "college_board/AP World History: Video Lessons 2/AP World History - vUnit_4_new/contents/subsection/Video Transcript/75af1f9b.json",
    # ]
    # keys = find_transcript_json_keys(folders)
    keys = [context.transcripts_path]

    # try:
    #     aggregate = []
    #     qc_results = {}
    #     for key in keys:
    #         print(f"\n{key[48:]}")
    #         lengthy_slides = qc_lesson_slides_length(key)
    #         if lengthy_slides:
    #             qc_results[os.path.basename(key)[:-5]] = lengthy_slides
    #     json.dump(qc_results, open('./slide_lengths.json', 'w'))
    # except Exception as e:
    #     import traceback
    #     print(traceback.format_exc())
    #     json.dump(qc_results, open('./slide_lengths.json', 'w'))

    for key in keys:
        print(f"\n{key[49:]}")
        fix_text_slides(context)