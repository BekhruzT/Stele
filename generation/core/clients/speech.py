import base64
import concurrent.futures
import json
import logging
import math
import os
import re
import string
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple, Union

import assemblyai as aai
import boto3
import requests
from bs4 import BeautifulSoup
from core.types import (
    TranscriptTiming, WordTiming)
from core.media.clip_timings import (
    extract_pause_times, mute_intervals)
from core.stage_constants import \
    elevenlabs_voice_descriptions
from core.parsers import str_2_json
from df.enhance import enhance, init_df
from df.io import load_audio, save_audio
from elevenlabs.client import ElevenLabs
from pydub import AudioSegment
from tenacity import retry, stop_after_attempt, wait_exponential
from core.constants import ELEVENLABS_API_KEY
from core.hash import hash_image_description
from core.clients.openai import (LLM, assistant_message, generate_speech_via_openai,
                          llm_complete, system_message, tts, user_message)
from core.clients.s3 import upload_file_to_s3

logger = logging.getLogger(__name__)

# ElevenLabs retired eleven_monolingual_v1 and eleven_multilingual_v1; requesting either now
# returns 400 unsupported_model, which took down every TTS call in the pipeline. v2 is the
# successor and still serves the /with-timestamps endpoint the word-level clock depends on.
# Override with ELEVENLABS_MODEL_ID, or per call by passing model_id through kwargs.
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

def clean_voice_with_elevenlabs(audio_path, out_path):
    client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

    with open(audio_path, "rb") as audio_file:
        audio_stream = client.audio_isolation.audio_isolation(audio=audio_file)
        audio_data = b''.join(chunk for chunk in audio_stream if isinstance(chunk, bytes))

    with open(out_path, "wb") as output_file:
        output_file.write(audio_data)

# Was defined to be used for deep filter net but breaks when running in multiple threads
@contextmanager
def suppress_all_output():
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    null_device = open(os.devnull, 'w')
    
    try:
        # Redirect both stdout and stderr to null device
        sys.stdout = null_device
        sys.stderr = null_device
        
        # Disable all logging
        logging.getLogger().setLevel(logging.CRITICAL + 1)  # Above all defined levels
        logging.disable(logging.CRITICAL)  # Disable all logging
        
        yield
    finally:
        # Restore original stdout/stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        null_device.close()
        
        # Re-enable logging if needed for other parts of the program
        logging.disable(logging.NOTSET)

def deep_filter_net(audio_path: str, output_path: str):
    model, df_state, _ = init_df()
    audio, _ = load_audio(audio_path, sr=df_state.sr())
    enhanced = enhance(model, df_state, audio)
    save_audio(output_path, enhanced, df_state.sr())
    
    if not os.path.isfile(output_path):
        raise Exception(f"Denoised audio for file {audio_path} failed to generate.")

def get_amplitude_info(mp3_path):
    audio = AudioSegment.from_mp3(mp3_path)
    samples = audio.get_array_of_samples()
    
    peak_amplitude = audio.max    # Maximum amplitude
    rms_amplitude = audio.rms     # Root mean square amplitude
    return {
        "peak_amplitude": peak_amplitude,
        "rms_amplitude": rms_amplitude
    }

def calculate_volume_adjustment(rms_amplitude: int, target_rms: int = 2250) -> float:
    # Target rms based on average voice amplitudes in elevenlabs
    if rms_amplitude == 0:
        return 1.0
    
    volume_factor = target_rms / rms_amplitude
    return min(max(volume_factor * 1.05, 0.5), 1.75) # Set limits on volume multiplier [0.5, 1750]

def adjust_audio_volume(input_path: str, output_path: str, volume_factor: float):
    audio = AudioSegment.from_file(input_path)
    gain_db = 20 * math.log10(volume_factor)
    adjusted_audio = audio.apply_gain(gain_db)
    adjusted_audio.export(output_path, format="mp3")

def standardize_volume(audio_path: str, output_path: str, amplitude: int = 2250):
    rms = get_amplitude_info(audio_path)['rms_amplitude']
    factor = calculate_volume_adjustment(rms, amplitude)
    adjust_audio_volume(audio_path, output_path, factor)

def seconds_to_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"

def group_words_fixed_interval(timings: List[WordTiming], interval: float = 2.0) -> List[List[WordTiming]]:
    groups = []
    current_group = []
    current_start_time = timings[0].start_time
    for word in timings:
        if word.end_time - current_start_time <= interval:
            current_group.append(word)
        else:
            groups.append(current_group)
            current_group = [word]
            current_start_time = word.start_time
    if current_group:
        groups.append(current_group)
    return groups

def group_words(timings: List[WordTiming]) -> List[List[WordTiming]]:
    groups = []
    n = len(timings)
    i = 0  # Index for the current word

    while i < n:
        current_group = []
        group_start_time = timings[i].start_time
        group_end_time = group_start_time
        group_duration = 0.0

        # Flag to indicate if the group has been extended beyond 2 seconds
        extended = False

        # Step 1: Add words until a punctuation mark is found or duration reaches 2 seconds
        while i < n and group_duration < 2.0:
            word = timings[i]
            current_group.append(word)
            group_end_time = word.end_time
            group_duration = group_end_time - group_start_time

            # Check for punctuation
            if re.search(r'[.,:;!?\-"]$', word.text.strip()) is not None:
                # End the group at punctuation mark
                i += 1  # Move to next word for the next group
                break  # Exit inner loop to start a new group

            i += 1  # Move to next word

        # If group ended due to duration reaching 2 seconds without punctuation
        if group_duration >= 2.0 and re.search(r'[.,:;!?\-"]$', current_group[-1].text.strip()) is None:
            # Step 2: Check for punctuation within the next 1 second (up to 3 seconds total)
            temp_group = current_group.copy()
            temp_i = i  # Temporary index for lookahead

            while temp_i < n:
                next_word = timings[temp_i]
                next_word_end_time = next_word.end_time
                extended_duration = next_word_end_time - group_start_time

                if extended_duration > 3.0:
                    break  # Do not extend beyond 3 seconds

                temp_group.append(next_word)

                if re.search(r'[.,:;!?\-"]$', next_word.text.strip()) is not None:
                    # Found punctuation within the extension window
                    current_group = temp_group  # Update current group
                    group_end_time = next_word_end_time
                    group_duration = extended_duration
                    i = temp_i + 1  # Move index to after the extended group
                    extended = True
                    break

                temp_i += 1

            if not extended:
                # No punctuation found within extension window, end group at 2 seconds
                # No need to adjust 'i' because it's already at the correct position
                pass  # The group remains as it was at 2 seconds

        # Append the group to the list of groups
        groups.append(current_group)

        # If the inner loops terminated due to reaching the end of timings
        if i >= n:
            break

        # If we haven't advanced 'i' in any of the above conditions, ensure we do so here
        # This handles cases where the group ended exactly at 2 seconds without punctuation
        if not extended and re.search(r'[.,:;!?\-"]$', current_group[-1].text.strip()) is None:
            # 'i' is already at the correct position
            pass

    return groups

def create_subtitles_file(transcript: TranscriptTiming, output_path: str = './output.srt') -> str:
    # groups = group_words_fixed_interval(transcript.timings, interval=3.0)
    groups = group_words(transcript.timings)
    logger.debug(json.dumps([[g.text for g in gs] for gs in groups], indent=2))
    srt_entries = []
    for index, group in enumerate(groups, start=1):
        start_timestamp = seconds_to_srt_timestamp(group[0].start_time)
        end_timestamp = seconds_to_srt_timestamp(group[-1].end_time)
        text = ' '.join([word.text for word in group])

        srt_entry = f"{index}\n{start_timestamp} --> {end_timestamp}\n{text}\n"
        srt_entries.append(srt_entry)
    
    srt = "\n".join(srt_entries)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(srt)

    return srt

def get_audio_duration(file_path: str) -> float:
    audio = AudioSegment.from_mp3(file_path)
    return round(len(audio) / 1000.0, 3) 

def transcribe_mp3(file_path: str) -> Tuple[List[Dict[str, Union[float, str]]], float]:
    aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")
    config = aai.TranscriptionConfig(speech_model=aai.SpeechModel.best, language_code="en_us")

    transcriber = aai.Transcriber(config=config)
    transcript = transcriber.transcribe(file_path)
    end_time = transcript.json_response['words'][-1]['end']/1000
    return [{k: v for k, v in word.items() if k in ['text', 'end', 'start']} for word in transcript.json_response['words']], end_time


def split_text(text: str, max_length: int = 4096) -> List[str]:
    snippets = []
    while len(text) > max_length:
        split_index = text.rfind('.', 0, max_length)
        if split_index == -1:
            split_index = max_length
        snippets.append(text[:split_index+1])
        text = text[split_index+1:].strip()
    snippets.append(text)
    return snippets


def combine_audio_files_sd(audio_files: List[str], output_file: str):
    logger.info("Running SD audio combiner")
    combined = AudioSegment.empty()
    for audio_file in audio_files:
        segment = AudioSegment.from_file(audio_file, format="mp3")
        combined += segment

    combined.export(output_file, format="mp3")


def combine_audio_files_hd(audio_files: List[str], output_file: str):
    file_path = f"{uuid.uuid4()}.txt"
    with open(file_path, 'w') as f:
        for audio_file in audio_files:
            f.write(f"file '{audio_file}'\n")
    subprocess.run([
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', file_path,
        '-c', 'copy',
        output_file
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    os.remove(file_path)


def combine_audio_files(audio_files: List[str], output_file: str):
    return combine_audio_files_sd(audio_files, output_file)
    # try:
    #     return combine_audio_files_hd(audio_files, output_file)
    # except:
    #     return combine_audio_files_sd(audio_files, output_file)

def process_chunks(chunks: List[WordTiming]):
    i = 0
    while i <= len(chunks) - 2:
        # print(chunks[i]['text'], chunks[i+1]['text'], chunks[i+2]['text'], chunks[i]['text'] == '<break', chunks[i+1]['text'].startswith('time="'), chunks[i+2]['text'].endswith('/>'))
        if "<breaktime=" in (chunks[i].text+ chunks[i+1].text).replace(' ', ''):

            start_popped = chunks[i].start_time
            end_popped = chunks[i+1].end_time

            # Remove the three chunks matching the pattern
            del chunks[i:i+2]

            # Adjust the timing of the previous or next chunk
            if i > 0:
                chunks[i-1].end_time = end_popped
            elif i < len(chunks):
                chunks[i].start_time = start_popped
        else:
            i += 1
    i = 0

    def is_punctuation_only(text):
        return all(char in string.punctuation or char.isspace() for char in text) and any(char in string.punctuation for char in text)
    while i < len(chunks):
        # Check if chunks[i].text is a punctuation mark only
        text = chunks[i].text
        if is_punctuation_only(text):
            # Punctuation mark only
            if i > 0:
                # Append punctuation to previous chunk
                chunks[i-1].text += text
                chunks[i-1].end_time = chunks[i].end_time
                # Delete current chunk
                del chunks[i]
            else:
                i += 1
        else:
            i += 1
    return chunks


def chars_to_word_timings(audio_dict: Dict[str, List[Union[str, float]]]) -> List[WordTiming]:
    characters = audio_dict['characters']
    starts = audio_dict['character_start_times_seconds']
    ends = audio_dict['character_end_times_seconds']

    word_list = []
    i = 0
    N = len(characters)

    while i < N:
        # Skip spaces
        while i < N and (characters[i] == ' ' or characters[i] == '\n'):
            i += 1
        if i >= N:
            break

        # Start of a new word
        word_start_index = i
        word_chars = []

        while i < N and characters[i] != ' ' and characters[i] != '\n':
            word_chars.append(characters[i])
            i += 1

        word_end_index = i - 1

        word_text = ''.join(word_chars)
        word_start_time = starts[word_start_index]
        word_end_time = ends[word_end_index]

        word_timing = WordTiming(
            text=word_text,
            start_time=word_start_time,
            end_time=word_end_time
        )
        word_list.append(word_timing)

    return word_list

def character_to_word_level_timings(audio_dict: Dict[str, List[Union[str, float]]]) -> List[WordTiming]:
    # Convert character-level timings to word-level timings for the current audio segment
    word_list = chars_to_word_timings(audio_dict)

    # Adjust the start and end times by adding the cumulative time
    adjusted_word_list = []
    for word in word_list:
        adjusted_start_time = round(word.start_time, 3)
        adjusted_end_time = round(word.end_time, 3)
        adjusted_word = WordTiming(
            text=word.text,
            start_time=adjusted_start_time,
            end_time=adjusted_end_time
        )
        adjusted_word_list.append(adjusted_word)

    return adjusted_word_list


def combine_audio_timings(audio_timings_list: List[List[WordTiming]], end_times: List[float]) -> List[WordTiming]:
    combined_timings = []
    cumulative_time = 0.0

    for ii, audio_timings in enumerate(audio_timings_list):
        for timing in audio_timings:
            adjusted_timing = WordTiming(
                text=timing.text,
                start_time=round(timing.start_time + cumulative_time, 3),
                end_time=round(timing.end_time + cumulative_time, 3)
            )
            combined_timings.append(adjusted_timing)
        if audio_timings:
            cumulative_time = end_times[ii]

    return combined_timings

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, max=30))
def generate_speech_via_elevenlabs(text:str, speech_file_path='./speech.mp3', voice='IKne3meq5aSn9XLyUdCD', **kwargs) -> Tuple[List[WordTiming], str]:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps"

    headers = {
    "Content-Type": "application/json",
    "xi-api-key": ELEVENLABS_API_KEY
    }

    voice_settings = {}
    if kwargs.get("speed", 1.0) != 1.0:
        voice_settings['voice_settings'] = {
            "speed": min(kwargs["speed"], 1.2),
            "stability": 0.5,
            "similarity_boost": 0.75,
        }
        del kwargs['speed']

    data = {
        "text": text.replace("*", ""),
        "voice_id": voice,
        "model_id": ELEVENLABS_MODEL_ID,
        **voice_settings,
        **kwargs
    }


    response = requests.post(
        url,
        json=data,
        headers=headers,
    )

    if response.status_code != 200:
        raise Exception(f"Error encountered, status: {response.status_code}, "
               f"content: {response.text}")

    request_id = response.headers["request-id"]
    audio = json.loads(response.content.decode("utf-8"))
    
    audio_bytes = base64.b64decode(audio["audio_base64"])

    with open(speech_file_path, 'wb') as f:
        f.write(audio_bytes)
    return character_to_word_level_timings(audio['alignment']), request_id

def generate_speech(text:str, speech_file_path='./speech.mp3', voice='IKne3meq5aSn9XLyUdCD', **kwargs) -> Tuple[List[WordTiming], List[str]]:
    # if voice in ['echo', 'onyx']:
    #     generate_speech_via_openai(text, speech_file_path, voice)
    # else:
    return generate_speech_via_elevenlabs(text, speech_file_path, voice, **kwargs)


def synthesize_speech(
        file_path: str, text: str, s3_media_path: str, voice: str = 'echo', **kwargs) -> Tuple[List[WordTiming], str]:
    enhanced_text = text #speech_enhance_transcript(text)
    character_timestamps = []
    request_ids = []
    if len(enhanced_text) >= 4096:  # limit is 5k in elevenlabs but sticking to this for simplicity
        logger.info(f"Chunked Speech Synthesis Running. {len(enhanced_text)//4096 + 1}")
        text_snippets = split_text(enhanced_text)
        temp_audio_files = []
        for i, snippet in enumerate(text_snippets):
            temp_file_path = f"{file_path.split('.')[0]}_temp_{i}.mp3"
            timestamps, request_id = generate_speech(snippet, temp_file_path, voice=voice, **kwargs)
            character_timestamps.append(timestamps)
            request_ids.append(request_id)
            temp_audio_files.append(temp_file_path)
        combine_audio_files(temp_audio_files, file_path)
        character_timestamps = combine_audio_timings(character_timestamps, [get_audio_duration(audio) for audio in temp_audio_files])
    else:
        logger.info("Single speech synthesis")
        character_timestamps, request_id = generate_speech(enhanced_text, file_path, voice=voice, **kwargs)
        request_ids.append(request_id)

    timings = process_chunks(character_timestamps)

    # pause_segments = extract_pause_times(text, TranscriptTiming(timings=timings))
    output_path = file_path
    # if pause_segments:
    #     output_path = os.path.join(os.path.dirname(file_path), f"muted-{os.path.basename(file_path)}")
    #     mute_intervals(file_path, pause_segments , output_path)
    
    # If voice is not a default Elevenlabs voice, run filter to remove background noise
    # if voice not in [*list(elevenlabs_voice_descriptions.keys()), 'IKne3meq5aSn9XLyUdCD']: 
    #     try:
    #         denoised_path = os.path.join(os.path.dirname(file_path), f"denoised-{os.path.basename(file_path)}")
    #         deep_filter_net(output_path, denoised_path)
    #         # clean_voice_with_elevenlabs(output_path, denoised_path)

    #         output_path = denoised_path
    #     except Exception as e:
    #         logger.error(e)

    standardize_volume(output_path, output_path)

    upload_file_to_s3(output_path, s3_media_path + os.path.basename(file_path))

    return timings, [id for id in request_ids if id]


def speech_enhance_transcript(transcript: str) -> str:
    """
    Enhances the transcript for TTS.
    """
    messages = [
        system_message(TRANSCRIPT_SPEECH_ENHANCEMENT_PROMPT),
        user_message(transcript)
    ]
    response = llm_complete(messages, model=LLM.ANTHROPIC_CLAUDE_3_5_SONNET)
    if not response:
        raise Exception("Speech enhancement failed.")
    return response

TRANSCRIPT_SPEECH_ENHANCEMENT_PROMPT = """
You are an expert in converting numerical values in text to their corresponding pronunciation based on the international number system. Here are some examples:
- "279" should be pronounced as "two hundred seventy-nine"
- "12696" should be pronounced as "twelve thousand six hundred ninety-six"
- "2,000,000" should be pronounced as "two million"
- "-1" should be pronounced as "negative one"
- "-3,400" should be pronounced as "negative three thousand four hundred"

You will be given a piece of text. Your task is to replace all numerical values with their corresponding pronunciations similar to the examples above. Please ensure that nothing else in the text is altered.
"""

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, max=30))
def get_voice_metadata(voice_id: str) -> Dict[str, Any]:
    url = f"https://api.elevenlabs.io/v1/voices/{voice_id}"
    
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY
    }
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Error getting voice metadata: {response.status_code} - {response.text}")
        
    return response.json()

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, max=30))
def get_voice_metadata(voice_id: str) -> Dict[str, Any]:
    url = f"https://api.elevenlabs.io/v1/voices/{voice_id}"
    
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY
    }
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Error getting voice metadata: {response.status_code} - {response.text}")
        
    return response.json()