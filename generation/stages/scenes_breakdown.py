import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from core.types import (
    Clip, LayerName, Media, OverlaysData, TranscriptTiming, WordTiming)
from core.media.clip_timings import (
    match_segment_timings, segment_split_suggestions)
from core.log import (
    ContextAwareThreadPoolExecutor, with_logging_context)
from core.helpers import (
    exception_handler, llm_call, split_transcript, identify_location)
from prompts.clips_prompts import (
    FIX_CLIPS_USER_PROMPT, get_system_prompt_define_clips, get_user_prompt_define_clips)
from core.context import Context
from core.clients.openai import (LLM)
from core.clients.s3 import (load_json_from_s3)

logger = logging.getLogger(__name__)

def split_paragraphs(text: str, current_index: int) -> List[Tuple[Tuple[int, int], str]]:

    paragraphs = text.split('\n')

    def split_large_paragraph(paragraph: str, start_index: int) -> List[Tuple[Tuple[int, int], str]]:
        sentences = re.split(r'(?<=[.!?]) +', paragraph)
        results = []
        while len(sentences) > 5:
            mid_point = len(sentences) // 2
            part1 = ' '.join(sentences[:mid_point])
            part2 = ' '.join(sentences[mid_point:])
            part1_end_index = start_index + len(part1.split())
            results.extend(split_large_paragraph(part1, start_index))
            results.extend(split_large_paragraph(part2, part1_end_index))
            return results
        end_index = start_index + len(paragraph.split()) 
        return [((start_index, end_index), paragraph)]

    result = []
    for paragraph in paragraphs:
        if paragraph.strip():
            result.extend(split_large_paragraph(paragraph, current_index))
        current_index += len(paragraph.split()) 

    return result


def split_segment_into_paragraphs(word_timings: List[WordTiming]) -> List[List[WordTiming]]:
    joined_text = " ".join(w.text for w in word_timings)
    split_results = split_paragraphs(joined_text, 0)  # returns [((start_idx, end_idx), paragraph_text), ...]

    sub_paragraphs = []
    for (start_idx, end_idx), _ in split_results:
        sub_paragraphs.append(word_timings[start_idx:end_idx])

    return sub_paragraphs

def split_transcript_into_video_segments(transcript: List[WordTiming], overlays: OverlaysData) -> Tuple[List[Dict[str, Any]], List[Tuple[float, float]]]:
    # conclusion_slide is optional, so drop it when a video type turned it off.
    overlays = [*overlays.text_slides, *overlays.diagrams, *([overlays.conclusion_slide] if overlays.conclusion_slide else [])]
    overlay_intervals = sorted((o.start_time, o.end_time) for o in overlays)

    # With no overlays at all the whole lesson is one video span, split into paragraph clips.
    if not overlay_intervals:
        return [{'word_timings': p, 'is_video_clip': True} for p in split_segment_into_paragraphs(transcript)], []

    intervals = [overlay_intervals[0]]
    for s, e in overlay_intervals[1:]:
        if s - 1 <= intervals[-1][1]:
            # If two consecutive diagrams are less than 1 second part assume they are neighbours appearing one after the other - specific case is Lesson Organizer followed by first section organizer. section organizer usually has a start time just before the lesson organizers end time.
            intervals[-1] = (intervals[-1][0], e)
        else:
            intervals.append((s, e))

    def gather_words_in_range(start_t: float, end_t: float) -> List[WordTiming]:
        return [
            w for w in transcript
            if w.end_time > start_t and w.end_time <= end_t
        ]

    segments = []
    last_end = transcript[0].start_time
    final_time = transcript[-1].end_time

    for (start_t, end_t) in intervals:
        if last_end < start_t:
            leftover = gather_words_in_range(last_end, start_t)
            # print("VIDEO", " ".join([l.text for l in leftover]), (last_end, start_t), (leftover[0].end_time, leftover[-1].end_time))
            if leftover:
                split_leftover_segments = [{'word_timings': paragraph, 'is_video_clip': True} for paragraph in split_segment_into_paragraphs(leftover)]
                segments.extend(split_leftover_segments)

        overlay_words = gather_words_in_range(start_t, end_t)
        # print("DIAGRAM", " ".join([l.text for l in overlay_words]), (start_t, end_t), (overlay_words[0].end_time, overlay_words[-1].end_time))
        if overlay_words:
            segments.append({'word_timings': overlay_words, 'is_video_clip': False})

        last_end = max(last_end, end_t)

    if last_end < final_time:
        leftover = gather_words_in_range(last_end, final_time)
        if leftover:
            segments.extend([{'word_timings': paragraph, 'is_video_clip': True} for paragraph in split_segment_into_paragraphs(leftover)])
    return segments, intervals


def split_transcript_into_segments(text: str) -> List[Dict[str, str]]:
    transcript_by_speaker = split_transcript(text)  # Assumes this function is defined elsewhere
    result = []
    start_index = 0
    for item in transcript_by_speaker:
        speaker = item['speaker']
        dialogue = item['dialogue']
        segments = split_paragraphs(dialogue, start_index)
        for ranges, segment_text in segments:
            if len(segment_text.strip().split()) >= 2:
                result.append({'speaker': speaker, 'essay': segment_text, 'word_count_range': ranges})
                start_index = ranges[1]
            
    return result


def validate_clips(timings: List[WordTiming], clips: List[dict]) -> Tuple[List[dict], dict]:
    validation_errors = {'no_matching_phrase': [], 'phrase_too_short': []}
    clip_definitions = []

    for clip in clips:
        try:
            start_index, end_index = match_segment_timings(
                TranscriptTiming(timings=timings), clip['text']
            )
            clip_definitions.append({
                "text": clip['text'],
                "start_time": timings[start_index].start_time,
                "end_time": timings[end_index].end_time,
                "duration": timings[end_index].end_time - timings[start_index].start_time,
                "media": clip.get('media', {})
            })

            if len(clips)>1 and clip_definitions[-1]['duration'] < 3.0:
                validation_errors['phrase_too_short'].append(clip_definitions[-1]['text'])

        except Exception:
            validation_errors['no_matching_phrase'].append(clip['text'])
            continue
    return clip_definitions, validation_errors


def define_clips(
    context: Context,
    timings: List[WordTiming],
    speakers: List[str],
    retries: int = 2
) -> List[Clip]:
    suggested_splits = segment_split_suggestions(timings)
    essay = " ".join([t.text for t in timings])

    history, clips_raw = llm_call(
        system_prompt=get_system_prompt_define_clips(context),
        user_prompt=get_user_prompt_define_clips(essay, suggested_splits, speakers),
        model=LLM.CLAUDE_5_SONNET,
        tag="segments",
        is_json=True
    )

    clip_definitions, validation_errors = validate_clips(timings, clips_raw)
    attempt = 0
    while (validation_errors['phrase_too_short'] or validation_errors['no_matching_phrase']) \
          and attempt < retries:
        logger.error(f"CLIPS VALIDATION ERROR: {validation_errors}")
        attempt += 1
        history, clips_raw = llm_call(
            system_prompt='',
            user_prompt=FIX_CLIPS_USER_PROMPT.format(validation_errors = json.dumps(validation_errors, indent=2)),
            model=LLM.CLAUDE_5_SONNET,
            history=history,
            tag="segments",
            is_json=True
        )
        clip_definitions, validation_errors = validate_clips(timings, clips_raw)

    # Final Clip generation
    clips = [
        Clip(
            **{k:v for k,v in clip_def.items() if k!='media'},
            media=Media(**{**clip_def['media'], 'type': 'VIDEO', 'subject': context.subject})
        )
        for clip_def in clip_definitions
    ]

    # Identify the location being discussed as this clip displays
    for ii, clip in enumerate(clips): 
        clips[ii].location = identify_location(context, clip.text)

    return clips

def postprocess_clips(clips: List[Clip], overlay_intervals: List[Tuple[float, float]]) -> List[Clip]:
    def find_neighbouring_clips(overlay_interval: Tuple[float, float], clips: List[Clip]) -> Tuple[Optional[int], Optional[int]]:
        start, end = overlay_interval
        before_index = None
        after_index = None

        for i, clip in enumerate(clips):
            if clip.end_time <= start:
                before_index = i
            elif after_index is None and clip.start_time >= end:
                after_index = i
                break
        return before_index, after_index

    # Find all clips neighbouring with diagrams and text slides
    neighbouring_clip_indices = []
    for interval in overlay_intervals:
        before_index, after_index = find_neighbouring_clips(interval, clips)
        neighbouring_clip_indices.append({
            "neighbouring_indices": (before_index, after_index),
            "interval": interval
        })

    logger.debug(overlay_intervals)
    for ii, clip in enumerate(clips):

        if ii == 0: # ensure first clip has start time of 0
            clip.start_time = 0
            clip.duration = clip.end_time - clip.start_time
            continue
        
        matching_entries = [e for e in neighbouring_clip_indices if ii in e["neighbouring_indices"]]

        if matching_entries:
            for matching_entry in matching_entries:
                # If a clip preceding diagram/slide, extend the clip by 1.5s to account for the fading
                if matching_entry["neighbouring_indices"][0] == ii:
                    if len(matching_entries)<2:
                        clip.start_time = clips[ii-1].end_time
                    clip.end_time   = matching_entry["interval"][0]+1.5

                # If a clip is post diagram/slide, start clipd 1.5 s earlier to account for fade out
                elif matching_entry and matching_entry["neighbouring_indices"][1] == ii:
                    clip.start_time = matching_entry["interval"][1]-1.5


        # For all other clips align start time of clip with end time of previous clip to avoid gaps and black screens
        else:

            clip.start_time = clips[ii-1].end_time
        clip.duration = clip.end_time - clip.start_time

        # catching and fixing a bug where a clip duration goes very high
        if clip.duration > 20:
            logger.warning(f"Clip {ii} duration is greater than 20 seconds: {clip.duration} Fixing it...")
            clip.start_time = clips[ii-1].end_time if ii!=0 else 0
            clip.end_time = min(clip.end_time, clip.start_time + 20)
            clip.duration = clip.end_time - clip.start_time
        logger.debug(f"Last clip end: {0 if ii==0 else clips[ii-1].end_time}. Current clip start: {clip.start_time}")

    clips[-1].duration += 2 # Add extra 2 seconds to last clip
    clips[-1].end_time += 2

    return clips
@with_logging_context(layer=LayerName.CLIPS)
@exception_handler
def generate_clips(output_path, output_type, inputs):
    input = Context(**inputs)
    logger.info(f"Running Clip Generation: {input.key}")

    avatar_assets = load_json_from_s3(input.avatar_assets_path)
    overlays_data = OverlaysData(**load_json_from_s3(input.text_overlays_path))

    transcript_timings = TranscriptTiming(timings=avatar_assets['lesson_timings']).timings
    transcript_splits, overlay_intervals = split_transcript_into_video_segments(transcript_timings, overlays_data)

    speakers = [intro['avatar_name'] for intro in avatar_assets['avatar_introductions']]
    # transcript_splits = split_transcript_into_segments(transcript)
    logger.info(f"Transcript Splits: {len(transcript_splits)}")

    def define_clips_wrapper(split, ii):
        if not split['is_video_clip']:
            return []
        return define_clips(input, split['word_timings'], speakers)

    with ContextAwareThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(define_clips_wrapper, transcript_splits, range(len(transcript_splits))))
    
    clips = sorted([clip for clips_list in results for clip in clips_list], key=lambda clip: clip.start_time)
    # print_json([c.model_dump() for c in clips])
    clips = postprocess_clips(clips, overlay_intervals)

    return {'clips': [clip.dict() for clip in clips]}
