import logging
import os
import subprocess

import cv2
import numpy as np

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
