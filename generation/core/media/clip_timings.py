import json
import logging
import re
import string
from typing import Dict, List, Tuple, Union
from pydub import AudioSegment
import subprocess
from core.types import (
    Clip, TranscriptOutput, TranscriptTiming, WordTiming)
from core.helpers import (
    print_json, split_transcript)
from prompts.clips_prompts import \
    IDENTIFY_CLIP_TIMINGS
from core.parsers import str_2_json
from core.context import APVideoContext as Context
from core.clients.openai import LLM, llm_complete, system_message, user_message
from core.clients.s3 import load_json_from_s3, save_json_to_s3

logger = logging.getLogger(__name__)

def segment_split_suggestions(timings: List[WordTiming]) -> List[Dict[str, Union[str, float]]]:
    bounds = [6.5, 8.5]
    ideal_duration = 7.5

    total_duration = round(timings[-1].end_time - timings[0].start_time, 3)
    average_word_duration = round(sum([t.end_time-t.start_time for t in timings])/len(timings), 3)
    max_duration: float = 8.5 if total_duration < 18 else 8

    num_segments = int(total_duration/max_duration + 0.999)
    target_duration = round(total_duration/num_segments, 3)
    logger.info(f"Suggested splits for video of length {total_duration}s will be at {target_duration}s. {num_segments} splits. Average word duration: {average_word_duration}s")

    segments = []
    current_segment = []
    current_segment_start_time = None
    
    for timing in timings:
        if not current_segment:
            current_segment_start_time = timing.start_time
            
        current_segment.append(timing)
        current_duration = timing.end_time - current_segment_start_time

        if current_duration > (target_duration - average_word_duration/2):
            segments.append(current_segment)
            current_segment = []

    if current_segment:
        if current_segment[-1].end_time - current_segment[0].start_time < 4.5:
            logger.info(f'Appending Leftover segment of duration {round(current_segment[-1].end_time - current_segment[0].start_time, 3)} to last segment of {round(segments[-1][-1].end_time - segments[-1][0].start_time, 3)}s')
            segments[-1].extend(current_segment)
        else:
            segments.append(current_segment)

    out = []
    for segment in segments:
        text = " ".join([s.text for s in segment])
        duration = segment[-1].end_time - segment[0].start_time

        add_tolerance = max((bounds[1] - duration)//average_word_duration, 0) 
        remove_tolerance = max((duration - bounds[0])//average_word_duration, 0) 

        out.append({
            'text': text,
            'start_time': segment[0].start_time,
            'end_time': segment[-1].end_time,
            'duration': duration,
            'positive_tolerance': f'Can add at most {add_tolerance} words to this segment' if add_tolerance>0 else f"{add_tolerance} words. Can't add words to this segment",
            'negative_tolerance': f'Can remove at most {remove_tolerance} words from this segment' if remove_tolerance>0 else f"{remove_tolerance} words. Can't remove words from this segment",
        })
    return out
    
   
def match_snippet_timings(timings: TranscriptTiming, clip: Clip) -> Tuple[float, float]:
    # Function to normalize text by removing punctuation, whitespace, and converting to lowercase
    def normalize(text):
        return re.sub(r'\W+', '', text).lower()
    
    # Normalize the substring and split it into tokens
    substring_tokens = [normalize(token) for token in clip.text.split()]
    len_substring = len(substring_tokens)
    
    # Normalize the words in the transcript timings
    processed_words = [normalize(word_timing.text) for word_timing in timings.timings]
    
    # Search for the substring tokens in the processed words
    for i in range(len(processed_words) - len_substring + 1):
        if processed_words[i:i+len_substring] == substring_tokens:
            clip.start_time = timings.timings[i].start_time
            clip.end_time = timings.timings[i + len_substring - 1].end_time
            clip.duration = round(clip.end_time - clip.start_time, 3)
            clip.duration_valid = 5<=clip.duration <=9 
            return clip
    
    return clip


def match_segment_timings(timings: TranscriptTiming, segment_text: str) -> Tuple[int, int]:
    def replace_dash_with_space(text: str)->str:
        return re.sub(r'[\u2010-\u2015\u2212\u23AF\u23E4\u2500\u2501\u2E3A\u2E3B\uFE58\uFE63\uFF0D-]', ' ', text) 
    def normalize(text:str)->str:
        return re.sub(r'\W+', '', text).lower()
    
    segment_text = re.sub(r'(?<=\w)\s+(?=&)', '', segment_text)
    segment_text = replace_dash_with_space(segment_text) 
    
    # Normalize the segment text and split it into tokens
    segment_tokens = [normalize(token) for token in segment_text.split()]
    len_segment = len(segment_tokens)
    
    # Normalize the words in the transcript timings and maintain mapping to original indices
    processed_words = []
    word_to_original_index = [] # Words from Elevenlabs are being split at dashes e.g. "labor-force". Labor and force will map to the same index i as was in the original timings instead of having indices i, i+1
    for idx, word_timing in enumerate(timings.timings):
        normalized_words = [normalize(w) for w in replace_dash_with_space(word_timing.text).split()]
        processed_words.extend(normalized_words)
        word_to_original_index.extend([idx] * len(normalized_words))  # All parts map to the same original index
    
    def segments_match(words: List[str], segment_tokens: List[str]) -> bool:
        if ("".join(words) == "".join(segment_tokens)): 
            return True
        return False

    # Search for the segment tokens in the processed words
    for i in range(len(processed_words) - len_segment + 1):
        if segments_match(processed_words[i:i+len_segment], segment_tokens):
            original_start_index = word_to_original_index[i]
            original_end_index = word_to_original_index[i + len_segment - 1]
            return original_start_index, original_end_index
    
    raw_transcript_words = [wt.text for wt in timings.timings]  # unnormalized
    print(raw_transcript_words, segment_text)
    # If no match is found, raise an exception
    raise ValueError(f"No matching segment found in the transcript timings for: {segment_text}")


def identify_word_index_in_transcript(splits: List[str], word: str, split_index: int) -> int:
    def clean_and_split(text: str) -> List[str]:
        cleaned_text = re.sub(r'[^\w\s]', '', text).lower()
        return cleaned_text.split()
    clean_word = re.sub(r'[^\w\s]', '', word).lower()
    
    # Clean and split words in each split up to the target split index
    cumulative_index = 0
    for split in splits[:split_index]:
        cumulative_index += len(clean_and_split(split))
    
    word_index = cumulative_index + clean_and_split(splits[split_index]).index(clean_word)
    return word_index


def extract_pause_times(text: str, timings: TranscriptTiming) -> List[Tuple[float, float]]:
    results = []
    break_pattern = re.compile(r'<break time="([\d.]+)s"\s*>')

    # Find all break tags (with their durations)
    for match in break_pattern.finditer(text):
        pause_duration = float(match.group(1))
        
        preceding_text = text[:match.start()]
        clean_preceding_text = break_pattern.sub('', preceding_text)
        words = re.split(r'\s+', clean_preceding_text.strip())
        last_10_words = " ".join(words[-10:])

        try:
            start_idx, end_idx = match_segment_timings(timings, last_10_words)
            paused_word = timings.timings[end_idx]

            offset = 0.4 if len(paused_word.text)<4 else 0.6 if len(paused_word.text)<8 else round(0.109 * len(paused_word.text) - 0.35, 4)
            if paused_word.end_time - paused_word.start_time > offset:
                results.append((max(paused_word.start_time + offset, paused_word.end_time-pause_duration), paused_word.end_time))
                print(f"pause duration was {pause_duration}. Computed offset for word '{paused_word.text}' was {round(offset, 3)}s. Compute pause duration = {round(results[-1][1]-results[-1][0], 3)}")
        except ValueError:
            print(f"Failed to match phrase: {last_10_words}")
            continue

    return results

def mute_intervals(
    audio_path: str,
    intervals: List[Tuple[float, float]],
    output_path: str
) -> None:
    audio_length = round(len(AudioSegment.from_mp3(audio_path)) / 1000.0, 3) 
    filters = []
    for start_time, end_time in intervals:
        if audio_length - end_time < 2.0:
            print(f"Updating end time of mute to audio end from {end_time} to {audio_length}")
            end_time = audio_length
        fade_len = min(0.25, end_time - start_time)
        filters.append(
            f"afade=enable='between(t,{start_time},{end_time})':"
            f"t=out:st={start_time}:d={fade_len}"
        )

    filter_str = ", ".join(filters)

    cmd = [
        "ffmpeg",
        "-y",  # overwrite output if present
        "-loglevel", "quiet",# Silence logs
        "-i", audio_path,
        "-af", filter_str,
        output_path
    ]

    subprocess.run(cmd, check=True)

def identify_video_split_indexes(transcript: TranscriptOutput, transcript_timings: TranscriptTiming):
    """
    This function identifies the video split indexes for the lesson video (end index for each split)
    """
    _, intro_end_index = match_segment_timings(transcript_timings, " ".join(transcript.lesson_transcript_breakdown.introduction.split()[-10:]))
    split_indexes = {
        "Introduction": intro_end_index,
        "Conclusion": len(transcript_timings.timings) - 1
    }

    for section_name, section in transcript.lesson_transcript_breakdown.sections.items():
        last_words_in_section = list(section.explanations.values())[-1].recap
        _, end_index = match_segment_timings(transcript_timings, last_words_in_section)
        split_indexes[section_name] = end_index

    return dict(sorted(split_indexes.items(), key=lambda x: x[1]))

def reset_timings(timings: TranscriptTiming):
    """
    This function resets the timings to start from 0
    """
    start = timings.timings[0].start_time
    for timing in timings.timings:
        timing.start_time -= start
        timing.end_time -= start
    return timings