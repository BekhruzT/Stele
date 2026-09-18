import boto3
import os
import json
from core.clients.s3 import load_json_from_s3
from core.context import APVideoContext

# Initialize the S3 client
s3_client = boto3.client('s3')

# Define the bucket name and the hash string
bucket_name = 'gen-ai-textbooks-dev'
base_path = 'college_board/AP World History: Video Lessons/AP World History - v1/contents/subsection/'
media_path = 'college_board/AP World History: Video Lessons/AP World History - v1/media/'



event = {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons",
            "grade": "Grade 11",
            "subject": "AP World History - v1",
            "category": "High School: AP World History: Modern"
        },
        "Input": {},
        "cutoff_time": "2024-10-14T00:00:00+00:00",  
        "google_folder_id": "10zDL3cb2Pp6PSQWvxDwnQkGcD2aJqNYF",
        "output_csv_path": "curated_lessons_output.csv"
    }

input_context = APVideoContext(**event.get("ExecutionInput"), **event.get("Input")) 
lesson_plan = load_json_from_s3(input_context.get_lesson_plan_path())



# List all folders in the specified path
response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=base_path, Delimiter='/')

print(json.dumps(response['CommonPrefixes'], indent=2))
# Check if 'CommonPrefixes' is in the response
def delete_for_a_lesson(s3_client, bucket_name, hash_string, folder):
    target_files = [f"{folder}{hash_string}.json", f"{folder}{hash_string}-edited.json"]
        
    for target_file in target_files:
        try:
                # Check if the file exists
            s3_client.head_object(Bucket=bucket_name, Key=target_file)
                
                # If the file exists, delete it
            s3_client.delete_object(Bucket=bucket_name, Key=target_file)
            print(f"Deleted {target_file}")
        except s3_client.exceptions.ClientError as e:
                # If the file does not exist, skip it
            if e.response['Error']['Code'] == '404':
                print(f"{target_file} does not exist.")
            else:
                raise


def delete_media_folder(s3_client, bucket_name, media_path, hash_string):
    media_folder_path = f"{media_path}{hash_string}/"
    response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=media_folder_path)

    if 'Contents' in response:
        for obj in response['Contents']:
            s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
            print(f"Deleted {obj['Key']}")
    else:
        print(f"No objects found in the media folder {media_folder_path}")


if 'CommonPrefixes' in response:
    folders = [prefix['Prefix'] for prefix in response['CommonPrefixes']]
    
    # Iterate over each folder
    for folder in folders:
       # We skip if it doesn't follow in the following list of folders
        folders_1 = [
    # "content_plan", 
    "lesson_metadata",
    "Video Transcript",
    "Avatar Clips",
    "Text Overlays",
    "Scenes Breakdown",
    "Image Gen Clips",
    "Video Gen Clips",
    "Local Render",
        ]
        if folder.split('/')[-2] not in folders_1:
            print(f"{folder.split('/')[-2]} not in folders {folders_1}")
            continue

        print(f"Deleting contents in Folder: {folder.split('/')[-2]}")
        # Define the target file names
        for unit_title, unit_lesson_plan in lesson_plan.get("Units", {}).items():
            for chapter_title, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
                if chapter_title != 'The Global Tapestry':
                    continue
                for section_title, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
                    for subsection_title, _ in section_lesson_plan.get("Subsections", {}).items():
                #         l1_s = ['Explain the effects of Chinese cultural traditions on East Asia over time.', 'Explain how systems of belief and their practices affected society in the period from c. 1200 to c. 1450.',
                # 'Explain the causes and effects of the rise of Islamic states over time.', 'Explain how the various belief systems and practices of South and Southeast Asia affected society over time.',
                # 'Explain how and why various states of South and Southeast Asia developed and maintained power over time.', 'Explain how and why states in the Americas developed and changed over time.',
                # 'Explain how and why states in Africa developed and changed over time.', 'Explain how the beliefs and practices of the predominant religions in Europe affected European society.']
                #         if subsection_title not in l1_s:
                #             continue
                #         else:
                #             print(subsection_title)
                    
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
                        delete_for_a_lesson(s3_client, bucket_name, context.key, folder)
                        # delete_media_folder(s3_client, bucket_name, media_path, context.key)
else:
    print("No folders found in the specified path.")
