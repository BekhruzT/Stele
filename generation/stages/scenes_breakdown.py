import concurrent.futures
import json
import logging
import os
import re
import string
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple, Union

import boto3
import requests
from core.types import (
    Clip, LayerName, Media, OverlaysData, TranscriptTiming, WordTiming, VideoPlan)
from core.media.clip_timings import (
    match_segment_timings, match_snippet_timings, segment_split_suggestions)
from core.log import (
    ContextAwareThreadPoolExecutor, setup_logging, with_logging_context)
from core.helpers import (
    classify_image, construct_phrases, exception_handler, extract_tag_content,
    llm_call, print_json, split_transcript, identify_location)
from prompts.clips_prompts import (
    FIX_CLIPS_USER_PROMPT, IDENTIFY_CLIP_DURATIONS, MAP_IS_NECESSARY_PROMPT,
    get_system_prompt_define_clips, get_user_prompt_define_clips)
from core.parsers import str_2_json
from pydantic import BaseModel, model_validator, root_validator
from core.context import APVideoContext as Context
from core.clients.openai import (LLM, add_to_messages, assistant_message, ensure_json,
                          generate_speech_via_openai, llm_complete,
                          system_message, tts, user_message)
from core.clients.s3 import (create_presigned_url, download, load_json_from_s3,
                      read_content_from_s3, save_json_to_s3, upload_file_to_s3)

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

def handle_first_clips(context: Context, video_plan: VideoPlan, timings: List[WordTiming]) -> List[Clip]:
    segment_text = " ".join([t.text for t in timings])
    print(f"HANDLE FIRST CLIP GOT SEGMENT: {segment_text}")
    custom_instruction = f"""
For the first clip, choose a symbolic image that illustrates the main point of the lesson "{video_plan.lesson_title}". 
- Even if the lesson seems abstract, provide a visual depiction that quickly aids the student in grasping the lesson's content and visualizing it.
- Avoid using maps, geographic representations, or complex images. Instead, opt for a simple, relatable image that connects with the lesson's theme.

For clip two, covering the background information for the lesson besides the background visual visualizing the specified lesson context, suggest a map. Within the "media" field, add a new field called "map_description" where you describe the central map that would help contextualize the lesson. Set the geographic setting: this could be a generic political map or a custom map. Whatever it is just describe the map of the geographic area under concern and what it should capture. 
 - Don't get too specific with the map,  focus on critical attributes that must be captured not thing that are ideal but not necessary.
   - The simpler is the map requested the better. We want to show a simple map to help geographically contextualize the lesson not something that is intricate and will need close inspection to understand.
   - Keep it short, 10 words maximum
 - No need to ensure consistency with the previous image, your goal is to the best of your ability to contextualize the lesson. 
 - Do not request a custom map unless strictly necessary some allowed use cases are: to show spread of disease (if that's the central theme), specific routes (e.g. if silk road is the central theme), etc. in all other scenarios a simple political map should be sufficient.  Whatever the scenario do not request text or arrows on the maps.
 - Maps require descriptions that are as straightforward and brief as a Google search. The description should clearly mention the broader geographical area and the primary subject, without any extra customization or aesthetic details. Here are a few examples:
   - "Map of Europe showing German occupation at its peak in 1943"
   - "Map highlighting trade routes of the Silk Road"
   - "Map of Eurasia with a focus on the Mongol Empire"
- Examples of maps which are complex and their acceptable simplified counterparts: 
  - "Map of Indian Ocean showing monsoon wind patterns and major trade routes from 1200-1450 CE" => "Map of Indian Ocean showing major trade routes from 1200-1450 CE"
  - "Map of Europe showing the spread of Protestant and Catholic territories during the Reformation (1550)" => "Map of Christianity in 15th century"
  - "Map of the Americas showing Spanish and Portuguese colonial territories, major mining regions, and trade networks with indigenous populations (1550-1700)" => "Map of the Americas showing Spanish and Portuguese colonial territories"

- Make sure the two segments cover the entire transcript. Make sure to add any text padded to the end of sentence 2 in the transcript, to the second segment in your JSON response.
"""
    _, clips_raw = llm_call(
        system_prompt=get_system_prompt_define_clips(context),
        user_prompt=get_user_prompt_define_clips(segment_text, ["No suggested segment splits. Please divide the transcript into two parts at a logical point. Ideally, the split should occur between the lesson introduction and the background information."], speaker=[],custom_instruction=custom_instruction),
        model=LLM.CLAUDE_5_SONNET,
        tag="segments",
        is_json=True
    )
    clip_definitions, _ = validate_clips(timings, clips_raw)

    clips = [Clip(**{k:v for k,v in clip_def.items() if k!='media'}, media=Media(**{**clip_def['media'], 'type': 'VIDEO', 'subject': context.subject})) if ii!=1 else Clip(**{k:v for k,v in clip_def.items() if k!='media'}, media=Media(description=clip_def['media']["map_description"], img_prompt=clip_def['media']['description'], type="IMAGE"))
        for ii, clip_def in enumerate(clip_definitions)
    ]
    print_json(clips[1].model_dump(), "FIRST CLIP")
    return clips

def identify_maps(context: Context, clips: List[Clip]) -> List[Clip]:
    if 'history' not in context.subject.lower():
        return clips
    def process_clip(clip):
        return {'transcript_snippet': clip.text, 'suggested_visual': clip.media.description} if 'map' in clip.media.description.split('.')[0].lower() and classify_image(context.subject, clip.media.description).value.lower() == 'web' else None

    with ContextAwareThreadPoolExecutor(max_workers=5) as executor:
        potential_maps = {ii: result for ii, result in enumerate(executor.map(process_clip, clips)) if result}
    
    if not potential_maps:
        return clips
        
    messages = [
        system_message(MAP_IS_NECESSARY_PROMPT.format(topic=f'{context.unit}: {context.subsection}')),
        user_message(json.dumps(potential_maps, indent=2))
    ]

    response = str_2_json(extract_tag_content('answer', llm_complete(messages, LLM.CLAUDE_5_SONNET)))

    def process_response_item(item):
        ii, _map = item
        ii = int(ii)
        if _map['is_necessary']:
            logger.info(f"  NECESSARY MAP. Clip {ii} - '{clips[ii].text}'.")
            clips[ii].media.type = 'IMAGE'
            clips[ii].media.video_prompt = ''
        else:
            logger.info(f"UNNECESSARY MAP. Clip {ii} - '{clips[ii].text}'. Suggested visual: {_map['suggestion']}")
            clips[ii].media.description = _map['suggestion']
            clips[ii].media.img_prompt = ''
            clips[ii].media.video_prompt = ''
            clips[ii].media.enforce_prompts()

    with ContextAwareThreadPoolExecutor(max_workers=5) as executor:
        executor.map(process_response_item, response.items())

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

    # clips = identify_maps(input, clips)
    clips[-1].duration += 2 # Add extra 2 seconds to last clip
    clips[-1].end_time += 2

    return clips
@with_logging_context(layer=LayerName.CLIPS)
@exception_handler
def generate_clips(output_path, output_type, inputs):
    input = Context(**inputs)
    logger.info(f"Running Clip Generation: {input.key}")

    video_plan = VideoPlan(**load_json_from_s3(input.video_plan_path)['video_plan'])
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
        if video_plan.included_map and ii == 0:
            return handle_first_clips(input, video_plan, split['word_timings'])
        return define_clips(input, split['word_timings'], speakers)

    with ContextAwareThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(define_clips_wrapper, transcript_splits, range(len(transcript_splits))))
    
    clips = sorted([clip for clips_list in results for clip in clips_list], key=lambda clip: clip.start_time)
    # print_json([c.model_dump() for c in clips])
    clips = postprocess_clips(clips, overlay_intervals)

    return {'clips': [clip.dict() for clip in clips]}


if __name__ == '__main__':
    from core.context import prep_content_gen_input
    from config.courses import get_execution_input
    setup_logging(level=logging.DEBUG)
    exec_input    = get_execution_input(
        subject = "AP World History - v6", 
        subsection = "Explain the systems of government employed by Chinese dynasties and how they developed over time."
    )
    context = Context(**prep_content_gen_input(exec_input))
    # json.dump(generate_clips('', '', context), open('./clips.json', 'w'))

    intervals = [(15.546, 50.12), (68.307, 137.84), (182.833, 243.354), (253.43, 273.842), (316.15, 382.174), (411.506, 512.109), (524.694, 561.231)]
    clips = [Clip(**c) for c in json.load(open('./clips.json', 'r'))]
    postprocess_clips(clips, intervals)