import json
import os
from typing import Dict, List, Optional

import pandas as pd
import requests
from core.stage_constants import \
    get_sheet_info_by_subject
from pydantic import BaseModel
from core.clients.sheets import (extract_hyperlink_parts, get_all_values,
                          get_range_values)
from tqdm import tqdm

"""
This script can be used to upload all the videos present in the delivery sheet to the Stele platform.

How to use:
- for the rows that are completed, it will upload the video to the Stele platform.

References:
- Documentation: https://docs.google.com/document/d/1ouZslYEuFS7VEdD4uGmDiL946Pe5YAASUYHcp1Ozado/edit?tab=t.0
- API Reference: https://docs.platform.learnwith.ai/#caea8dee-9132-4ea0-bae7-b5b4ac2679e9
"""

standard_mapping_csvs = {
    "AP World History": "standard_mapping_world_history.csv",
    "AP US History": "standard_mapping_us_history.csv"
}

# TYPES ======================================

class Image(BaseModel):
    url: str
    credit: Optional[str] = None
    caption: Optional[str] = None

class VideoSubtitles(BaseModel):
    url: str
    type: str

class Video(BaseModel):
    url: str
    title: Optional[str] = None
    subtitles: Optional[VideoSubtitles] = None
    thumbnail: Optional[Image] = None

class VideoSplit(BaseModel):
    name: str
    start: float
    end: float
    video: Video

class LessonVideoObject(BaseModel):
    url: str
    title: Optional[str] = None
    subtitles: Optional[VideoSubtitles] = None
    thumbnail: Optional[Image] = None
    splits: Optional[List[VideoSplit]] = None

class AnswerOption(BaseModel):
    id: str
    answer: str
    correct: bool
    explanation: str

class QuestionObject(BaseModel):
    time: float
    videoSplitTime: float
    videoSplitName: str
    question: str
    answer_options: List[AnswerOption]
    background_image: Optional[Image] = None
    learning_content: Optional[str] = None
    speaker: Optional[str] = None

class LessonObject(BaseModel):
    lesson: LessonVideoObject
    video_parts: Dict[str, Video]
    questions: Dict[str, List[QuestionObject]]
    standard_id: str
    learning_order: int
    video_length: float

# ============================================
def get_thumbnail_row(lesson_id: str, spreadsheet_id: str) -> List[List[str]]:
    sheet_data = get_all_values(spreadsheet_id, 'Video Thumbnails')
    
    # Find the row with matching lesson ID in column G (index 6)
    start_row = None
    for idx, row in enumerate(sheet_data, start=1):  # start=1 because get_range_values uses 1-based indexing
        if len(row) > 6 and row[6] == lesson_id:
            start_row = idx
            break
    
    if start_row is None:
        raise ValueError(f"Could not find lesson ID {lesson_id} in Video Thumbnails sheet")
    
    # Find the next non-empty cell in column G
    end_row = start_row + 1
    
    # Get data between columns H and Z (indices 7-25)
    thumbnail_data = get_range_values(spreadsheet_id, 'Video Thumbnails', start_row, end_row, 'H', 'Z')
    return dict(zip([split_name.lower() for split_name in thumbnail_data[0]], [url.strip('=IMAGE("').strip('")') for url in thumbnail_data[1]]))

# ============================================
GRAPHQL_ENDPOINT = "https://wopirgliozbidi3hbg6ytb7qwi.appsync-api.us-east-1.amazonaws.com/graphql"
AUTH_ENDPOINT = "https://cognito-idp.us-east-1.amazonaws.com/?"
PLATFORM_CONTENT_GENERATOR_CONFIG_ID_LESSON = "243c4a9b-0589-11f0-b555-0eb28d3c3f3f"
PLATFORM_CONTENT_GENERATOR_CONFIG_ID_VIDEO_PART = "529f1978-056a-11f0-b555-0eb28d3c3f3f"
PLATFORM_CONTENT_GENERATOR_CONFIG_ID_QUESTION = "443e6211-f5c8-11ef-b555-0eb28d3c3f3f"

def get_access_token():
    USERNAME = os.getenv('STELE_UPLOAD_USERNAME')
    PASSWORD = os.getenv('STELE_UPLOAD_PASSWORD')
    AWS_CLIENT_ID = os.getenv('STELE_UPLOAD_AWS_CLIENT_ID')

    headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "x-amz-target": "AWSCognitoIdentityProviderService.InitiateAuth"
    }
    payload = {
        "AuthFlow": "USER_PASSWORD_AUTH",
        "ClientId": AWS_CLIENT_ID,
        "AuthParameters": {
            "USERNAME": USERNAME,
            "PASSWORD": PASSWORD
        },
        "ClientMetadata": {}
    }
    response = requests.post(
        AUTH_ENDPOINT,
        json=payload,
        headers=headers
    )
    if response.status_code != 200:
        raise Exception(f"Failed to get access token: {response.text}")
    
    return response.json()['AuthenticationResult']['AccessToken']

AUTO_GEN_GRAPHQL_ID_TOKEN = get_access_token()
print("Authenticated with Stele to upload contents!")

def upload_lesson_to_stele(lesson_video_object: LessonVideoObject, standard_id: str, learning_order: int, video_length: float):
    # print(lesson_video_object.model_dump_json(indent=4))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AUTO_GEN_GRAPHQL_ID_TOKEN}"
    }
    query = """
    mutation InsertContent($input: InsertContentInput!) {
        insertContent(input: $input) {
            platformGeneratedContentId
        }
    }
    """
    variables = {
        "input": {
            "platformContentGeneratorConfigId": PLATFORM_CONTENT_GENERATOR_CONFIG_ID_LESSON,
            "platformStandardId": standard_id,
            "content": lesson_video_object.model_dump_json(exclude_none=True),
            "customAttributes": [
                {
                    "attributeName": "learningOrder",
                    "attributeValue": learning_order
                },
                {
                    "attributeName": "VideoLength",
                    "attributeValue": video_length/60 # in minutes
                }
            ]
        }
    }
    payload = {
        "query": query,
        "variables": variables
    }
    response = requests.post(
        GRAPHQL_ENDPOINT,
        json=payload,
        headers=headers
    )
    if response.status_code != 200:
        raise Exception(f"GraphQL request failed with status {response.status_code}: {response.text}")

    return response.json()

def upload_video_part_to_stele(video_part_object: Video, standard_id: str, parent_id: str, learning_order: int):
    # print(video_part_object.model_dump_json(indent=4, exclude_none=True))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AUTO_GEN_GRAPHQL_ID_TOKEN}"
    }
    query = """
    mutation InsertContent($input: InsertContentInput!) {
        insertContent(input: $input) {
            platformGeneratedContentId
        }
    }
    """
    variables = {
        "input": {
            "platformContentGeneratorConfigId": PLATFORM_CONTENT_GENERATOR_CONFIG_ID_VIDEO_PART,
            "platformStandardId": standard_id,
            "platformParentContentId": parent_id,
            "content": video_part_object.model_dump_json(exclude_none=True),
            "customAttributes": [
                {
                    "attributeName": "learningOrder",
                    "attributeValue": learning_order
                }
            ]
        }
    }
    payload = {
        "query": query,
        "variables": variables
    }
    response = requests.post(
        GRAPHQL_ENDPOINT,
        json=payload,
        headers=headers
    )
    if response.status_code != 200:
        raise Exception(f"GraphQL request failed with status {response.status_code}: {response.text}")

    return response.json()
    

def upload_question_to_stele(question_object: QuestionObject, standard_id: str, parent_id: str):
    # print(question_object.model_dump_json(indent=4, exclude_none=True))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AUTO_GEN_GRAPHQL_ID_TOKEN}"
    }
    query = """
    mutation InsertContent($input: InsertContentInput!) {
        insertContent(input: $input) {
            platformGeneratedContentId
        }
    }
    """
    variables = {
        "input": {
            "platformContentGeneratorConfigId": PLATFORM_CONTENT_GENERATOR_CONFIG_ID_QUESTION,
            "platformStandardId": standard_id,
            "platformParentContentId": parent_id,
            "content": question_object.model_dump_json(exclude_none=True)
        }
    }
    payload = {
        "query": query,
        "variables": variables
    }
    response = requests.post(
        GRAPHQL_ENDPOINT,
        json=payload,
        headers=headers
    )
    if response.status_code != 200:
        raise Exception(f"GraphQL request failed with status {response.status_code}: {response.text}")

    return response.json()


def prepare_lessons_to_upload(subject: str) -> List[LessonObject]:
    # making the LO to standard id mapping
    # Relative to this module, not the working directory: the CSVs ship beside it.
    df = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  standard_mapping_csvs[subject]))

    # Implementing this below hack because standard_mappings have duplicate external_ids 
    # HACK: (we'll store a list instead of single value for each external_id and pop values from front of the list to get the id)
    lo_to_standard_id = {}
    # Iterate over all items in the dataframe
    for index, item in df.iterrows():
        if item['external_id'] not in lo_to_standard_id:
            lo_to_standard_id[item['external_id']] = [item['id']]
        else:
            lo_to_standard_id[item['external_id']].append(item['id'])
    # print(json.dumps(lo_to_standard_id, indent=4))


    sheet_info = get_sheet_info_by_subject(subject)['Delivery Sheet']
    delivery_spreadsheet_id = sheet_info['sheet_id']

    sheet_data = get_all_values(delivery_spreadsheet_id, sheet_info['main_sheet_name'])
    sheet_headers = {v:k for k,v in enumerate(sheet_data[1])}
    sheet_rows = sheet_data[2:]

    resources_sheet_header_row = get_range_values(delivery_spreadsheet_id, sheet_info['video_resource_sheet_name'], 1, 1, 'A', 'N')[0]
    resources_data_headers = {v:k for k,v in enumerate(resources_sheet_header_row) if v != ''}

    lessons_to_upload: List[LessonObject] = []

    topic_count = {}
    for lesson in tqdm(sheet_rows, desc='Preparing lessons to upload'):
        lo_id = lesson[sheet_headers['LO']]
        lesson_name = lesson[sheet_headers['LO Name']]

        # first instance of lo_id gets the first value from the list lo_to_standard_id, second instance gets the second value and so on...
        standard_id = lo_to_standard_id[lo_id][0]
        lo_to_standard_id[lo_id].pop(0)

        video_url = lesson[sheet_headers['Video Link']]
        if video_url == '':
            continue
        mvp_ready = lesson[sheet_headers['MVP Ready']]
        if mvp_ready == 'FALSE':
            continue

        thumbnail_data = get_thumbnail_row(lesson[sheet_headers['Lesson ID']], delivery_spreadsheet_id)

        resources_start_row, resources_end_row = lesson[sheet_headers['Video Resources']].split('range=')[1].split(':')
        resources_start_row = int(resources_start_row)
        resources_end_row = int(resources_end_row)

        resources_data = get_range_values(delivery_spreadsheet_id, sheet_info['video_resource_sheet_name'], resources_start_row, resources_end_row, 'A', 'N')
        subtitles_url = resources_data[0][resources_data_headers['Subtitles URL']]
        susbtitle_type = resources_data[0][resources_data_headers['Subtitles type']]
        VideoSubtitlesObject = VideoSubtitles(url=subtitles_url, type=susbtitle_type)

        splits = [row[resources_data_headers['Splits']] for row in resources_data]
        splits = [split for split in splits if split != '']
        video_parts: Dict[str, Video] = {}
        VideoSplitObject: List[VideoSplit] = []
        for split_index, split in enumerate(splits):
            split_url, split_name = extract_hyperlink_parts(split)
            split_durations = resources_data[split_index][resources_data_headers['Split Durations']]
            split_subtitles_url, _ = extract_hyperlink_parts(resources_data[split_index][resources_data_headers['Splits Subtitles']])
            split_subtitles_object = VideoSubtitles(url=split_subtitles_url, type=susbtitle_type)
            split_start, split_end = map(float, split_durations.split(' - '))
            split_thumbnail = Image(url=thumbnail_data[split_name.lower()])
            VideoSplitObject.append(VideoSplit(name=split_name, start=split_start, end=split_end, video=Video(url=split_url, title=split_name, subtitles=split_subtitles_object, thumbnail=split_thumbnail)))

            video_parts[split_name] = Video(url=split_url, title=split_name, subtitles=split_subtitles_object)
        
        lesson_thumbnail = Image(url=thumbnail_data["lesson thumbnail"])
        lessonObject = LessonVideoObject(url=video_url, title=lesson_name, subtitles=VideoSubtitlesObject, splits=VideoSplitObject, thumbnail=lesson_thumbnail)

        questionObjects: Dict[str, List[QuestionObject]] = {}
        for split_index, split in enumerate(splits):
            split_url, split_name = extract_hyperlink_parts(split)
            questionObjects[split_name] = []
            if split_name in ['Introduction', 'Conclusion']:
                continue
            split_durations = resources_data[split_index][resources_data_headers['Split Durations']]
            split_start, split_end = map(float, split_durations.split(' - '))
            question_cell_data = json.loads(resources_data[split_index][resources_data_headers['Questions']])
            for question in question_cell_data:
                question_time = question['time']
                question_video_split_time = question_time - split_start
                for ques in question['questions']:
                    questionObjects[split_name].append(QuestionObject(
                        time=question_time,
                        videoSplitTime=question_video_split_time,
                        videoSplitName=split_name,
                        question=ques['question'],
                        answer_options=ques['answer_options'],
                        background_image=ques['background_image'],
                        learning_content=ques['learning_content'],
                        speaker=ques['speaker']
                    ))
                    # print(questionObjects[-1].model_dump_json(indent=4))

        video_length = VideoSplitObject[-1].end
        lesson_topic = lesson[sheet_headers['Topic']]
        topic_count[lesson_topic] = topic_count.get(lesson_topic, 0) + 1
        learning_order = topic_count[lesson_topic]

        lessons_to_upload.append(LessonObject(
            lesson=lessonObject,
            video_parts=video_parts,
            questions=questionObjects,
            standard_id=standard_id,
            learning_order=learning_order,
            video_length=video_length
        ))

    return lessons_to_upload

def upload_lessons_to_stele(lessons_to_upload: List[LessonObject]):
    for item in tqdm(lessons_to_upload, desc='Uploading lessons to Stele', position=0, leave=True):
        lesson_response = upload_lesson_to_stele(item.lesson, item.standard_id, item.learning_order, item.video_length)
        # print(lesson_response)
        lesson_generated_content_id = lesson_response['data']['insertContent']['platformGeneratedContentId']

        for split_index, (split_name, video) in enumerate(tqdm(item.video_parts.items(), desc='Uploading video parts for the lesson', position=1, leave=False)):
            video_part_response = upload_video_part_to_stele(video, item.standard_id, lesson_generated_content_id, split_index+1)
            # print(video_part_response)
            video_part_generated_content_id = video_part_response['data']['insertContent']['platformGeneratedContentId']

            for question in tqdm(item.questions[split_name], desc='Uploading questions for the video part', position=2, leave=False):
                question_response = upload_question_to_stele(question, item.standard_id, video_part_generated_content_id)
                # print(question_response)

            
    print(f"Uploaded {len(lessons_to_upload)} lessons to Stele!")

if __name__ == "__main__":
    lessons_to_upload = prepare_lessons_to_upload('AP US History')
    upload_lessons_to_stele(lessons_to_upload)