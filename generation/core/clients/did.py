import time
from pathlib import Path
import json

import boto3
import requests
from core.constants import DID_API_KEY, S3_BUCKET


def get_s3_client():
    """Built on demand, not at import. stages/avatar_clips.py imports this module even when
    STORAGE=local skips every D-ID call, and constructing a boto3 client at module scope
    made that import need AWS config it never uses.
    """
    return boto3.client("s3")

# D-ID API credentials
api_url = "https://api.d-id.com"
create_talk_url = f"{api_url}/talks"
# Prepare headers
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": f"Basic {DID_API_KEY}",
}
temp = "<break time=\"5000ms\"/><break time=\"5000ms\"/><break time=\"5000ms\"/><break time=\"5000ms\"/><break time=\"5000ms\"/><break time=\"5000ms\"/><break time=\"5000ms\"/><break time=\"5000ms\"/><break time=\"5000ms\"/>"
def create_avatar(
    audio_url, image_url, video_file_path="./video.mp4", s3_prefix="avatars"
):    

    # print(f"Audio URL: {audio_url}")
    # print(f"Image URL: {image_url}")

    # Prepare the payload
    payload = {
        "source_url": image_url,
        "script": {"type": "audio", "audio_url": audio_url},
        "config": {"result_format": "mp4", "stitch": "true", "fluent": "true"},
    }

    # Create talk
    response = requests.post(create_talk_url, json=payload, headers=headers)
    return process_create_talk_response(response, video_file_path, s3_prefix)

def process_create_talk_response(response, video_file_path, s3_prefix):
    print(f"Response status code: {response.status_code}")
    # print(f"Response headers: {response.headers}")
    # print(f"Response content: {response.text}")
    response.raise_for_status()
    response_data = response.json()
    talk_id = response_data["id"]

    # print(f"Talk created with ID: {talk_id}")

    result_url = poll_for_completion(talk_id)

    download_video(result_url, video_file_path)

    s3_video_key = s3_prefix + Path(video_file_path).name
    get_s3_client().upload_file(video_file_path, S3_BUCKET, s3_video_key)
    print(f"Video uploaded to S3 with key: {s3_video_key}")

    return s3_video_key

def download_video(result_url, video_file_path):
    video_response = requests.get(result_url, stream=True)
    video_response.raise_for_status()

    # Save the video locally
    with open(video_file_path, "wb") as f:
        for chunk in video_response.iter_content(chunk_size=8 * 1024):
            if chunk:
                f.write(chunk)

    print("Video downloaded and saved")

def poll_for_completion(talk_id):
    get_talk_url = f"{api_url}/talks/{talk_id}"

    while True:
        response = requests.get(get_talk_url, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        status = response_data["status"]

        if status == "done":
            result_url = response_data["result_url"]
            print(f"Video generation completed. Result URL: {result_url}")
            return result_url
        elif status == "error":
            print(f"Error response: {json.dumps(response_data, indent=2)}")
            print("Error occurred during video generation")
            raise Exception("Error occurred during video generation")

        time.sleep(10)  # Wait for 10 seconds before polling again


def create_listening_avatar( image_url, ssml_text, video_file_path="./video.mp4", s3_prefix="avatars"):
    # print(f"Image URL: {image_url}")
    payload = {
        "source_url": image_url,
        "script": {
            "type": "text",
            "subtitles": "false",
            "provider": {
                "type": "microsoft",
                "voice_id": "Sara"
            },
            "input": ssml_text,
            "ssml": True
        },
        "config": {
            "fluent": "true",
            "pad_audio": "0.0",
            "result_format": "mp4",
            "stitch": "true"
        }
    }
    

    response = requests.post(create_talk_url, json=payload, headers=headers)

    return process_create_talk_response(response, video_file_path, s3_prefix)