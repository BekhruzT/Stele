import os
from googleapiclient.discovery import build
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from oauth2client.service_account import ServiceAccountCredentials
from concurrent.futures import ThreadPoolExecutor, as_completed
# Import necessary modules
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.clients.s3 import upload_file_to_s3

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service(service_account_file):
    gauth = GoogleAuth()
    gauth.credentials = ServiceAccountCredentials.from_json_keyfile_name(service_account_file, SCOPES)
    return GoogleDrive(gauth)

def download_file(drive, file_id, file_name, local_directory, force=False):
    file_path = os.path.join(local_directory, file_name)
    
    if os.path.exists(file_path) and not force:
        print(f"Skipping {file_name}: File already exists locally")
        return True

    try:
        file = drive.CreateFile({'id': file_id})
        file.GetContentFile(file_path)
        print(f"Downloaded: {file_name}")
        return True
    except Exception as e:
        print(f"An error occurred during download of {file_name}: {str(e)}")
        return False

def download_json_files_from_drive(local_directory, service_account_file, folder_id, force=False):
    try:
        drive = get_drive_service(service_account_file)
    except Exception as e:
        print(f"Failed to obtain drive service: {e}")
        return

    # Create the local directory if it doesn't exist
    os.makedirs(local_directory, exist_ok=True)

    # Search for JSON files in the Drive
    file_list = drive.ListFile({'q': f"'{folder_id}' in parents and mimeType='application/json'"}).GetList()

    if not file_list:
        print('No JSON files found in Drive.')
        return

    print(f'Total files: {len(file_list)}')

    # Use ThreadPoolExecutor for concurrent downloads
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for file in file_list:
            future = executor.submit(download_file, drive, file['id'], file['title'], local_directory, force)
            futures.append(future)
        
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"An error occurred: {str(e)}")

    print("All JSON files have been processed.")

# Usage example (commented out)
local_directory = '/tmp/character_bundles'
service_account_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'service-account.json')
folder_id = '1KBWzo8k5VB1YrHwNCuy6hri-vvLEPKIf'
download_json_files_from_drive(local_directory, service_account_file, folder_id)


curriculum = "college_board"
course = "AP World History: Video Lessons"
subject = "AP World History"
s3_prefix = f"{curriculum}/{course}/{subject}/character_bundles"
# List JSON files in local_directory and create a dictionary
json_files = [f for f in os.listdir(local_directory) if f.endswith('.json')]
character_bundle_dict = {
    os.path.splitext(file)[0]: f"{s3_prefix}/{file}"
    for file in json_files
}


# Function to upload a single file to S3
def upload_file(local_file, s3_key):
    try:
        upload_file_to_s3(local_file, s3_key, detect_mimetype=True)
        print(f"Uploaded {local_file} to {s3_key}")
    except Exception as e:
        print(f"Failed to upload {local_file}: {str(e)}")

# Concurrently upload files to S3
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = []
    for file in json_files:
        local_file = os.path.join(local_directory, file)
        s3_key = f"{s3_prefix}/{file}"
        future = executor.submit(upload_file, local_file, s3_key)
        futures.append(future)
    
    for future in as_completed(futures):
        future.result()

print("All files have been uploaded to S3.")


# Write the character_bundle_dict to a JSON file
import json
# The file core/stage_constants.py loads CHARACTER_BUNDLE from at import time, so this
# writes it where the stages read it rather than into the working directory.
output_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'core', 'character_bundle_mapping.json')
with open(output_file, 'w') as f:
    json.dump(character_bundle_dict, f, indent=4)

print(f"Character bundle mapping has been written to {output_file}")




