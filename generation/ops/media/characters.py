import re
import json
import logging
from typing import Optional, List, Dict, Tuple, Union
from fuzzywuzzy import process
import tempfile
import concurrent.futures
import requests
import uuid
from PIL import Image
from io import BytesIO
import os
from pydub import AudioSegment

from core.clients.did import create_avatar, create_listening_avatar
from core.clients.images import generate_flux_image_portrait
from prompts.avatar_prompts import SPEAKER_IDENTIFIER_PROMPT, AVATAR_INTRODUCTION_PROMPT, GENERATE_AVATER_IMAGE_PROMPT, MATCH_SIGNIFICANT_FIGURE_VOICE_PROMPT, GENERATE_AVATER_IMAGE_USER_PROMPT, AVATAR_INTRODUCTION_TRIGGER_WORD_PROMPT
from core.clients.openai import ensure_json, llm_complete, LLM, user_message, system_message
from core.parsers import str_2_json
from core.clients.speech import synthesize_speech, combine_audio_timings, get_audio_duration, create_subtitles_file

from core.hash import hash_image_description
from core.constants import S3_MEDIA_BUCKET
from core.logger import Logger
from core.helpers import exception_handler, split_transcript, print_json, extract_tag_content
from core.clients.s3 import create_presigned_url, does_file_exist, load_json_from_s3, save_json_to_s3, upload_file_to_s3, S3_BUCKET, get_s3_client
from core.context import APVideoContext as Context
from core.stage_constants import CHARACTER_BUNDLE, get_unit_from_chapter, elevenlabs_voice_descriptions
from core.media.clip_timings import identify_word_index_in_transcript
from core.types import AvatarIntroduction, WordTiming, AvatarAsset, Speaker, TranscriptTiming, LayerName
from prompts.common_prompts import get_subject_specific_general_prompt_entries
from core.media.html_to_video import render_template, generate_video_asset_from_html
from core.log import setup_logging, with_logging_context


from core.context import prep_content_gen_input, get_lesson_context
from core.clients.openai import call_openai_vision
from PIL import Image
import ast
from core.clients.images import generate_image, GeneratedImageTypes, save_image
import concurrent.futures
import json
import threading

SYSTEM_PROMPT = """You are tasked with verifying whether a portrait corresponds to a given historic figure and their information. You will be provided with information about the historic figure and an actual portrait image. Your goal is to analyze the match between the two and provide an evaluation in a specific JSON format.

First, you will be given information about the historic figure:

Analyze the information and portrait image carefully. Focus on the following aspects:

1. Basic info and appearance:
   - Check if the sex, age, ethnicity, and general appearance in the image match the historic figure's information.
   - Assess whether facial features resemble those of the historic figure.
   - Determine if the attire is appropriate for the figure's status and era.

2. Time-appropriate elements:
   - Evaluate if the clothing and style are appropriate for the historic figure's era.
   - Look for any anachronistic elements that don't belong to the figure's time period.

After your analysis, compile your evaluation in the following JSON format:

<evaluation>
{
    "evaluation": {
        "basic_info": {
            "analysis": "<Your analysis of basic info and appearance>",
            "evaluation": "<Your evaluation of whether the basic info matches the character's appearance>"
        },
        "time_appropriate": {
            "analysis": "<Your analysis of time-appropriate elements>",
            "evaluation": "<Your evaluation of whether the figure's portrait includes anachronistic elements>"
        }
    },
    "violations": [
        "<List specific violations here>"
    ]
}
</evaluation>

Guidelines for listing violations:
- Only include violations that significantly mismatch the historic figure and could cause confusion for the viewer.
- If there are no major violations, leave the list empty.
- Minor discrepancies that don't affect the overall representation should not be listed as violations.

Here are some exemplar valid violation statements:
<examples>
 - The portrait depicts a person with blonde hair when the historic figure was known to have dark brown hair.
 - The portrait shows modern eyeglasses styles that were not invented during the historic figure's lifetime.
 - The portrait depicts traditional Chinese clothing on a European colonial-era figure who would have worn Western attire.
 - The portrait shows a t-shirt the figure wearing a t-shirt on Zhu Xi a figure from 12th Century, which is anachronistic clothing
</examples>

Ensure your evaluation is thorough, objective, and based solely on the information provided in the historic figure info and the visual elements in the portrait image. Do not make assumptions beyond what is explicitly stated or clearly visible.
"""

USER_PROMPT = """The historic figure you will be evaluating is {figure_name}, below is some information about them.

<historic_figure_info>
{figure_info}
</historic_figure_info>

Here is their portrait:
"""

class CharacterImageProcessor:
    def get_avatar_portrait_prompt(self, context: Context, speaker: str, info: json):
        messages = [
            system_message(GENERATE_AVATER_IMAGE_PROMPT.format(**get_subject_specific_general_prompt_entries(context.subject))),
            user_message(f"Compose a prompt for {speaker}, who will be portrayed as a historic figure. Here is some info about the character: {json.dumps(info, indent=2)}")
        ]

        image_prompt = extract_tag_content('prompt', llm_complete(messages, model=LLM.GPT_5))
        return image_prompt

    def create_thumbnail(self, image_path: str, thumbnail_path: str) -> None:
        with Image.open(image_path) as img:
            width, height = img.size
            top_offset = int(0.02 * height)
            
            left = 0
            upper = top_offset
            right = width
            lower = top_offset + width
            
            if lower > height:
                shift_up = lower - height
                upper -= shift_up
                lower -= shift_up
            
            cropped_img = img.crop((left, upper, right, lower))
            cropped_img.save(thumbnail_path)

    def update_character_json(self, character_json: dict, edited_path: str, portrait_path: str, thumbnail_path: str):
        import unicodedata, urllib.parse
        fix_string = lambda s: ''.join(c for c in unicodedata.normalize('NFKD', urllib.parse.unquote(s)) if not unicodedata.combining(c))
        name = fix_string(character_json["name"])
        portrait_s3_url = upload_file_to_s3(portrait_path, f'Public Images/Characters/{name}.jpg', s3_bucket=S3_MEDIA_BUCKET)
        thumbnail_s3_url = upload_file_to_s3(thumbnail_path, f'Public Images/Characters/{name}-thumbnail.jpg', s3_bucket=S3_MEDIA_BUCKET)
        character_json["imageUrl"] = portrait_s3_url.replace(" ", "%20")
        character_json["thumbnailUrl"] = thumbnail_s3_url.replace(" ", "%20")
        print(f"{character_json['name']} - {character_json['imageUrl']}")
        save_json_to_s3(character_json, edited_path)

    def replace_character_image(self, context, info: dict):
        import uuid
        prompt = self.get_avatar_portrait_prompt(context, info['name'], info)
        image_url = generate_flux_image_portrait(prompt)
        print(image_url)
        portrait_path = f"./{info['name']}.png"
        thumbnail_path = f"/tmp/{uuid.uuid4()}.png"
        save_image(image_url, portrait_path)
        self.create_thumbnail(portrait_path, thumbnail_path)
        return portrait_path, thumbnail_path

    def fix_character(self, context, edited_path: str, character_json: dict):
        # while True:
        portrait_path, thumbnail_path = self.replace_character_image(context, character_json)

            # user_validation = input(f"{info['name']} - (y/r)")
            # if user_validation== "y":
        self.update_character_json(character_json, edited_path, portrait_path, thumbnail_path)
                # break

    def process_violation(self, context, violation: Union[Tuple, str]):
        if isinstance(violation, tuple):
            ii, violation = violation
        else:
            ii = -1
            violation = dict(id = violation)

        if ii%100 == 0:
            print(f"Finished processing {ii} images.")

        if not violation.get('is_valid', True):
            return
        character_path = f"college_board/AP World History: Video Lessons/AP World History/character_bundles/{violation['id']}.json"
        edited_path = os.path.join(
            os.path.dirname(character_path),
            f"{os.path.basename(character_path)[:-5]}-edited.json"
        )
        if does_file_exist(edited_path):
            character_json = load_json_from_s3(edited_path)
        else:
            character_json = load_json_from_s3(character_path)
        self.fix_character(context, edited_path, character_json)

    def process_violations(self, context):
        with open("./violations-log.json", "r") as f:
            violations_log = json.load(f)
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(self.process_violation, context, (ii, v)) for ii, v in enumerate(violations_log)]
            for future in concurrent.futures.as_completed(futures):
                future.result()

class CharacterImageChecker:
    def __init__(self):
        self.lock = threading.Lock()  # Assuming 'lock' is defined in the outer scope

    def check_figure(self, figure_json):
        messages = [
            system_message(SYSTEM_PROMPT),
            {"role": "user",
            "content": [{"type": "text", "text": USER_PROMPT.format(figure_name=figure_json['name'], figure_info=json.dumps(figure_json, indent=2))},
                        {"type": "image_url", "image_url": {'url': figure_json['imageUrl']}}]}]
        response = call_openai_vision(messages, 'gpt-4o')

        evaluation = str_2_json(extract_tag_content('evaluation', response))
        return evaluation

    def log_violation(self, violation):
        with self.lock:
            with open("./violations-log.json", "r") as f:
                violations_log = json.load(f)
            violations_log.append(violation)
            with open("./violations-log.json", "w") as f:
                json.dump(violations_log, f)
                
    def process_character(self, ii, id_s3):
        try:
            id, s3_path = id_s3

            if (ii - 1) % 100 == 0:
                print(f"Checked {ii} characters")

            edited_path = os.path.join(
                os.path.dirname(s3_path),
                f"{os.path.basename(s3_path)[:-5]}-edited.json"
            )
            if does_file_exist(edited_path):
                character_json = load_json_from_s3(edited_path)
            else:
                character_json = load_json_from_s3(s3_path)

            if S3_MEDIA_BUCKET and S3_MEDIA_BUCKET in character_json["imageUrl"]:
                return

            evaluation = self.check_figure(character_json)
            if evaluation.get('violations', []):
                new_violation = {
                    "id": id, 
                    "info": f"{character_json['era']} || {character_json['ageGroup']} - {character_json['country']} - {character_json['bio']}",
                    "url": character_json["imageUrl"],
                    "violations": evaluation["violations"],
                    "is_valid": True
                }
                # Lock to ensure safe file I/O
                self.log_violation(new_violation)
        except Exception as e:
            try:
                new_violation = {
                    "id": id, 
                    "info": f"{character_json['era']} || {character_json['ageGroup']} - {character_json['country']} - {character_json['bio']}",
                    "url": character_json["imageUrl"],
                    "violations": [f"Error: {e}"],
                    "is_valid": True
                }
                self.log_violation(new_violation)
            except Exception as e:
                print(f"Failed to process character: {character_json.get('name', 'NonE')}. {e}")

    def check_character_images(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for ii, id_s3 in enumerate(CHARACTER_BUNDLE.items()):
                futures.append(executor.submit(self.process_character, ii, id_s3))

            for future in concurrent.futures.as_completed(futures):
                future.result()

def publish_edited_characters():
    source_bucket = S3_BUCKET
    source_prefix = "college_board/AP World History: Video Lessons/AP World History/character_bundles/"

    destination_bucket = S3_MEDIA_BUCKET
    destination_prefix = "Edited Character Bundle/"
    
    client = get_s3_client()
    
    # List objects in the source directory
    paginator = client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=source_bucket, Prefix=source_prefix)
    
    upload_urls = []
    
    # Create a temporary directory for downloading and uploading files
    with tempfile.TemporaryDirectory() as temp_dir:
        for page in pages:
            if 'Contents' not in page:
                print(f"No files found in {source_prefix}")
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                filename = os.path.basename(key)
                # Check if the file ends with -edited.json
                if filename.endswith('-edited.json'):
                    # Download the file to temp directory
                    local_path = os.path.join(temp_dir, filename)
                    client.download_file(source_bucket, key, local_path)
                    
                    # Upload to destination
                    destination_key = destination_prefix + filename
                    upload_url = upload_file_to_s3(local_path, destination_key, s3_bucket=destination_bucket)
                    
                    upload_urls.append(upload_url)
                    
                    print(f"Uploaded {filename} to {destination_bucket}/{destination_key}")
    
    print(f"Uploaded {len(upload_urls)} edited character bundle files to {destination_bucket}")
    return upload_urls

def update_voice(character: str, voice_id: str) -> None:
    s3_path = f"college_board/AP World History: Video Lessons/AP World History/character_bundles/{character}.json"
    edited_path = os.path.join(
        os.path.dirname(s3_path),
        f"{os.path.basename(s3_path)[:-5]}-edited.json"
    )
    if does_file_exist(edited_path):
        character_json = load_json_from_s3(edited_path)
    else:
        character_json = load_json_from_s3(s3_path)

    character_json['voiceId'] = voice_id
    save_json_to_s3(character_json, edited_path)

if __name__ == "__main__":
    context = prep_content_gen_input({
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons 2",
            "grade": "Grade 11",
            "subject": "AP World History - v7",
            "category": "High School: AP World History: Modern"
        },
        "Input": get_lesson_context("Explain the systems of government employed by Chinese dynasties and how they developed over time.")
    })
    context = Context(**context)


    # CharacterImageChecker().check_character_images() # Will run through all character jsons checking their images and identifying inconsistensicies with their description

    character_image_fixer = CharacterImageProcessor()
    # character_image_fixer.process_violations(context)
    character_image_fixer.process_violation(context, 'siddhartha_gautama') # Will generate a new image for th egiven character

