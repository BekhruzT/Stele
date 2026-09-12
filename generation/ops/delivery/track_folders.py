from concurrent.futures import ThreadPoolExecutor, as_completed

from core.clients.sheets import (clear_range, duplicate_sheet, get_worksheet_id,
                          write_to_cell)
from tqdm import tqdm
from config.courses import get_execution_input
from core.clients.s3 import list_files_in_directory

"""
This script tracks the presence of all the json files in the given folders.
It will create a new sheet in the tracking spreadsheet for each folder and track layer wise jsons there.
"""

tracking_spreadsheet_id = "13_bxN8xh_sfMmiqddJMmJdVdQZvGAMMhqRHMJkSEDoU"
layer_index = {
    "Knowledge Graph": 0,
    "Video Plan": 1,
    "Video Transcript": 2,
    "Avatar Clips": 3,
    "Text Overlays": 4,
    "Scenes Breakdown": 5,
    "Image Gen Clips": 6,
    "Video Gen Clips": 7,
    "ShotStack": 8,
}

def update_folder_tracking_sheet(folder):
    execution_input = get_execution_input(folder)['ExecutionInput']

    if get_worksheet_id(tracking_spreadsheet_id, folder) == -1:
        duplicate_sheet(tracking_spreadsheet_id, "Template", folder)

    json_present = {}
    files = list_files_in_directory(f"{execution_input['curriculum']}/{execution_input['course']}/{folder}/contents/subsection/")
    for file in files:
        file = file.replace("-edited", "")
        if not file.endswith(".json") or not '/' in file:
            continue
        id = file.split('/')[-1].split('.')[0]
        for layer in layer_index:
            if layer in file:
                if id not in json_present:
                    json_present[id] = [""] * len(layer_index)
                json_present[id][layer_index[layer]] = "X"
    
    # print(json_present)
    json_present = dict(sorted(json_present.items(), key=lambda x: x[0]))
    values_to_write = []
    for key, value in json_present.items():
        values_to_write.append([key] + value)
    write_to_cell(tracking_spreadsheet_id, folder, values_to_write, 2, 1)
    clear_range(tracking_spreadsheet_id, folder, len(values_to_write) + 2, 100)


if __name__ == "__main__":

    folders_to_check = [
        f"AP US History - vUnit_1_new",
        f"AP US History - vUnit_2_new",
        f"AP World History - vUnit_1",
        f"AP World History - vUnit_2_new",
        f"AP World History - vUnit_3_new",
        f"AP World History - vUnit_4_new",
        f"AP World History - vUnit_5_new",
        f"AP World History - vUnit_6_new",
        f"AP World History - vUnit_7_new",
        f"AP World History - vUnit_8_new",
        f"AP World History - vUnit_9_new",
    ]

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(update_folder_tracking_sheet, folder)
            for folder in folders_to_check
        ]
        
        for future in tqdm(
            as_completed(futures), 
            total=len(futures),
            desc="Tracking folders"
        ):
            future.result()