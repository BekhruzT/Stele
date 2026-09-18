import concurrent.futures
import json
import logging
import os
import random
import re
import string
import subprocess
import time
import uuid
from pydantic import BaseModel
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple, Union

import boto3
import cv2
import fal_client
import numpy as np
import requests
from core.helpers import print_json
from core.types import (
    ArtifactImage, DiagramVisual, OverlaysData, TranscriptTiming, Diagram, TextSlide)
from core.clients.sheets import \
    get_range_values
from core.clients.images import (GeneratedImageTypes, generate_image,
                                          save_image)
from core.context import APVideoContext as Context
from core.clients.s3 import load_json_from_s3, upload_file_to_s3

logger = logging.getLogger(__name__)

def is_frame_black(frame, threshold=10):
    """Check if a frame is essentially black (below threshold)"""
    # Convert to grayscale if it's a color image
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    
    # Calculate mean brightness
    mean_brightness = np.mean(gray)
    return mean_brightness < threshold

def is_video_black(video_src: str, threshold=10):
    """Check if a video has black frames at key timestamps (0s and after each extension)"""
    cap = cv2.VideoCapture(video_src)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    timestamp = 0
    while timestamp < duration:
        frame_number = int(timestamp * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if not ret:
            logger.error(f"Failed to read frame at timestamp {timestamp}s in video: {video_src}")
            continue
        if is_frame_black(frame, threshold):
            logger.warning(f"Black frame detected at timestamp {timestamp}s in video: {video_src}")
            return True
        timestamp += 5.1 if timestamp == 0 else 4
    cap.release()
    return False

def speed_up_video(file_path: str, factor: float) -> str:
    dir_name = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    name, ext = os.path.splitext(file_name)
    
    output_path = os.path.join(dir_name, f"{name}_speed_{factor}{ext}")
    
    video_filter = f"setpts=PTS/{factor}"
    
    if factor > 2.0 or factor<0.25:
        factor = min(2.0, max(0.25, factor))
        logger.warning(f"Can't handle speed up factors above 2.0 or less than 2.5. Updating factor to {factor}")

    audio_filter = ""
    if 0.25 <= factor < 0.5:
        audio_filter = "atempo=0.5,atempo=" + str(factor/0.5)
    elif 0.5 <= factor <= 2.0:
        audio_filter = f"atempo={factor}"
    
    cmd = [
        "ffmpeg",
        "-i", file_path,
        "-filter:v", video_filter,
        "-filter:a", audio_filter,
        "-map", "0:v",      # Include video stream
        "-map", "0:a?",     # Include audio stream if it exists
        "-c:v", "libx264",  # Use H.264 for video encoding
        "-preset", "slow",  # Better quality encoding
        "-crf", "18",       # High quality (lower value = higher quality, 18-23 is good range)
        "-c:a", "aac",      # Use AAC for audio encoding
        "-b:a", "192k",     # Higher audio bitrate
        "-y",
        output_path
    ]
    
    subprocess.run(cmd, check=True)
    
    os.remove(file_path)
    os.rename(output_path, file_path)

def get_video_duration(file_name):
    import cv2

    # Open the video file
    video = cv2.VideoCapture(file_name)
    
    # Check if video opened successfully
    if not video.isOpened():
        print(f"Error: Could not open video file {file_name}")
        return None
    
    # Get frame count and frames per second
    frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = video.get(cv2.CAP_PROP_FPS)
    
    # Calculate duration
    duration = frame_count / fps if fps > 0 else 0
    
    # Release the video object
    video.release()
    
    return duration

def convert_mov_to_mp4(mov_path, mp4_path=None):  
    if mp4_path is None:
        base_name = os.path.basename(mov_path).replace('.mov', '.mp4')
        mp4_path = f"./{base_name}"
    
    cmd = [
        'ffmpeg',
        '-i', mov_path,            # Input file
        '-c:v', 'libx264',         # Video codec
        '-c:a', 'aac',             # Audio codec
        '-strict', 'experimental', # For AAC codec compatibility
        '-y',                      # Overwrite output file if exists
        mp4_path                   # Output file
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)

def get_lesson_artifacts(context: Context, spreadsheet_id = "1b1m-zpLGf8YFt-AGo_SlYOtEW4puPaBa8sAMAPxTtwU") -> List[ArtifactImage]:
    sheet_name = "AP World History Artifacts" if "World History" in context.subject else "AP US History Artifacts"
    subject = "AP US History" if "US" in sheet_name else "AP World History"
    
    values = get_range_values(spreadsheet_id, sheet_name, 2, 1000, 'A', 'J')
    
    artifacts = []
    for row in values:
        lesson_id = row[4]
        name = row[5]
        fact = row[6]
        image_url = row[7].replace('=IMAGE("', '').strip('")')
        if lesson_id == context.key and image_url and fact and bool(row[9]):
            artifact = ArtifactImage(
                # src=image_url,
                src=f"https://gen-ai-textbooks-media.s3.us-east-1.amazonaws.com/HistoryArtifacts/{subject}/{lesson_id}/{name}.png",
                name=name,
                fact=fact
            )
            artifacts.append(artifact)
    
    return artifacts

def update_lesson_artifacts(sheet_name: str = "AP World History Artifacts", spreadsheet_id = "1b1m-zpLGf8YFt-AGo_SlYOtEW4puPaBa8sAMAPxTtwU"):
    subject = "AP US History" if "US" in sheet_name else "AP World History"
    values = get_range_values(spreadsheet_id, sheet_name, 2, 1000, 'A', 'J')
    
    for row in values:
            
        lesson_id = row[4]
        name = row[5]
        image_url = row[7].replace('=IMAGE("', '').strip('")')

        file_name = f"{name}.png"
        try:
          save_image(image_url, "/tmp/" + file_name)

          url = upload_file_to_s3("/tmp/" + file_name, f"HistoryArtifacts/{subject}/{lesson_id}/{file_name}", s3_bucket="gen-ai-textbooks-media")
          print(url)
        except:
          print(f"COULDN;t download {name}: {image_url}")
          continue
    return 

def identify_artifact_image_timing(self, transcript_timings: TranscriptTiming) -> DiagramVisual:
    if self.visuals is None:
        return self
    
    unmatched_phrases = []
    for artifact in self.visuals:
        if isinstance(artifact.phrase, str):
            unmatched_phrases, (start_index, end_index) = match_segment_timings(transcript_timings, artifact.phrase, unmatched_phrases)
            artifact.start_time = transcript_timings.timings[start_index].start_time
            artifact.end_time = transcript_timings.timings[end_index].end_time
        else:
            unmatched_phrases, (start_index, _) = match_segment_timings(transcript_timings, artifact.phrase[0], unmatched_phrases)
            unmatched_phrases, (_, end_index) = match_segment_timings(transcript_timings, artifact.phrase[1], unmatched_phrases)

            artifact.start_time = transcript_timings.timings[start_index].start_time
            artifact.end_time = transcript_timings.timings[end_index].end_time
    return self

def truncate_phrases(obj):
    if isinstance(obj, BaseModel):
        for field_name, field_value in obj:
            if field_name == 'phrase' and isinstance(field_value, str):
                setattr(obj, field_name, ' '.join(field_value.split()[:3]))
            else:
                truncate_phrases(field_value)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'phrase' and isinstance(v, str):
                obj[k] = ' '.join(v.split()[:3])
            else:
                truncate_phrases(v)
    elif isinstance(obj, list):
        for item in obj:
            truncate_phrases(item)
    return obj

def update_transcript_with_artifact_reference(transcript: str, diagram: dict, artifact: ArtifactImage) -> Tuple[str, ArtifactImage]:
    from core.helpers import (
        extract_tag_content, llm_call)
    from prompts.prompts import (
        TRANSCRIPT_INSERT_VISUAL_REFERENCE_SYSTEM_PROMPT,
        TRANSCRIPT_INSERT_VISUAL_REFERENCE_USER_PROMPT)
    from core.clients.openai import LLM

    if isinstance(diagram, Diagram):
        diagram = truncate_phrases(diagram)

    _, response = llm_call(
        system_prompt=TRANSCRIPT_INSERT_VISUAL_REFERENCE_SYSTEM_PROMPT,
        user_prompt=TRANSCRIPT_INSERT_VISUAL_REFERENCE_USER_PROMPT.format(
            transcript=transcript, 
            diagram=json.dumps(diagram, indent=2), 
            artifact=artifact.name
        ),
        model=LLM.CLAUDE_5_SONNET
    )

    insert_method = extract_tag_content("method", response).strip()

    if insert_method == "Contextual Reference":
        artifact.phrase = extract_tag_content("context_phrase", response).strip()
    elif insert_method == "Pause":
        artifact.phrase = (extract_tag_content("prior_phrase", response).strip(), extract_tag_content("post_phrase", response).strip())
    elif insert_method == "Direct Reference":
        transcript = extract_tag_content("transcript", response).strip()
        artifact.phrase = extract_tag_content("reference_phrase", response).strip()

    return transcript, artifact

def convert_mov_to_mp4(mov_path, mp4_path=None):  
    if mp4_path is None:
        base_name = os.path.basename(mov_path).replace('.mov', '.mp4')
        mp4_path = f"./{base_name}"
    
    cmd = [
        'ffmpeg',
        '-i', mov_path,            # Input file
        '-c:v', 'libx264',         # Video codec
        '-c:a', 'aac',             # Audio codec
        '-strict', 'experimental', # For AAC codec compatibility
        '-y',                      # Overwrite output file if exists
        mp4_path                   # Output file
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
        
if __name__=="__main__":
    from core.types import (
        Diagram, DiagramType, MindMap, OverlaysData, TextSlide,
        TranscriptOutput, TreeDiagram, VennDiagram, VideoPlan)
    from core.media.html_to_video import (
        render_diagram_template, render_text_slide_template)
    from config.courses import get_execution_input
    from core.context import prep_content_gen_input
    exec_input    = get_execution_input(
        subject = "AP World History - vUnit_1", 
        subsection = "Explain the effects of innovation on the Chinese economy over time."
    )
    context = Context(**prep_content_gen_input(exec_input))

    # assets = OverlaysData(**load_json_from_s3(context.text_overlays_path))

    # diagram = next(asset for asset in assets.diagrams+assets.text_slides if asset.end_time>315 and asset.start_time<315)
    # print(truncate_phrases(diagram))
    # convert_mov_to_mp4("./7f5697d6.mov")
    # print(get_lesson_artifacts(context))
    # update_lesson_artifacts()

def convert_mov_to_mp4(mov_path, mp4_path=None):  
    if mp4_path is None:
        base_name = os.path.basename(mov_path).replace('.mov', '.mp4')
        mp4_path = f"./{base_name}"
    
    cmd = [
        'ffmpeg',
        '-i', mov_path,            # Input file
        '-c:v', 'libx264',         # Video codec
        '-c:a', 'aac',             # Audio codec
        '-strict', 'experimental', # For AAC codec compatibility
        '-y',                      # Overwrite output file if exists
        mp4_path                   # Output file
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)