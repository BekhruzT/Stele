import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import matplotlib.pyplot as plt
from core.types import \
    OverlaysData
from core.stage_constants import \
    get_sheet_info_by_subject
from core.clients.sheets import (clear_range, find_cell_coordinates, get_all_values,
                          get_range_values, get_worksheet_id, is_cell_empty,
                          merge_cells, write_to_cell)
from tqdm import tqdm
from config.courses import get_execution_input
from core.clients.s3 import (download, list_files_in_directory, load_json_from_s3,
                      upload_file_to_s3)

"""
This script can be used to fill the delivery sheet with the video links and the video resource sheet links.
It also copies the source data from the dump sheet to the video resource sheet.

How to use:
- set the folders to check in the `folders_to_check` list. it will search for all successful shotstack jsons in the given folders.
- for each successful shotstack, it will find the subsection cell in delivery sheet and check if the cell is empty.
- if cell is empty, it will fill the cell with the video link and the video resource sheet. (copy + link)

So basically, it will try to fill all empty cells in delivery sheet if it's possible from the given folders. (if the subsections are present in the given folders)
"""


def capture_last_frame(input_path: str, output_path: str) -> None:
    """
    Uses ffmpeg to grab the last frame of a video.
    """
    cmd = [
        "ffmpeg",
        "-sseof", "-0.1",
        "-i", input_path,
        "-vframes", "1",
        '-loglevel', 'error',
        "-q:v", "2",
        "-y",
        output_path
    ]
    subprocess.run(cmd, check=True)


def get_diagram_last_frames(shotstack_path: str) -> List[Dict]:
    overlays = OverlaysData(**load_json_from_s3(
        shotstack_path.replace("/ShotStack/", "/Text Overlays/"))
    )
    overlays = sorted(
        [*overlays.text_slides, *overlays.diagrams, overlays.conclusion_slide],
        key=lambda x: x.start_time
    )

    screenshots = []
    timestamp_folder = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    for overlay in overlays:
        overlay_id = os.path.splitext(os.path.basename(overlay.src))[0]
        local_file = f"/tmp/{overlay_id}.png"

        download(overlay.src, f"/tmp/{overlay_id}.mp4")

        capture_last_frame(f"/tmp/{overlay_id}.mp4", local_file)

        s3_key = (
            f"SCREENSHOTS/"
            f"{os.path.splitext(os.path.basename(shotstack_path))[0]}/"
            f"{timestamp_folder}/"
            f"{overlay_id}.png"
        )
        upload_url = upload_file_to_s3(local_file, s3_key, s3_bucket=os.getenv("S3_BUCKET_UI"))

        screenshots.append({"url": upload_url, "start_time": overlay.start_time, "end_time": overlay.end_time})

    return screenshots

# caching the sheet data
sheet_data_cache = {}
sheet_header_to_col_cache = {}


def fill_video_resources(sheets_info, shotstack_path, generations_sheet_link, main_sheet_row, main_sheet_header_to_col):
    video_resource_sheet_gid = get_worksheet_id(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['video_resource_sheet_name'])
    start_row = (main_sheet_row - 3) * 10 + 2
    end_row = start_row + 9
    new_sheet_link = (
        f"https://docs.google.com/spreadsheets/d/{sheets_info['Delivery Sheet']['sheet_id']}"
        f"/edit#gid={video_resource_sheet_gid}&range={start_row}:{end_row}"
    )
    write_to_cell(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'], new_sheet_link, main_sheet_row, main_sheet_header_to_col['Video Resources'])

    # Get source data from dump sheet and copy to destination
    source_range = generations_sheet_link.split('range=')[1].split(':')
    source_start_row = int(source_range[0])
    source_end_row = int(source_range[1])
    source_values = get_range_values(sheets_info['Fresh Generations']['sheet_id'], sheets_info['Fresh Generations']['sheet_name'], source_start_row, source_end_row)
    
    if (10 - len(source_values)) > 0:
        source_values += [[""] * (len(source_values[0]) if source_values else 0) for _ in range(10 - len(source_values))]
    
    if source_values:   
        # Get screenshot URLs
        screenshots = get_diagram_last_frames(shotstack_path)
        screenshot_urls = [f'=IMAGE("{scr["url"]}")' for scr in screenshots]
        captions = [f"{datetime.utcfromtimestamp(scr['start_time']).strftime('%M:%S')} - {datetime.utcfromtimestamp(scr['end_time']).strftime('%M:%S')}" for scr in screenshots]
        # Extend first row of source_values with screenshot URLs
        source_values[0].extend(screenshot_urls)
        source_values[-1].extend(captions)


        # Clear target range
        clear_range(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['video_resource_sheet_name'], start_row, end_row)

        # Write all values at once (including URLs)
        write_to_cell(
            sheets_info['Delivery Sheet']['sheet_id'],
            sheets_info['Delivery Sheet']['video_resource_sheet_name'],
            source_values,
            start_row,
            1,  # Starting from column A
            start_row + len(source_values) - 1,
            len(source_values[0])
        )

        # Merge columns for screenshot URLs (9 empty rows beneath - 10th is the caption row)
        if screenshots:
            start_col_for_images = len(source_values[0]) - len(screenshots) + 1  # 1-based indexing
            merge_cells(
                spreadsheet_id=sheets_info['Delivery Sheet']['sheet_id'],
                sheet_name=sheets_info['Delivery Sheet']['video_resource_sheet_name'],
                start_row_index=start_row-1,
                end_row_index=end_row - 1,
                start_column_index=start_col_for_images-1,
                end_column_index=start_col_for_images + len(screenshots) - 1,
                merge_type='MERGE_COLUMNS'
            )


def fill_thumbnails(sheets_info, shotstack_json, main_sheet_row, main_sheet_header_to_col):
    # link to the thumbnails sheet
    video_thumbnails_sheet_gid = get_worksheet_id(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['video_thumbnails_sheet_name'])
    thumbnails_start_row = (main_sheet_row - 3) * 5 + 2
    thumbnails_end_row = thumbnails_start_row + 4
    thumbnails_sheet_link = (
        f"https://docs.google.com/spreadsheets/d/{sheets_info['Delivery Sheet']['sheet_id']}"
        f"/edit#gid={video_thumbnails_sheet_gid}&range={thumbnails_start_row}:{thumbnails_end_row}"
    )
    write_to_cell(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'], thumbnails_sheet_link, main_sheet_row, main_sheet_header_to_col['Video Thumbnails'])
    # copying the metadata from main sheet
    metadata_values = get_range_values(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'], main_sheet_row, main_sheet_row, 'A', 'G')
    if (5 - len(metadata_values)) > 0:
        metadata_values += [[""] * (len(metadata_values[0]) if metadata_values else 0) for _ in range(5 - len(metadata_values))]
    # adding the names and thumbnail images
    thumbnails = shotstack_json['lesson_video']['output_data'].get('thumbnails', None)
    if thumbnails:
        metadata_values[0].append("Lesson Thumbnail")
        metadata_values[1].append(f'=IMAGE("{thumbnails["lesson_thumbnail"]}")')
        metadata_values[0].extend(list(thumbnails['section_thumbnails'].keys()))
        metadata_values[1].extend([f'=IMAGE("{url}")' for url in thumbnails['section_thumbnails'].values()])
    # writing all data at once to the thumbnails sheet
    clear_range(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['video_thumbnails_sheet_name'], thumbnails_start_row, thumbnails_end_row)
    write_to_cell(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['video_thumbnails_sheet_name'], metadata_values, thumbnails_start_row, 1)
    # merge the first 7 columns (metadata)
    merge_cells(
        spreadsheet_id=sheets_info['Delivery Sheet']['sheet_id'],
        sheet_name=sheets_info['Delivery Sheet']['video_thumbnails_sheet_name'],
        start_row_index=thumbnails_start_row-1,
        end_row_index=thumbnails_end_row,
        start_column_index=0,
        end_column_index=7,
        merge_type='MERGE_COLUMNS'
    )
    # merge the image columns
    merge_cells(
        spreadsheet_id=sheets_info['Delivery Sheet']['sheet_id'],
        sheet_name=sheets_info['Delivery Sheet']['video_thumbnails_sheet_name'],
        start_row_index=thumbnails_start_row,
        end_row_index=thumbnails_end_row,
        start_column_index=7,
        end_column_index=len(metadata_values[0]),
        merge_type='MERGE_COLUMNS'
    )


def fill_lesson(key: str, shotstack_path: str, subject: str):
    sheets_info = get_sheet_info_by_subject(subject)

    if sheets_info['Delivery Sheet']['sheet_id'] not in sheet_data_cache:
        sheet_data = get_all_values(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'])
        sheet_header_to_col = {v:k+1 for k,v in enumerate(sheet_data[1])}     # returns 1 based index
        sheet_data_cache[sheets_info['Delivery Sheet']['sheet_id']] = sheet_data
        sheet_header_to_col_cache[sheets_info['Delivery Sheet']['sheet_id']] = sheet_header_to_col
    
    # extract the data from the shotstack json
    shotstack_json = load_json_from_s3(shotstack_path)
    subsection = shotstack_json['lesson_video']['output_data'].get('title', None)
    video_url = shotstack_json['lesson_video']['output_data'].get('url', None)
    lesson_report = shotstack_json['lesson_video'].get('lesson_report', None)
    generations_sheet_link = shotstack_json['lesson_video']['output_data'].get('sheet_link', None)

    if (not video_url) or (not generations_sheet_link):
        print(f"Could not find video url or generations sheet link for {key}")
        return False
    
    # fetch the sheet data and the header to column mapping
    sheet_data = sheet_data_cache[sheets_info['Delivery Sheet']['sheet_id']]
    sheet_header_to_col = sheet_header_to_col_cache[sheets_info['Delivery Sheet']['sheet_id']]

    # find the row with the lesson id
    for i in range(2, len(sheet_data)):
        id = sheet_data[i][sheet_header_to_col['Lesson ID']-1]
        if id == key:
            row = i+1
            break
    else:
        print(f"Could not find lesson id {key} in delivery sheet")
        return False
    
    # skip filled rows
    if not is_cell_empty(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'], row, sheet_header_to_col['Video Link']):
        return False
        
    # video url
    write_to_cell(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'], video_url, row, sheet_header_to_col['Video Link'])

    # VIDEO RESOURCES
    fill_video_resources(sheets_info, shotstack_path, generations_sheet_link, row, sheet_header_to_col)

    # VIDEO THUMBNAILS
    fill_thumbnails(sheets_info, shotstack_json, row, sheet_header_to_col)

    # Write lesson report if present
    if lesson_report:
        lesson_report_content = json.dumps(lesson_report, indent=4)
        write_to_cell(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'], lesson_report_content, row, sheet_header_to_col['Automated Lesson Report'])

    # Marking QC flags
    qc_flags = lesson_report.get('qc_flags', {})
    for flag_name, flag_value in qc_flags.items():
        value = 'FAIL' if flag_value else 'PASS'
        if flag_name in sheet_header_to_col:
            write_to_cell(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'], value, row, sheet_header_to_col[flag_name])

    # Write the last updated time in the sheet in IST timezone
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    write_to_cell(sheets_info['Delivery Sheet']['sheet_id'], sheets_info['Delivery Sheet']['main_sheet_name'], now.strftime("%Y-%m-%d %H:%M"), row, sheet_header_to_col['Last Updated (IST)'])

    return True

if __name__ == "__main__":
    # ====================================== FETCHING SUCCESSFUL LESSONS ======================================

    successful_shotstacks = {}

    folders_to_check = [
        "AP US History - vUnit_1_new",
        # "AP US History - vUnit_2_new",
        # "AP US History - vUnit_3_new",
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
    
    for folder in tqdm(folders_to_check, desc="Fetching successful shotstack jsons"):
        exec_input = get_execution_input(folder)['ExecutionInput']

        shotstack_folder_path = f"{exec_input['curriculum']}/{exec_input['course']}/{exec_input['subject']}/contents/subsection/ShotStack"
        successful_keys = list_files_in_directory(shotstack_folder_path, return_type="basename")
        for key in successful_keys:
            successful_shotstacks[key.split('.')[0]] = {
                "shotstack_path": f"{shotstack_folder_path}/{key}",
                "exec_input": exec_input
            }


    # ====================================== FILLING UP THE DELIVERY SHEET======================================
    filled_count = 0
    # Use ThreadPoolExecutor for concurrent execution
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(fill_lesson, key, item["shotstack_path"], item["exec_input"]["subject"])
            for key, item in successful_shotstacks.items()
        ]
        
        # This will update the progress bar as tasks complete
        for future in tqdm(
            as_completed(futures), 
            total=len(futures),
            desc="Filling Delivery Sheet"
        ):
            if future.result():
                filled_count += 1

    print(f"Filled {filled_count} rows in Delivery Sheet")
