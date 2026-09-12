import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Dict

from core.types import (
    TranscriptOutput, TranscriptTiming)
from core.helpers import (
    get_topics_list, llm_call, sanitize_path)
from core.stage_constants import \
    get_sheet_info_by_subject
from core.clients.sheets import (
    get_range_values, write_to_cell)
from prompts.thumbnail_prompts import (
    THUMBNAIL_IMAGE_LESSON_USER_PROMPT, THUMBNAIL_IMAGE_SECTION_USER_PROMPT,
    THUMBNAIL_IMAGE_SYSTEM_PROMPT)
from core.clients.images import generate_flux_image, save_image
from tqdm import tqdm
from core.context import APVideoContext as Context
from core.context import prep_content_gen_input
from core.hash import hash_code
from core.clients.openai import LLM
from core.path import get_key
from core.clients.s3 import (list_files_in_directory, load_json_from_s3,
                      save_json_to_s3, upload_file_to_s3)

S3_VIEWER_BUCKET = os.getenv('S3_BUCKET_UI')

def get_thumbnails(context:Context):
    # load jsons
    video_plan_json = load_json_from_s3(context.video_plan_path)
    transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path))

    # getting lesson thumbnail
    _, lesson_thumbnail_prompt = llm_call(
        system_prompt=THUMBNAIL_IMAGE_SYSTEM_PROMPT,
        user_prompt=THUMBNAIL_IMAGE_LESSON_USER_PROMPT.format(
            description=f"Title: {video_plan_json['video_plan']['lesson_title']}\n\nTranscript:\n{transcript.lesson_transcript}"
        ),
        model=LLM.CLAUDE_3_7_SONNET,
    )

    # getting section thumbnails
    section_prompts = {}

    _, intro_thumbnail_prompt = llm_call(
        system_prompt=THUMBNAIL_IMAGE_SYSTEM_PROMPT,
        user_prompt=THUMBNAIL_IMAGE_SECTION_USER_PROMPT.format(
            description=f"Lesson Title: {video_plan_json['video_plan']['lesson_title']}\n\nSection: Introduction\n\nIntroduction Transcript:\n{transcript.lesson_transcript_breakdown.introduction}"
        ),
        model=LLM.CLAUDE_3_7_SONNET,
    )
    section_prompts["Introduction"] = intro_thumbnail_prompt

    for section, section_details in transcript.lesson_transcript_breakdown.sections.items():
        _, section_thumbnail_prompt = llm_call(
            system_prompt=THUMBNAIL_IMAGE_SYSTEM_PROMPT,
            user_prompt=THUMBNAIL_IMAGE_SECTION_USER_PROMPT.format(
                description=f"Lesson Title: {video_plan_json['video_plan']['lesson_title']}\n\nSection: {section}\n\nSection Details:\n{section_details}"
            ),
            model=LLM.CLAUDE_3_7_SONNET,
        )
        section_prompts[section] = section_thumbnail_prompt
    
    _, conclusion_thumbnail_prompt = llm_call(
        system_prompt=THUMBNAIL_IMAGE_SYSTEM_PROMPT,
        user_prompt=THUMBNAIL_IMAGE_SECTION_USER_PROMPT.format(
            description=f"Lesson Title: {video_plan_json['video_plan']['lesson_title']}\n\nSection: Conclusion\n\nConclusion Transcript:\n{transcript.lesson_transcript_breakdown.conclusion}"
        ),
        model=LLM.CLAUDE_3_7_SONNET,
    )
    section_prompts["Conclusion"] = conclusion_thumbnail_prompt

    # generating thumbnails
    lesson_thumbnail = generate_flux_image(lesson_thumbnail_prompt, width=640, height=360)
    section_thumbnails = {}
    for i, (section, prompt) in enumerate(section_prompts.items()):
        image_url = generate_flux_image(prompt, width=640, height=360)
        section_thumbnails[section] = image_url
    # print(lesson_thumbnail)
    # print(json.dumps(section_thumbnails, indent=4))
    return {
        "lesson_thumbnail": lesson_thumbnail,
        "section_thumbnails": section_thumbnails
    }

def get_and_save_thumbnails(context:Context):
    thumbnails = get_thumbnails(context)
    shotstack_json = load_json_from_s3(context.shotstack_json_path)

    video_url = shotstack_json['lesson_video']['output_data']['url']
    segment_urls = shotstack_json['lesson_video']['output_data']['segment_urls']

    output_dir = f"/tmp/{context.key}"
    os.makedirs(output_dir, exist_ok=True)
    
    local_img_path = f"{output_dir}/lesson_thumbnail.jpg"
    save_image(thumbnails['lesson_thumbnail'], local_img_path)
    video_thumbnail_s3_path = '/'.join(video_url.replace('.mp4', '.jpg').split('/')[3:])
    thumbnails['lesson_thumbnail'] = upload_file_to_s3(local_img_path, video_thumbnail_s3_path, S3_VIEWER_BUCKET)

    for section, image_url in thumbnails['section_thumbnails'].items():
        local_img_path = f"{output_dir}/{sanitize_path(section).replace('/', '_')}.jpg"
        save_image(image_url, local_img_path)
        section_thumbnail_s3_path = '/'.join(segment_urls[section].replace('.mp4', '.jpg').split('/')[3:])
        thumbnails['section_thumbnails'][section] = upload_file_to_s3(local_img_path, section_thumbnail_s3_path, S3_VIEWER_BUCKET)

    shotstack_json['lesson_video']['output_data']['thumbnails'] = thumbnails
    save_json_to_s3(shotstack_json, context.shotstack_json_path)

def fetch_lesson_data(execution_input:Dict):
    lesson_datas = {}
    curriculum_data = get_topics_list(execution_input)
    for unit, unit_data in curriculum_data["Units"].items():
        for chapter, chapter_data in unit_data["Chapters"].items():
            for section, subsections in chapter_data["Sections"].items():
                for subsection in subsections:
                    input_dict = {
                        "unit": unit,
                        "chapter": chapter,
                        "section": section,
                        "subsection": subsection
                    }
                    data = {
                        "ExecutionInput": execution_input,
                        "Input": input_dict
                    }
                    lesson_datas[hash_code(get_key([unit, chapter, section, subsection]))] = data
    return lesson_datas

def fetch_generated_lesson_ctx(lesson_datas:Dict):

    shotstack_folder_path = f"{exec_input['curriculum']}/{exec_input['course']}/{exec_input['subject']}/contents/subsection/ShotStack"
    successful_keys = list_files_in_directory(shotstack_folder_path, return_type="basename")
    successful_keys = [os.path.basename(key).split(".")[0] for key in successful_keys if key.endswith(".json")]
    lesson_datas = {k: v for k, v in lesson_datas.items() if k in successful_keys}

    with ThreadPoolExecutor(max_workers=10) as executor:
        contexts_list = list(tqdm(
            executor.map(
                lambda data: Context(**prep_content_gen_input(data)),
                lesson_datas.values()
            ),
            total=len(lesson_datas),
            desc=f"Getting contexts for generated lessons from {exec_input['subject']}:"
        ))
    return contexts_list


if __name__ == "__main__":
    from config.courses import get_execution_input

    # set this to generate thumbnails in these folders
    folders_to_check = [
        "AP US History - vUnit_1_new",
        # "AP US History - vUnit_2_new",
        # "AP US History - vUnit_3_new",
        # "AP US History - vUnit_4_new",
        # "AP US History - vUnit_5_new",
        # "AP US History - vUnit_6_new",
        # "AP US History - vUnit_7_new",
        # "AP US History - vUnit_8_new",
        # "AP US History - vUnit_9_new",
    ]

    # set this to limits the lessons to generate thumbnails for
    lesson_ids_to_check = [
        "6316aa8a",
    ]

    lesson_ctxs = []

    print("Fetching contexts to generate thumbnails for...")
    for folder in folders_to_check:
        exec_input = get_execution_input(folder)["ExecutionInput"]
        lesson_datas = fetch_lesson_data(exec_input)
        # comment this out to generate thumbnails for all generated lessons in the folder-------|
        # lesson_datas = {k: v for k, v in lesson_datas.items() if k in lesson_ids_to_check}
        # -----------------------------------------------------------------------------------|
        lesson_ctxs.extend(fetch_generated_lesson_ctx(lesson_datas))

    print(f"Identified {len(lesson_ctxs)} lessons to generate thumbnails for")
    print("Generating thumbnails...")

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(tqdm(
            executor.map(get_and_save_thumbnails, lesson_ctxs),
            total=len(lesson_ctxs),
            desc=" - Generating thumbnails",
        ))