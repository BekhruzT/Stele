import csv
import os
import re
import tempfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import pygsheets
from core.types import (
    SheetImage, SheetImages)
from google.oauth2 import service_account
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials
from pydantic import BaseModel
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed
from core.google_api_utils import get_google_creds
from core.hash import hash_code
from core.path import get_key, get_lesson_plan_path
from core.clients.s3 import (create_presigned_url, does_file_exist, download,
                      get_last_modified_time, load_json_from_s3,
                      save_json_to_s3)


def save_dicts_to_csv(data_list, file_path='/tmp/tmp.csv'):
    if not data_list:
        raise ValueError("The data list is empty")
    fieldnames = data_list[0].keys()
    with open(file_path, mode='w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for data in data_list:
            writer.writerow(data)


def does_gdrive_file_exist(url):
    creds = get_google_creds()
    service = build('drive', 'v3', credentials=creds)
    
    try:
        # Extract the file ID from the URL
        file_id = url.split('/d/')[1].split('/')[0]
        # Attempt to get the file metadata using the file ID
        file = service.files().get(fileId=file_id).execute()
        return True
    except Exception as e:
        # print(f"Error: {e}")
        return False

def read_gsheet_into_dict(spreadsheet_key, sheet_name='Sheet1'):
    # Get the Google credentials
    creds = get_google_creds()

    # Authorize and access the Google Sheet using pygsheets
    client = pygsheets.authorize(custom_credentials=creds)
    sh = client.open_by_key(spreadsheet_key)
    worksheet = sh.worksheet_by_title(sheet_name)

    # Read all records into a list of dictionaries
    records = worksheet.get_all_records()
    return records

def get_images() -> SheetImages:
    sheet1 = read_gsheet_into_dict('1oda6qbYqkoPk3xfrRM9okAI3xqnp77xF3xq9vM_f0xU', 'Mapped Images')
    sheet2 = read_gsheet_into_dict('1tp-AW_Cwp8oudYMyIFQv2XnqQvrMEX-JTmuDCi3kau4', 'image files and captions')

    records = [*sheet1, *sheet2]
    images = SheetImages(images=[])
    for record in records:
        url = record.get('Image URL', record.get('URL'))
        description = record.get('Caption')
        is_map = 'map' in record.get('Image Type', 'Map').lower()
        
        if url and description and is_map:
            images.images.append(SheetImage(url=url, description=description))
    return images

def update_images() -> None:
    image_mappings_path = 'custom/ap_history/mapped_images.json'
    if (not does_file_exist(image_mappings_path)) or (datetime.now(get_last_modified_time(image_mappings_path).tzinfo) - get_last_modified_time(image_mappings_path) > timedelta(days=1)):
        new_image_mappings = get_images()
        save_json_to_s3(new_image_mappings.model_dump(), image_mappings_path)

def get_worksheet_id(spreadsheet_id, worksheet_name):
    creds = get_google_creds()
    client = pygsheets.authorize(custom_credentials=creds)

    try:
        sheet = client.open_by_key(spreadsheet_id)
        worksheet = sheet.worksheet_by_title(worksheet_name)
        return worksheet.id
    except pygsheets.exceptions.WorksheetNotFound:
        # Return -1 if the worksheet is not found
        return -1
    except Exception as e:
        # Log other exceptions but still return -1
        print(f"Error getting worksheet ID: {e}")
        return -1
    
def upload_csv_to_gsheet(csv_path: str, sheet_id: str, sheet_name: str):
    # Authenticate with Google
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)

    # Specify the sheet and range where the data will be uploaded
    range_name = f'{sheet_name}!A1'  # Adjust range as needed
    value_input_option = 'USER_ENTERED'

    # Read data from CSV
    with open(csv_path, newline='') as csvfile:
        reader = csv.reader(csvfile)
        data = list(reader)

    # Prepare the request body
    body = {
        'values': data
    }

    # Call the Sheets API to update the sheet
    result = service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_name,
        valueInputOption=value_input_option,
        body=body
    ).execute()

    print(f"{result.get('updatedCells')} cells updated.")

def upload_s3_file_to_gdrive(s3_key: str, file_name: Optional[str] = None, gdrive_folder_id:str='1mtrbRBj1qx4-RK5msraE25xRxJGIBKQ8'):
    try:
        # Create a temporary file to store the downloaded video
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            local_path = tmp_file.name

        # Download the video from S3
        download(s3_key, local_path)
        print(f"Downloaded video from S3 to {local_path}")

        # Get Google Drive credentials
        creds = get_google_creds()

        # Build the Drive service
        service = build('drive', 'v3', credentials=creds)

        # Set up the file metadata
        file_metadata = {'name': file_name if file_name is not None else os.path.basename(s3_key)}
        if gdrive_folder_id:
            file_metadata['parents'] = [gdrive_folder_id]

        # Create a MediaFileUpload object
        media = MediaFileUpload(local_path, resumable=True)

        # Upload the file to Google Drive
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        file_id = file.get('id')
        print(f"Uploaded video to Google Drive with file ID: {file.get('id')}")
        return f'https://drive.google.com/file/d/{file_id}/view?usp=sharing'
    except Exception as e:
        print(f"An error occurred: {e}")
        raise e

    finally:
        # Clean up the temporary file
        if os.path.exists(local_path):
            os.remove(local_path)
            print(f"Temporary file {local_path} deleted")

def merge_cells(
    spreadsheet_id: str,
    sheet_name: str,
    start_row_index: int,
    end_row_index: int,
    start_column_index: int,
    end_column_index: int,
    merge_type: str = 'MERGE_ALL'
):
    """
    Merges cells in the given (row and column) range on the specified sheet.
    merge_type can be 'MERGE_ALL', 'MERGE_COLUMNS', or 'MERGE_ROWS'.
    """
    # print(f"Merging: {start_row_index} - {end_row_index} : {start_column_index} - {end_column_index}")
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    sheet_id = get_worksheet_id(spreadsheet_id, sheet_name)
    requests_body = {
        'requests': [
            {
                'mergeCells': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': start_row_index,
                        'endRowIndex': end_row_index,
                        'startColumnIndex': start_column_index,
                        'endColumnIndex': end_column_index
                    },
                    'mergeType': merge_type
                }
            }
        ]
    }
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=requests_body
    ).execute()

def get_sheet_row_count(spreadsheet_id: str, sheet_name: str) -> int:
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    
    range_name = f"{sheet_name}"
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()
    
    values = response.get('values', [])
    return len(values)

def append_row_to_sheet(row_data: List[Any], spreadsheet_id: str, sheet_name: str):
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()

    # Append the row to the sheet
    range_name = f'{sheet_name}!A:{chr(len(row_data) + 64)}'
    request = sheet.values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body={
            'values': [row_data]
        }
    )
    response = request.execute()

    return response

def get_dataframe_from_sheet(sheet_id: str, sheet_name: str):
    creds = get_google_creds()
    client = pygsheets.authorize(custom_credentials=creds)

    sheet = client.open_by_key(sheet_id)
    worksheet = sheet.worksheet_by_title(sheet_name)

    data = worksheet.get_all_values()
    df = pd.DataFrame(data)

    df.columns = df.iloc[0]
    df = df[1:]

    # Reset the index
    df.reset_index(drop=True, inplace=True)

    return df

from datetime import datetime


def fetch_all_comments(sheet_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Tuple[str, str]]:
    drive = build('drive', 'v3', credentials=get_google_creds())
    comments = []
    page_token = None

    # Set default dates with time
    if not start_date:
        start_date = '1971-01-01T00:00:00'
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    # Convert dates to datetime objects
    start_date = datetime.strptime(start_date, '%Y-%m-%dT%H:%M:%S')
    end_date = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%S')

    while True:
        response = drive.comments().list(
            fileId=sheet_id,
            fields='*',
            includeDeleted=False,
            pageToken=page_token
        ).execute()

        for comment in response.get('comments', []):
            comment_time = datetime.strptime(comment['createdTime'], '%Y-%m-%dT%H:%M:%S.%fZ')
            if start_date <= comment_time <= end_date:
                comments.append(comment)
        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return comments

def to_excel_coordinates(row, col):
    # Convert column number to Excel column letters
    excel_col = ''
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        excel_col = chr(65 + remainder) + excel_col

    # Combine column letters with row number
    return f"{excel_col}{row}"
    
def find_cell_coordinates(spreadsheet_id, sheet_name, cell_value):
    import html

    # Authorize pygsheets client
    client = pygsheets.authorize(custom_credentials=get_google_creds())

    # Open the spreadsheet by ID
    spreadsheet = client.open_by_key(spreadsheet_id)

    # Select the worksheet by name
    worksheet = spreadsheet.worksheet_by_title(sheet_name)

    # Decode HTML entities in the cell value
    decoded_value = html.unescape(cell_value)

    # Find the cell with the specified value
    cell = worksheet.find(decoded_value, matchEntireCell=True)

    if cell:
        # Return the coordinates of the first matching cell
        return cell[0].row, cell[0].col
    else:
        return None

def column_to_index(col):
    col = col.upper()  # Ensure the column label is in uppercase
    index = 0
    for char in col:
        index = index * 26 + (ord(char) - ord('A') + 1)
    return index - 1

@retry(stop=stop_after_attempt(3), wait=wait_fixed(1), retry=retry_if_result(lambda x: x == "FAIL"))
def note_over_cell(spreadsheet_id: str, comment: str, sheet_name: str = "Sheet1", col: int = 1, row: int = 5):
    # Adds a note over the cell. Not a comment

    service = build('sheets', 'v4', credentials=get_google_creds())

    # Get the sheetId from the sheetName
    sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = sheet_metadata.get('sheets', '')
    sheet_id = None
    for sheet in sheets:
        if sheet.get("properties", {}).get("title") == sheet_name:
            sheet_id = sheet.get("properties", {}).get("sheetId")
            current_columns = sheet.get("properties", {}).get("gridProperties", {}).get("columnCount", 0)
            break

    if sheet_id is None:
        return f"No sheet found with name {sheet_name}"

    start_column_index = col
    end_column_index = start_column_index + 1

    # Ensure the sheet has at least 200 columns
    if current_columns < 200:
        update_grid_request = {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {
                        "columnCount": 200
                    }
                },
                "fields": "gridProperties.columnCount"
            }
        }
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": [update_grid_request]}).execute()

    # Prepare the request body to add a note
    request_body = {
        "requests": [
            {
                "updateCells": {
                    "rows": [
                        {
                            "values": [
                                {
                                    "note": comment
                                }
                            ]
                        }
                    ],
                    "fields": "note",
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": start_column_index,
                        "endColumnIndex": end_column_index
                    }
                }
            }
        ]
    }

    # Execute the request to update the cell with a note
    try:
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=request_body).execute()
        return "SUCCESS"
    except Exception as e:
        print(f"An error occurred: {e}")
        return "FAIL"



@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    retry=retry_if_result(lambda x: x == "FAIL")
)
def color_cell(spreadsheet_id: str, sheet_name: str, col: int, row: int, color: str, factor: float = 0.2):
    def lighten_color(color, factor):
        return {key: min(1.0, value + (1.0 - value) * factor) for key, value in color.items()}
        
    colors = {
        'red': {'red': 1.0, 'green': 0.0, 'blue': 0.0},
        'green': {'red': 0.0, 'green': 1.0, 'blue': 0.0},
        'blue': {'red': 0.0, 'green': 0.0, 'blue': 1.0},
        'yellow': {'red': 1.0, 'green': 1.0, 'blue': 0.0},
        'cyan': {'red': 0.0, 'green': 1.0, 'blue': 1.0},
        'magenta': {'red': 1.0, 'green': 0.0, 'blue': 1.0},
        'black': {'red': 0.0, 'green': 0.0, 'blue': 0.0},
        'white': {'red': 1.0, 'green': 1.0, 'blue': 1.0},
        'gray': {'red': 0.5, 'green': 0.5, 'blue': 0.5},
        'orange': {'red': 1.0, 'green': 0.647, 'blue': 0.0},
        'pink': {'red': 1.0, 'green': 0.753, 'blue': 0.796},
        'purple': {'red': 0.502, 'green': 0.0, 'blue': 0.502},
        'brown': {'red': 0.647, 'green': 0.165, 'blue': 0.165},
        'violet': {'red': 0.933, 'green': 0.51, 'blue': 0.933},
        'indigo': {'red': 0.294, 'green': 0.0, 'blue': 0.51}
    }
    try:
        service = build('sheets', 'v4', credentials=get_google_creds())
        sheet_id = get_worksheet_id(spreadsheet_id, sheet_name)
        column_index = col
        row_index = row - 1

        # Define the cell range
        cell_range = {
            'sheetId': sheet_id,
            'startRowIndex': row_index,
            'endRowIndex': row_index + 1,
            'startColumnIndex': column_index,
            'endColumnIndex': column_index + 1
        }
        # Create the request body
        request_body = {
            'requests': [
                {
                    'repeatCell': {
                        'range': cell_range,
                        'cell': {
                            'userEnteredFormat': {
                                'backgroundColor': lighten_color(colors[color], factor)
                            }
                        },
                        'fields': 'userEnteredFormat.backgroundColor'
                    }
                }
            ]
        }

        # Execute the request
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=request_body
        ).execute()

        print('Cell color updated successfully.')
        return "SUCCESS"

    except Exception as e:
        print(f"An error occurred: {e}")
        return "FAIL"

def set_file_public(file_url):
    # Extract the file ID from the URL
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', file_url)
    if not match:
        print('Invalid file URL.')
        return
    file_id = match.group(1)
    print(f'File ID: {file_id}')
    
    # Authenticate and build the Drive API service
    creds = get_google_creds()
    drive_service = build('drive', 'v3', credentials=creds)
    
    try:
        # Create a new permission
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        drive_service.permissions().create(
            fileId=file_id,
            body=permission,
            fields='id',
        ).execute()
        print('File permissions updated: Anyone with the link can view.')
    except HttpError as error:
        print(f'An error occurred: {error}')


def read_google_sheet_to_csv(spreadsheet_id, sheet_name, csv_file_path='/tmp/csv_file.csv'):
    # Authenticate and create a client
    creds = get_google_creds()
    client = pygsheets.authorize(custom_credentials=creds)
    
    # Open the spreadsheet and the specific sheet
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet_by_title(sheet_name)
    
    # Export the sheet to a CSV file
    worksheet.export(filename=csv_file_path, file_format='csv')

def write_to_cell(spreadsheet_id: str, sheet_name: str, values: Any, row: int, col: int, end_row: Optional[int] = None, end_col: Optional[int] = None):
    """
    Writes values to a cell or range in a Google Sheet.
    
    Args:
        spreadsheet_id (str): The ID of the spreadsheet
        sheet_name (str): Name of the sheet
        values: Single value or 2D list of values to write
        row (int): Starting row number (1-based)
        col (int): Starting column number (1-based)
        end_row (int, optional): Ending row number for range updates
        end_col (int, optional): Ending column number for range updates
    """
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    
    # Handle single value vs 2D array
    if not isinstance(values, list):
        values = [[values]]
    elif not isinstance(values[0], list):
        values = [values]
    
    # Convert to A1 notation
    start_cell = to_excel_coordinates(row, col)
    if end_row and end_col:
        end_cell = to_excel_coordinates(end_row, end_col)
        range_name = f'{sheet_name}!{start_cell}:{end_cell}'
    else:
        range_name = f'{sheet_name}!{start_cell}'
    
    body = {
        'values': values
    }
    
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption='USER_ENTERED',
        body=body
    ).execute()

def get_all_values(spreadsheet_id: str, sheet_name: str) -> List[List[Any]]:
    """
    Get all values from a Google Sheet.
    """
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    
    range_name = f"{sheet_name}"
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()
    
    values = response.get('values', [])
    return values


def get_range_values(spreadsheet_id: str, sheet_name: str, start_row: int, end_row: int, start_col: str = 'A', end_col: str = 'Z') -> List[List[Any]]:
    """
    Get values from a specified range in a Google Sheet.
    
    Args:
        spreadsheet_id (str): The ID of the spreadsheet
        sheet_name (str): Name of the sheet
        start_row (int): Starting row number (1-based)
        end_row (int): Ending row number (1-based)
        start_col (str): Starting column letter (default 'A')
        end_col (str): Ending column letter (default 'Z')
    
    Returns:
        List[List[Any]]: 2D array of values from the specified range
    """
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    
    range_name = f'{sheet_name}!{start_col}{start_row}:{end_col}{end_row}'
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueRenderOption='FORMULA'
    ).execute()
    
    return result.get('values', [])

def clear_range(spreadsheet_id: str, sheet_name: str, start_row: int, end_row: int, start_col: str = 'A', end_col: str = 'Z'):
    """
    Clear values in a specified range in a Google Sheet.
    """
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    
    range_name = f'{sheet_name}!{start_col}{start_row}:{end_col}{end_row}'
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()

def duplicate_sheet(spreadsheet_id: str, source_sheet_name: str, new_sheet_name: str) -> int:
    """
    Duplicates a sheet within a spreadsheet and renames it.
    
    Args:
        spreadsheet_id (str): The ID of the spreadsheet
        source_sheet_name (str): Name of the sheet to duplicate
        new_sheet_name (str): Name for the new duplicated sheet
    
    Returns:
        int: The ID of the newly created sheet
    """
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    
    # Get the source sheet ID
    sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = sheet_metadata.get('sheets', '')
    source_sheet_id = None
    
    for sheet in sheets:
        if sheet.get("properties", {}).get("title") == source_sheet_name:
            source_sheet_id = sheet.get("properties", {}).get("sheetId")
            break
    
    if source_sheet_id is None:
        raise ValueError(f"No sheet found with name {source_sheet_name}")
    
    # Create the duplicate sheet request
    request_body = {
        'requests': [
            {
                'duplicateSheet': {
                    'sourceSheetId': source_sheet_id,
                    'insertSheetIndex': len(sheets),
                    'newSheetName': new_sheet_name
                }
            }
        ]
    }
    
    # Execute the request
    response = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=request_body
    ).execute()
    
    # Get the ID of the newly created sheet
    new_sheet_id = response.get('replies', [{}])[0].get('duplicateSheet', {}).get('properties', {}).get('sheetId')
    
    # print(f"Sheet '{source_sheet_name}' duplicated as '{new_sheet_name}' with ID {new_sheet_id}")
    return new_sheet_id

def extract_hyperlink_parts(hyperlink_formula: str) -> tuple[str, str]:
    # Remove the =HYPERLINK( from start and ) from end
    content = hyperlink_formula.strip('=HYPERLINK()')
    
    # Split by comma and strip quotes
    url, name = content.split(',', 1)
    url = url.strip().strip('"')
    name = name.strip().strip('"')
    
    return url, name

def is_cell_empty(spreadsheet_id: str, sheet_name: str, row: int, col: Union[int, str]):
    """
    Check if a cell in a Google Sheet is empty.
    """
    if not isinstance(col, str):
        cell = to_excel_coordinates(row, col)
    else:
        cell = f"{col}{row}"
    creds = get_google_creds()
    service = build('sheets', 'v4', credentials=creds)
    
    range_name = f'{sheet_name}!{cell}'
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()

    return result.get('values', []) == []

if __name__=="__main__":
    files = [
        # 'college_board/AP US History: Video Lessons/AP US History - v2/media/4449879f/Explain the context in which the republic developed from 1800 to 1848.mp4',
        # 'college_board/AP US History: Video Lessons/AP US History - v2/media/42301cb7/Explain the causes and effects of the Mexican–American War.mp4',
        'college_board/AP US History: Video Lessons/AP US History - v2/media/4dcedfd9/Explain how and why various European colonies developed and expanded from 1607 to 1754.mp4',
        'college_board/AP US History: Video Lessons/AP US History - v2/media/b61066c8/Explain causes of the Columbian Exchange and its effect on Europe and the Americas during the period after 1492.mp4'
    ]
    for f in files:
        upload_s3_file_to_gdrive(f, os.path.basename(f))
