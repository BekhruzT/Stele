import csv
import os
from datetime import datetime, timezone
from typing import List
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pydantic import BaseModel, Field
from core.types import LessonMetadata, KeyConcept
from core.google_api_utils import get_google_creds
from core.context import APVideoContext
from core.clients.s3 import does_file_exist, get_last_modified_time, load_json_from_s3
from core.clients.sheets import upload_csv_to_gsheet
import json

def process_lessons(input_context, lesson_plan, cutoff_time, mode='transcript'):
    processed_lessons = []

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
                    ids = {
                        'DomainId': subsection_lesson_plan.get('DomainId'),
                        'ClusterId': subsection_lesson_plan.get('ClusterId'),
                        'StandardId': subsection_lesson_plan.get('StandardId')
                    }
                    transcripts_path = context.transcripts_path
                    if mode == 'metadata':
                        json_path = context.metadata_path
                        if not does_file_exist(json_path):
                            print(f'metadata file does not exist for {subsection_title}')
                            processed_lessons.append((context, {'lesson_metadata': {'lesson_title': subsection_title, 'key_concepts': []}}, ids))
                            continue
                        last_modified = get_last_modified_time(json_path)
                        if last_modified > cutoff_time:
                            # Fetch transcript
                            metadata_json = load_json_from_s3(json_path)
                            processed_lessons.append((context, metadata_json, ids))
                    else:
                        if not does_file_exist(transcripts_path):
                            continue
                        last_modified = get_last_modified_time(transcripts_path)

                        if last_modified > cutoff_time:
                            # Fetch transcript
                            transcript_json = load_json_from_s3(transcripts_path)
                            processed_lessons.append((context, transcript_json, ids))

    # Sort processed lessons based on DomainId, ClusterId, and StandardId
    processed_lessons.sort(key=lambda x: (
        x[2].get('DomainId', ''),
        x[2].get('ClusterId', ''), 
        x[2].get('StandardId', '')
    ))
    return processed_lessons

def initialize_curation(event):
    input_context = APVideoContext(**event.get("ExecutionInput"), **event.get("Input"))
    cutoff_time = datetime.fromisoformat(event.get("cutoff_time"))
    google_folder_id = event.get("google_folder_id")

    # Load the lesson plan
    lesson_plan = load_json_from_s3(input_context.get_lesson_plan_path())

    credentials = get_google_creds()
    drive_service = build('drive', 'v3', credentials=credentials)

    return input_context, cutoff_time, google_folder_id, lesson_plan, credentials, drive_service


def curate_metadata(event, context):
    input_context, cutoff_time, google_folder_id, lesson_plan, credentials, drive_service = initialize_curation(event)
    print(google_folder_id)
    # We won't be using output CSV file now

    processed_lessons = process_lessons(input_context, lesson_plan, cutoff_time, mode='metadata')
    curated_metadata = []

    # Determine the maximum number of key concepts and key phrases
    max_key_concepts = 0
    max_key_phrases = 0

    for lesson_context, transcript_json, ids in processed_lessons:
        lesson_metadata = transcript_json.get('lesson_metadata')
        if lesson_metadata:
            metadata = LessonMetadata(
                lesson_title=lesson_metadata['lesson_title'],
                boundaries_and_purpose='NA',
                perspective_guidance='NA',
                key_concepts=[
                    KeyConcept(
                        title=concept['title'],
                        learning_objectives=concept['learning_objectives'],
                        key_phrases=concept.get('key_phrases', [])[:20]  # Limit to 20 key phrases
                    )
                    for concept in lesson_metadata['key_concepts']
                ]
            )
            
            curated_metadata.append({
                'chapter': lesson_context.chapter,
                'section': lesson_context.section,
                'subsection': lesson_context.subsection,
                'metadata': metadata,
                'DomainId': ids.get('DomainId'),
                'ClusterId': ids.get('ClusterId'),
                'StandardId': ids.get('StandardId')
            })

            # Update max_key_concepts and max_key_phrases
            max_key_concepts = max(max_key_concepts, len(metadata.key_concepts))
            max_key_phrases = 20  # Fixed to 20

            # Print ignored key phrases
            for concept in lesson_metadata['key_concepts']:
                if len(concept.get('key_phrases', [])) > 20:
                    for phrase in concept.get('key_phrases', [])[20:]:
                        print(f"Ignored phrase: '{phrase}' from key concept '{concept['title']}' in lesson '{metadata.lesson_title}'")
        else:
            print(f"No lesson metadata found for {lesson_context.key}")
    print("Collected Metadata")

    # Prepare data with dynamic headers
    sheet_data = []
    for item in curated_metadata:
        row = {
            'Status': "Awaiting Review",
            'DomainId': item['DomainId'],
            'Domain': item['chapter'],
            'ClusterId': item['ClusterId'],
            'Cluster': item['section'],
            'StandardId': item['StandardId'],
            'Standard': item['subsection'],
            'Lesson-Title': item['metadata'].lesson_title
        }
        
        # Add key concepts and phrases
        for i in range(max_key_concepts):
            if i < len(item['metadata'].key_concepts):
                concept = item['metadata'].key_concepts[i]
                row[f'Section-Title-{i+1}'] = concept.title
                for j in range(max_key_phrases):
                    if j < len(concept.key_phrases):
                        row[f'Key-Phrase-{i+1}-{j+1}'] = concept.key_phrases[j]
                    else:
                        row[f'Key-Phrase-{i+1}-{j+1}'] = ''
            else:
                row[f'Section-Title-{i+1}'] = ''
                for j in range(max_key_phrases):
                    row[f'Key-Phrase-{i+1}-{j+1}'] = ''
        
        sheet_data.append(row)

    print("Prepared data with dynamic headers")

    # todo: sort data based on ids.

    # Create dynamic fieldnames
    fieldnames = ['Status', 'DomainId', 'Domain', 'ClusterId', 'Cluster', 'StandardId', 'Standard', 'Lesson-Title']
    for i in range(1, max_key_concepts + 1):
        fieldnames.append(f'Section-Title-{i}')
        for j in range(1, max_key_phrases + 1):
            fieldnames.append(f'Key-Phrase-{i}-{j}')
    print("Created dynamic field names")

    # Now, proceed to update the Google Sheet
    # Build the service
    sheets_service = build('sheets', 'v4', credentials=credentials)

    # The ID of the spreadsheet to update
    spreadsheet_id = event['sheet_id']
    sheet_name = event['sheet_name']
    # First, read the existing data from the sheet
    sheet = sheets_service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=sheet_name).execute()
    existing_values = result.get('values', [])
    
    # Convert existing data to a list of dicts for easier comparison
    # Assume the headers are in the first row
    if not existing_values:
        existing_headers = fieldnames  # If the sheet is empty, use our fieldnames
        existing_data_dicts = []
    else:
        existing_headers = existing_values[0]
        # Ensure that the existing headers match the new fieldnames
        if existing_headers != fieldnames:
            # Update the headers in the sheet to match the new fieldnames
            body = {
                'values': [fieldnames]
            }
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!1:1',  
                valueInputOption='RAW',
                body=body
            ).execute()
            existing_headers = fieldnames
            existing_data_dicts = []
            existing_values = []
        else:
            existing_data_dicts = [dict(zip(existing_headers, row)) for row in existing_values[1:]]

    # Now, for each item in our sheet_data, check if it exists in existing_data_dicts
    for new_row in sheet_data:
        match_found = False
        for idx, existing_row in enumerate(existing_data_dicts):
            if (existing_row.get('Domain') == new_row['Domain'] and
                existing_row.get('Cluster') == new_row['Cluster'] and
                existing_row.get('Standard') == new_row['Standard']):
                print("Match found, update the existing row")
                # todo : should we preserve the 'Status' if it is qc-passed
                # if existing_row.get('Status') == 'QC complete - Passed':
                    # new_row['Status'] = existing_row.get('Status', "Awaiting Review")
                
                existing_data_dicts[idx] = new_row
                match_found = True
                break
        if not match_found:
            # Append to existing data
            existing_data_dicts.append(new_row)

    # Now, we need to write back the updated data to the sheet
    # Create the new data, starting with headers
    updated_values = [fieldnames]
    for row_dict in existing_data_dicts:
        row = [row_dict.get(field, '') for field in fieldnames]
        updated_values.append(row)

    # Prepare the body for updating the sheet
    body = {
        'values': updated_values
    }

    # Write the data back to the sheet (overwrites existing data)
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f'{sheet_name}',  
        valueInputOption='RAW',
        body=body
    ).execute()

    print(f"Metadata updated in Google Sheet ID: {spreadsheet_id}")
    print(f"Max key concepts: {max_key_concepts}")
    print(f"Max key phrases: {max_key_phrases}")

    return curated_metadata

def curate_transcripts(event, context):
    input_context, cutoff_time, google_folder_id, lesson_plan, credentials, drive_service = initialize_curation(event)
    output_csv_path = "/tmp/curated_lessons_output.csv"

    processed_lessons = process_lessons(input_context, lesson_plan, cutoff_time)
    curated_lessons = []

    for lesson_context, transcript_json in processed_lessons:
        # Create Google Doc
        file = create_transcript_google_doc(lesson_context, cutoff_time, google_folder_id, credentials, drive_service, transcript_json)

        # Add to curated lessons
        curated_lessons.append({
            'chapter': lesson_context.chapter,
            'section': lesson_context.section,
            'subsection': lesson_context.subsection,
            'google_doc_link': file['webViewLink']
        })

    # Export curated lessons to CSV
    with open(output_csv_path, 'w', newline='') as csvfile:
        fieldnames = ['chapter', 'section', 'subsection', 'google_doc_link']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for lesson in curated_lessons:
            writer.writerow(lesson)

    return {
        'curated_lessons_count': len(curated_lessons),
        'output_csv_path': output_csv_path
    }

def create_transcript_google_doc(context, cutoff_time, google_folder_id, credentials, drive_service, transcript_json):
    file_metadata = {
                            'name': f"{cutoff_time.strftime('%m-%d %H:%M')} - {context.key}",
                            'mimeType': 'application/vnd.google-apps.document',
                            'parents': [google_folder_id]
                        }
    file = drive_service.files().create(body=file_metadata, fields='id, webViewLink').execute()

                        # Update Google Doc content
    from googleapiclient.errors import HttpError
    docs_service = build('docs', 'v1', credentials=credentials)
    lesson_transcript = transcript_json.get('lesson_transcript', 'not found')
    requests = [
                            {
                                'insertText': {
                                    'location': {'index': 1},
                                    'text': lesson_transcript
                                }
                            }
                        ]
    try:
        response = docs_service.documents().batchUpdate(
                                documentId=file['id'],
                                body={'requests': requests}
                            ).execute()
        print(f"Successfully updated document {file['id']}")
        print(f"Response details: {response}")
    except HttpError as error:
        print(f"An error occurred: {error}")
        print(f"Failed to update document {file['id']}")
        print(f"Error details: {error.resp.status}, {error.content}")
    return file


if __name__ == "__main__":
    event = {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons",
            "grade": "Grade 11",
            "subject": "AP World History - v1",
            "category": "High School: AP World History"
        },
        "Input": {},
        "cutoff_time": "2024-10-14T00:00:00+00:00",  
        "google_folder_id": "10zDL3cb2Pp6PSQWvxDwnQkGcD2aJqNYF",
        "sheet_id": "1ZEO3A2CPyCS1dblkxEzInorfX9aWRS1ALTpW_iOF38g",
        'sheet_name': 'Sheet16'
    }

    # upload_csv_to_gsheet('curated_metadata_output.csv', '1zUVqxAlgyHG41b8twVBM5xMbslgWFmUgqNmF3IpFAxI')
    # result = curate_transcripts(event, None)
    curate_metadata(event, None)
    











