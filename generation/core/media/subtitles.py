import os
from concurrent.futures import ThreadPoolExecutor
from typing import Dict

from core.types import (
    TranscriptOutput, TranscriptTiming)
from core.helpers import (
    get_topics_list, sanitize_path)
from core.stage_constants import \
    get_sheet_info_by_subject
from core.media.clip_timings import (
    identify_video_split_indexes, reset_timings)
from core.clients.sheets import get_range_values, write_to_cell
from tqdm import tqdm
from core.context import APVideoContext as Context
from core.context import prep_content_gen_input
from core.hash import hash_code
from core.path import get_key
from core.clients.s3 import (list_files_in_directory, load_json_from_s3,
                      upload_file_to_s3)
from core.clients.speech import create_subtitles_file

S3_VIEWER_BUCKET = os.getenv('S3_BUCKET_UI')


def get_section_subtitles(context:Context):
    # load jsons
    transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path))
    transcript_timings = TranscriptTiming(timings=load_json_from_s3(context.avatar_assets_path)['lesson_timings'])
    render_json = load_json_from_s3(context.lesson_video_path)

    # identify video split indexes
    split_times = identify_video_split_indexes(transcript, transcript_timings)
    section_wise_outputs = {
        k: dict(
            start_index=0 if ii==0 else list(split_times.values())[ii-1] + 1,
            end_index=v,
        )
        for ii, (k, v) in enumerate(split_times.items())
    }
    
    # Create directory for the output files if it doesn't exist
    output_dir = f"/tmp/{context.key}"
    os.makedirs(output_dir, exist_ok=True)

    segment_urls = render_json['lesson_video']['output_data']['segment_urls']
    
    # generating subtitles for each section and uploading to s3
    subtitle_urls = {}
    for section_name, section_split_times in section_wise_outputs.items():
        section_timings = TranscriptTiming(timings=transcript_timings.timings[section_split_times['start_index']:section_split_times['end_index']+1])
        section_timings = reset_timings(section_timings)
        srt_path = f"{output_dir}/{sanitize_path(section_name).replace('/', '_')}.srt"
        create_subtitles_file(section_timings, srt_path)
        subtitle_s3_path = '/'.join(segment_urls[section_name].replace('.mp4', '.srt').split('/')[3:])
        subtitle_urls[section_name] = upload_file_to_s3(srt_path, subtitle_s3_path, S3_VIEWER_BUCKET)
    
    # getting fresh generations sheet info and updating the sheet
    sheets_info = get_sheet_info_by_subject(context.subject)
    generations_sheet_link = render_json['lesson_video']['output_data']['sheet_link']

    generations_sheet_headers = get_range_values(sheets_info['Fresh Generations']['sheet_id'], sheets_info['Fresh Generations']['sheet_name'], 1, 1)
    generations_sheet_header_to_col = {header: i for i, header in enumerate(generations_sheet_headers[0])}

    # reading sources values, updating and refilling that in sheet (adding subtitles urls)
    source_range = generations_sheet_link.split('range=')[1].split(':')
    source_start_row = int(source_range[0])
    source_end_row = int(source_range[1])
    source_values = get_range_values(sheets_info['Fresh Generations']['sheet_id'], sheets_info['Fresh Generations']['sheet_name'], source_start_row, source_end_row)
    for i, row in enumerate(source_values):
        row[generations_sheet_header_to_col['Splits subtitles']] = f'=HYPERLINK("{list(subtitle_urls.values())[i]}", "{list(subtitle_urls.keys())[i]}")'
    write_to_cell(sheets_info['Fresh Generations']['sheet_id'], sheets_info['Fresh Generations']['sheet_name'], source_values, source_start_row, 1)


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

    render_folder_path = f"{exec_input['curriculum']}/{exec_input['course']}/{exec_input['subject']}/contents/subsection/Local Render"
    successful_keys = list_files_in_directory(render_folder_path, return_type="basename")
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

    # set this to generate section subtitles in these folders
    folders_to_check = [
        "AP US History - vUnit_1_new",
        "AP US History - vUnit_2_new",
        "AP US History - vUnit_3_new",
        "AP US History - vUnit_4_new",
        "AP US History - vUnit_5_new",
        "AP US History - vUnit_6_new",
        "AP US History - vUnit_7_new",
        "AP US History - vUnit_8_new",
        "AP US History - vUnit_9_new",
    ]

    # set this to limits the lessons to generate section subtitles for
    lesson_ids_to_check = [
        "6316aa8a",
    ]

    lesson_ctxs = []

    print("Fetching contexts to generate section subtitles for...")
    for folder in folders_to_check:
        exec_input = get_execution_input(folder)["ExecutionInput"]
        lesson_datas = fetch_lesson_data(exec_input)
        # comment this out to generate section subtitles for all generated lessons in the folder-------|
        lesson_datas = {k: v for k, v in lesson_datas.items() if k in lesson_ids_to_check}
        # -----------------------------------------------------------------------------------|
        lesson_ctxs.extend(fetch_generated_lesson_ctx(lesson_datas))

    print(f"Identified {len(lesson_ctxs)} lessons to generate section subtitles for")
    print("Generating section subtitles...")

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(tqdm(
            executor.map(get_section_subtitles, lesson_ctxs),
            total=len(lesson_ctxs),
            desc=" - Generating section subtitles",
        ))