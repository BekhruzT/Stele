import concurrent.futures
import json
import logging
import os
import re
import uuid
from io import BytesIO
from typing import Dict, List, Optional, Tuple, Union

import requests
from core.types import (
    AvatarAsset, AvatarIntroduction, LayerName, Speaker, TranscriptTiming,
    WordTiming)
from core.media.clip_timings import \
    identify_word_index_in_transcript
from core.log import (
    setup_logging, with_logging_context)
from core.helpers import (
    exception_handler, extract_tag_content, print_json, split_transcript)
from core.stage_constants import (
    CHARACTER_BUNDLE, elevenlabs_voice_descriptions, get_unit_from_chapter)
from core.clients.did import (
    create_avatar, create_listening_avatar)
from core.media.html_to_video import (
    generate_video_asset_from_html, render_template)
from prompts.avatar_prompts import (
    AVATAR_INTRODUCTION_PROMPT, AVATAR_INTRODUCTION_TRIGGER_WORD_PROMPT,
    GENERATE_AVATER_IMAGE_PROMPT, GENERATE_AVATER_IMAGE_USER_PROMPT,
    MATCH_SIGNIFICANT_FIGURE_VOICE_PROMPT, SPEAKER_IDENTIFIER_PROMPT)
from prompts.common_prompts import \
    get_subject_specific_general_prompt_entries
from core.parsers import str_2_json
from core.clients.images import generate_flux_image_portrait
from fuzzywuzzy import process
from PIL import Image
from pydub import AudioSegment
from core.context import APVideoContext as Context
from core.hash import hash_image_description
from core.logger import Logger
from core.clients.openai import (LLM, ensure_json, llm_complete, system_message,
                          user_message)
from core.clients.s3 import (create_presigned_url, does_file_exist, is_local,
                      load_json_from_s3, save_json_to_s3, upload_file_to_s3)
from core.clients.speech import (combine_audio_timings, get_audio_duration,
                          mute_intervals, synthesize_speech)

# logger = Logger("AvatarAssetsGenerator", logging.DEBUG)
logger = logging.getLogger(__name__)

def generate_listening_avatar_ssml(duration: float) -> str:
    ssml_chunks = []
    remaining_duration = duration
    while remaining_duration > 0:
        chunk_duration = min(remaining_duration, 5)
        ssml_chunk = f"<break time='{int(chunk_duration * 1000)}ms'/>"
        ssml_chunks.append(ssml_chunk)
        remaining_duration -= chunk_duration
    ssml_text = "".join(ssml_chunks)
    return ssml_text

def find_best_voice(context: Context, speaker: str, image_prompt: str):
    messages = [
        system_message(MATCH_SIGNIFICANT_FIGURE_VOICE_PROMPT.format(voices = json.dumps(elevenlabs_voice_descriptions, indent=2),  **get_subject_specific_general_prompt_entries(context.subject))),
        user_message(f"{context.category} Figure: {speaker}\nTopic: {get_unit_from_chapter(context.subject, context.chapter)} - {context.subsection}.\nPortrait Description: {image_prompt}")
    ]
    voice_id = extract_tag_content('voice_id', llm_complete(messages, model=LLM.GPT_4_TURBO))
    return voice_id

def describe_avatars(subject: str, transcript: str, avatar_intros: Dict[str, str]) -> Dict[str, str]:
    messages = [
        system_message(AVATAR_INTRODUCTION_PROMPT.format(transcript=transcript, introducing_phrases=json.dumps(avatar_intros, indent=2), **get_subject_specific_general_prompt_entries(subject))),
        user_message(f"Here is the list of signficant personas:\n<personas>\n{json.dumps(list(avatar_intros.keys()), indent=2)}\n</personas>")
    ]
    avatar_introductions = llm_complete(messages, model=LLM.ANTHROPIC_CLAUDE_3_5_SONNET)

    return str_2_json(extract_tag_content('introductions', avatar_introductions))

def generate_introduction_overlay(context: Context, asset: AvatarIntroduction)->AvatarIntroduction:

    id = hash_image_description(asset.description)
    duration = min(asset.end_time-asset.start_time, 9)

    s3_video_path = context.media_path + f'Avatar/Introduction/{id}.mov'
    
    asset.src = generate_video_asset_from_html('avatar_introduction.html', s3_video_path, {'avatar_intro': asset.model_dump(), 'duration': duration}, duration, id=id)
    return asset

def identify_speaker_intro(speaker: str, avatar_asset: AvatarAsset) -> Dict[str, Union[str, float]]:

    text = " ".join([word.text for word in avatar_asset.timings])
    splits = re.split(r'(?<=[.!?])\s+', text) # Split transcript at punctuation marks
    speaker_intro_timings_template = {
        'figure': speaker,
        "phrase_index": 0,
        "word": ""
    }

    messages = [
        system_message(AVATAR_INTRODUCTION_TRIGGER_WORD_PROMPT.format(template=json.dumps(speaker_intro_timings_template, indent=2))),
        user_message(f"<phrases>\n{json.dumps({ii: split for ii, split in enumerate(splits)})}\n</phrases>")
    ]


    llm_response = llm_complete(messages, LLM.ANTHROPIC_CLAUDE_3_5_SONNET)
    try:
        response = str_2_json(extract_tag_content('matches', llm_response))
        trigger_word_index = identify_word_index_in_transcript(splits, response['word'], response['phrase_index'])
    except:
        logger.error(f"Failed to find intro of {speaker}, got response: \n```\n{llm_response}\n```. Speech was\n:{text}\n")
        trigger_word_index = -1 
        response = {'phrase_index': -1}

    return {
        'start_time': avatar_asset.start_time + avatar_asset.timings[trigger_word_index].end_time,
        'end_time': avatar_asset.end_time,
        'introducing_sentence': splits[response['phrase_index']]
    }

def generate_avatar_introductions(context: Context, avatar_assets: Dict[int, AvatarAsset]) -> Tuple[Dict[int, AvatarAsset], List[AvatarIntroduction]]:

    transcript = load_json_from_s3(context.transcripts_path)['lesson_transcript']

    speaker_intros = {} 
    for ii, asset in avatar_assets.items():
        speaker = asset.avatar_name
        if (speaker.lower() not in ['host', 'narrator']) and (speaker not in speaker_intros):

            speaker_intros[speaker] = identify_speaker_intro(speaker, avatar_assets[ii-1])
            speaker_intros[speaker]['index'] = ii 
    
    avatar_descriptions = describe_avatars(context.subject, transcript, {k: v['introducing_sentence'] for k,v in speaker_intros.items()})

    avatar_introductions = []
    indices = sorted(avatar_assets.keys())
    for avatar_name, intro_info in speaker_intros.items():
        index = intro_info['index']
        asset = avatar_assets[index]
        avatar_assets[intro_info['index']-1].avatar_display_time = intro_info['start_time']
        
        # Find the end time of the avatar's introduction
        avatar_end_time = asset.end_time
        index_pos = indices.index(index)
        for idx in indices[index_pos+1:]:
            if avatar_assets[idx].avatar_name == avatar_name:
                avatar_end_time = avatar_assets[idx].end_time
            else:
                break
        
        # Create the AvatarIntroduction object
        introduction = AvatarIntroduction(
            avatar_name=avatar_name,
            description=avatar_descriptions[avatar_name],
            start_time=avatar_assets[intro_info['index']-1].avatar_display_time,
            end_time=avatar_assets[intro_info['index']-1].avatar_display_time + max(
                avatar_assets[intro_info['index']-1].end_time-avatar_assets[intro_info['index']-1].avatar_display_time, 8
        ))

        introduction = generate_introduction_overlay(context, introduction)
        avatar_introductions.append(introduction)

        logger.info(f"For host speech starting at {avatar_assets[intro_info['index']-1].start_time}, introducing {avatar_name} at time {avatar_assets[intro_info['index']-1].avatar_display_time} with phrase: {introduction.description}.")

    return avatar_assets, avatar_introductions

def find_best_match(speaker: str, character_bundles: dict) -> Optional[str]:
    """Find the best matching character in the bundles using fuzzy matching and LLM."""
    top_20_matches = process.extract(speaker.lower(), character_bundles.keys(), limit=20)
    
    # Prepare the matches for LLM input
    matches_str = "\n".join([f"{match[0]}" for match in top_20_matches])
    
    prompt = SPEAKER_IDENTIFIER_PROMPT.format(speaker=speaker, candidate_matches=matches_str)

    llm_response = ensure_json(llm_complete([user_message(prompt)], model=LLM.ANTHROPIC_CLAUDE_3_5_SONNET))
    
    if llm_response and 'match_found' in llm_response and llm_response['match_found']:
        return llm_response.get('matching_candidate')
    else:
        return None

def load_speaker(context: Context, loaded_speakers: Dict[str, Speaker], segment: Dict):
    best_match = find_best_match(segment['speaker'], CHARACTER_BUNDLE)

    if best_match and best_match in CHARACTER_BUNDLE:
        try:
            # Load the character bundle from S3
            edited_path = f"{CHARACTER_BUNDLE[best_match][:-5]}-edited.json"
            if does_file_exist(edited_path):
                character_data = load_json_from_s3(edited_path)
            else:
                character_data = load_json_from_s3(CHARACTER_BUNDLE[best_match])
                
            # Use the pre-created character's image and prompt
            webp_url = character_data['imageUrl']
            png_path = f'/tmp/{uuid.uuid4()}.png'
            
            # Download and convert webp to png
            response = requests.get(webp_url)
            img = Image.open(BytesIO(response.content)).convert('RGB')
            img.save(png_path, 'PNG')
            
            # Upload to S3
            s3_key = f"{context.media_path}character_images/{os.path.basename(png_path)}"
            upload_file_to_s3(png_path, s3_key)
            
            # Create presigned URL
            image_url = create_presigned_url(s3_key, expiration=3600, url_style='path')
            
            # Clean up temporary file
            os.remove(png_path)
            image_prompt = "Not Available as imported speaker"

            speaker = Speaker(url=image_url, prompt=image_prompt)
        
            if 'voiceId' in character_data and character_data['voiceId']:
                speaker.voice_id = character_data['voiceId']
            else:
                logger.info(f"Pre created character {segment['speaker']} has no chosen voice. Picking from default voices...")
                speaker.voice_id = find_best_voice(context, segment['speaker'], "No image description found, please infer an appropriate voice based on the significant figure's name.")

            loaded_speakers[segment['speaker']] = speaker
            
            logger.info(f"Using pre-created character bundle for {segment['speaker']} (matched with {best_match}). Chosen voice is: {speaker.voice_id}")
            return loaded_speakers
        except Exception as e:
            logger.error(f"Failed to load pre-created character bundle for {segment['speaker']}: {str(e)}. Falling back to generating new image.")

    # If no suitable match found or if loading pre-created bundle failed, proceed with generating a new photo-realistic image
    logger.info(f"No pre-created character bundle found for {segment['speaker']}, generating a new image.")
    
    messages = [
        system_message(GENERATE_AVATER_IMAGE_PROMPT.format(**get_subject_specific_general_prompt_entries(context.subject))),
        user_message(GENERATE_AVATER_IMAGE_USER_PROMPT.format(figure_name=segment['speaker'], topic=context.subsection, unit=get_unit_from_chapter(context.subject, context.chapter), **get_subject_specific_general_prompt_entries(context.subject)))
    ]

    image_prompt = extract_tag_content('prompt', llm_complete(messages, model=LLM.GPT_4_TURBO))
    image_url = generate_flux_image_portrait(image_prompt)
    if image_url == "NSFW":
        raise Exception(f"Generation of image for {segment['speaker']} failed as it contained NSFW concepts.")
    
    voice_id = find_best_voice(context, segment['speaker'], image_prompt)

    speaker = Speaker(url=image_url, prompt=image_prompt, voice_id=voice_id)
    logger.info(f"Generated image for speaker {segment['speaker']}: {image_url}. Chosen voice: {voice_id}. Prompt:\n{image_prompt}")
    loaded_speakers[segment['speaker']] = speaker
    return loaded_speakers

@exception_handler
def create_avatar_asset_audio(context: Context, host_names: List[str], loaded_speakers: Dict[str, Speaker], speaker_segments: List[Dict], index: int, segment: Dict, segment_clip_prefix_name: str, previous_request_ids: List[str]=[]) -> Tuple[AvatarAsset, List[str]]:
    is_host = segment['speaker'].lower() in host_names
    is_listening_avatar = False

    if is_host:
        prev_speaker = speaker_segments[index - 1]['speaker'] if index > 0 else None
        next_speaker = speaker_segments[index + 1]['speaker'] if index < len(speaker_segments) - 1 else None
        is_listening_avatar = (prev_speaker == next_speaker) and (prev_speaker not in host_names) and (prev_speaker is not None)

    previous_text, next_text = "", ""
    if not is_host:
        if index > 1 and speaker_segments[index - 2]['speaker'] == segment['speaker']:
            previous_text = f"[Speaker]: {speaker_segments[index - 2]['dialogue']}\n[Responder]: {speaker_segments[index - 1]['dialogue']}"
        
        if index < len(speaker_segments) - 2 and speaker_segments[index + 2]['speaker'] == segment['speaker']:
            next_text = f"[Responder]: {speaker_segments[index + 1]['dialogue']}\n[Speaker]: {speaker_segments[index + 2]['dialogue']}"
                
    # Generate audio for all segments, including host, with their dialogue
    audio_s3_path = context.media_path + f'{segment_clip_prefix_name}.mp3'
    voice_id = 'IKne3meq5aSn9XLyUdCD' if is_host else loaded_speakers[segment['speaker']].voice_id  # Voice IDs for host and others
    try:
        speech_timings, request_ids = synthesize_speech(
            f'/tmp/{segment_clip_prefix_name}.mp3', 
            segment['dialogue'], context.media_path, 
            voice=voice_id, previous_text=previous_text, 
            next_text=next_text, previous_request_ids=previous_request_ids,
            speed=1.1 if is_host else 1.0
        )

    except Exception as e:
        core_error = str(e.__cause__) if e.__cause__ else str(e)
        logger.info(f"Error on voice: {segment['speaker']} - {voice_id}. {core_error}")
        if "detected_captcha_voice" in core_error:
            loaded_speakers[segment['speaker']].voice_id = find_best_voice(context, segment['speaker'], 'No image prompt, identify best voice for significant figure\'s name')
            speech_timings, request_ids = synthesize_speech(
                f'/tmp/{segment_clip_prefix_name}.mp3', 
                segment['dialogue'], context.media_path, 
                voice=loaded_speakers[segment['speaker']].voice_id, previous_text=previous_text, 
                next_text=next_text, previous_request_ids=previous_request_ids, speed=1.1 if is_host else 1.0
            )
            logger.info(f"Changed, {segment['speaker']} - {voice_id}, to a default voice: {loaded_speakers[segment['speaker']].voice_id}")
        else: 
            raise e

        
    # Create AvatarAsset with audio-related fields
    avatar_asset = AvatarAsset(
        avatar_name=segment['speaker'],
        timings=speech_timings,
        src=audio_s3_path,
        start_time=0.0,  # will be updated later
        end_time=get_audio_duration(f'/tmp/{segment_clip_prefix_name}.mp3'),
        is_listening_avatar=is_listening_avatar  # Store is_listening_avatar for later use
    )

    return avatar_asset, request_ids

@exception_handler
def create_avatar_asset_video(
    context: Context,
    host_names: List[str],
    loaded_speakers: Dict[str, Speaker],
    speaker_segments: List[Dict],
    index: int,
    segment: Dict,
    segment_clip_prefix_name: str,
    avatar_asset: AvatarAsset
) -> AvatarAsset:
    is_host = segment['speaker'].lower() in host_names
    is_listening_avatar = avatar_asset.is_listening_avatar
    # Calculate the time difference for the new condition
    should_create_listening_avatar = is_listening_avatar or ((avatar_asset.avatar_display_time - avatar_asset.start_time) > 0.5)
    listening_speaker = speaker_segments[index - 1]['speaker'] if is_listening_avatar else speaker_segments[index + 1]['speaker'] if should_create_listening_avatar else None

    if not is_host or should_create_listening_avatar:
        logger.info(f"The listening speaker is {listening_speaker} at index {index}. It is first intro: {not is_listening_avatar}" if should_create_listening_avatar else f"Speaker is {segment['speaker']}")
 
        speaker = listening_speaker if should_create_listening_avatar else segment['speaker']
        segment_avatar = loaded_speakers[speaker]
        image_url = segment_avatar.url
        image_prompt = segment_avatar.prompt

        if should_create_listening_avatar:
            if is_listening_avatar:
                # Original case: use duration of host audio
                audio_duration = get_audio_duration(f'/tmp/{segment_clip_prefix_name}.mp3')
                logger.info(f"Creating a {audio_duration}s listening avatar")
            else:
                # New condition: use the specified duration
                audio_duration = avatar_asset.end_time - avatar_asset.avatar_display_time
                logger.info(f"Creating a {audio_duration}s listening avatar for introduction")

            avatar_video_s3_path = create_listening_avatar(
                image_url,
                generate_listening_avatar_ssml(audio_duration),
                video_file_path=f"/tmp/{segment_clip_prefix_name}_listening.mp4",
                s3_prefix=context.media_path + 'avatar_assets'
            )
        else:
            # Use the regular audio for non-host avatar video creation
            audio_url = create_presigned_url(avatar_asset.src, expiration=3600, url_style='path')
            logger.info(f"Creating {get_audio_duration(f'/tmp/{segment_clip_prefix_name}.mp3')}s speaking avatar")
            avatar_video_s3_path = create_avatar(
                audio_url, 
                image_url, 
                video_file_path=f"/tmp/{segment_clip_prefix_name}.mp4", 
                s3_prefix=context.media_path + 'avatar_assets'
            )

        # Update the AvatarAsset instance with video-related fields
        avatar_asset.avatar_name = speaker if not is_host else 'HOST'
        avatar_asset.image = image_url
        avatar_asset.prompt = image_prompt
        avatar_asset.avatar_clip = avatar_video_s3_path
        avatar_asset.is_listening_avatar = should_create_listening_avatar

    return avatar_asset

def group_speaker_segments(speaker_segments: List[Dict], segment_clip_prefix_names: List[str]) -> List:
    args_by_speaker = {}
    for ii in range(len(speaker_segments)):
        speaker = speaker_segments[ii]['speaker'].lower().strip()
        if speaker not in args_by_speaker:
            args_by_speaker[speaker] = []
        args_by_speaker[speaker].append((ii, speaker_segments[ii], segment_clip_prefix_names[ii]))

    grouped_segments = []
    
    # Add host segments individually for full parallelization
    if 'host' in args_by_speaker:
        grouped_segments.extend([[segment] for segment in args_by_speaker['host']])
    if 'narrator' in args_by_speaker:
        grouped_segments.extend([[segment] for segment in args_by_speaker['narrator']])
        
    # Add non-host segments as complete sequences per speaker
    grouped_segments.extend([
        segments for speaker, segments in args_by_speaker.items() 
        if speaker not in ['host', 'narrator']
    ])
    
    return grouped_segments

def grouped_avatar_asset_generation_audio(context: Context, host_names: List[str], 
                                          loaded_speakers: Dict[str, Speaker], 
                                          all_segments: List[Dict], 
                                          speaker_segments: List[Tuple[int, Dict, str]]) -> Dict[int, AvatarAsset]:
    output = {}
    previous_request_ids = []
    
    for ii, segment, segment_clip_prefix_name in speaker_segments:
        logger.info(f"Calling Audio Segment Generation {ii}. Speaker: {segment['speaker']}. Previous generations: {previous_request_ids[-3:]} ")
        avatar_asset, request_ids = create_avatar_asset_audio(
            context, host_names, loaded_speakers, all_segments, 
            ii, segment, segment_clip_prefix_name, previous_request_ids[-3:]
        )
        previous_request_ids.extend(request_ids)
        output[ii] = avatar_asset
    return output

@with_logging_context(layer=LayerName.AVATAR)
@exception_handler
def generate_avatar_assets(output_path: str, output_type: str, inputs: dict):
    logger.info("Generating Avatar Assets")
    context = Context(**inputs)

    transcript = load_json_from_s3(context.transcripts_path)['lesson_transcript_paused']
    speaker_segments = split_transcript(transcript)
    host_names = ['host', 'narrator']

    # Load unique speakers first
    loaded_speakers: Dict[str, Speaker] = {}
    for segment in speaker_segments:
        if segment['speaker'].lower() not in host_names and segment['speaker'] not in loaded_speakers:
            load_speaker(context, loaded_speakers, segment)

    # Generate assets for all speakers
    segment_clip_prefix_names = [
        hash_image_description(f"{context.subsection}_{segment['speaker']}_{idx}") 
        for idx, segment in enumerate(speaker_segments)
    ]

    all_avatar_assets = {}
    args_grouped_by_speaker = group_speaker_segments(speaker_segments, segment_clip_prefix_names)
    
    all_avatar_assets = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor: # Audio Generation with Elevenlabs. Limit is currently DID at 5/gen   
        future_results = list(executor.map(
            lambda args: grouped_avatar_asset_generation_audio(
                context, host_names, loaded_speakers, 
                speaker_segments, args
            ),
            args_grouped_by_speaker
        ))
        
        # Combine all results
        for result_dict in future_results:
            all_avatar_assets.update(result_dict)
        all_avatar_assets = dict(sorted(all_avatar_assets.items()))

    # Adjust start_time and end_time
    current_time = 0.0
    for ii, asset in all_avatar_assets.items():
        all_avatar_assets[ii].start_time = current_time
        all_avatar_assets[ii].end_time += current_time
        current_time = asset.end_time
        logger.info(f"Speaker {asset.avatar_name}, starts at {all_avatar_assets[ii].start_time}s and ends at {all_avatar_assets[ii].end_time}s")

    all_avatar_assets, avatar_introductions = generate_avatar_introductions(context, all_avatar_assets)

    # The only part of this stage D-ID touches, and the only part that needs a presigned URL
    # a vendor can fetch. Skipping it leaves avatar_clip and image unset on each asset, which
    # only ShotStack reads, and ShotStack is skipped under STORAGE=local too. Everything the
    # rest of the pipeline depends on -- the ElevenLabs audio above and the lesson_timings
    # built from it below -- is produced either way, so Text Overlays onward still run.
    if is_local():
        logger.info("STORAGE=local: skipping D-ID avatar video generation, keeping audio")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor: # Video Gen
            updated_avatar_assets = list(executor.map(
                lambda ii: create_avatar_asset_video(context, host_names, loaded_speakers, speaker_segments, ii, speaker_segments[ii], segment_clip_prefix_names[ii], all_avatar_assets[ii]),
                range(len(speaker_segments))
            ))
        for ii, updated_avatar_asset in enumerate(updated_avatar_assets):
            all_avatar_assets[ii] = updated_avatar_asset

    # Convert to ordered list
    avatar_assets = [all_avatar_assets[i] for i in range(len(speaker_segments))]

    # Prepare lesson_timings
    lesson_timings = combine_audio_timings(
        audio_timings_list=[asset.timings for asset in avatar_assets], 
        end_times=[asset.end_time for asset in avatar_assets]
    )

    return {
        'avatar_assets': [asset.model_dump() for asset in avatar_assets],
        'lesson_timings': [t.model_dump() for t in lesson_timings],
        'avatar_introductions': [a.model_dump() for a in avatar_introductions]
    }

if __name__ == '__main__':
    from config.courses import get_execution_input
    from core.context import prep_content_gen_input
    from core.clients.s3 import download
    setup_logging(level=logging.DEBUG)
    exec_input    = get_execution_input(
        subject = "AP US History - vUnit_8_new", 
        chapter = "Period 8: 1945-1980",
        section = "The Vietnam War",
        subsection = "Explain the causes and effects of the Vietnam War",
    )
    context = Context(**prep_content_gen_input(exec_input))
    assets = load_json_from_s3(context.avatar_assets_path)['avatar_assets']
    time = 318
    asset = next(asset for asset in assets if asset['end_time']>time and asset['start_time']<time)
    # print_json(asset)
    # intro = AvatarIntroduction(**{
    #   "start_time": 570.022,
    #   "end_time": 581.408,
    #   "avatar_name": "Zheng He",
    #   "description": "Commander of China's greatest treasure ship fleet",
    #   "src": "college_board/AP World History: Video Lessons 2/AP World History - vUnit_4_new/media/962adc0b/Avatar/Introduction/75e3a336.mov"
    # })
    # generate_introduction_overlay(context, intro)

    asset_id = asset['src'].split('/')[-1].split('.')[0]
    logger.info("Audio path:" + context.media_path + f"{asset_id}.mp3")
    logger.info("Video path:" + context.media_path + f"avatar_assets{asset_id}.mp4")
    download(context.media_path + f"{asset_id}.mp3", f"{asset_id}.mp3")
    mute_intervals(f"./{asset_id}.mp3", [(55.2, 57)], f"./{asset_id}-muted.mp3")    # download the audio with above lines and determine the mute intervals manullay
    upload_file_to_s3(f"./{asset_id}-muted.mp3", context.media_path + f"{asset_id}.mp3")
    
    # t, ids = synthesize_speech(
    #     file_path=f'./hello.mp3',
    #     text="Today we're exploring What made the Song Dynasty So Successful. Spanning from 960 to 1279 A.D., the Song Dynasty was a period of remarkable cultural and economic growth in China. Renowned for its technological advancements, flourishing arts, and the establishment of a strong centralized government, the dynasty set the foundation for modern Chinese society. <break time=\"1.5s\"> In examining the Song dynasty's success, we'll look at how Confucian and Neo-Confucian ideas shaped government <break time=\"0.75s\"> , explore how the merit-based civil service exams created an effective administration <break time=\"0.75s\"> , and see how these systems led to lasting political stability, social advancement, and economic growth in medieval China <break time=\"0.75s\"> . By the end of this lesson, you'll understand how the Song Dynasty's unique combination of ethics and innovation created a lasting legacy. <break time=\"2.0s\">",
    #     s3_media_path=f"custom/media/",
    #     voice= "IKne3meq5aSn9XLyUdCD",
    #     previous_request_ids=[],
    #     speed=1.2
    # )
    # create_listening_avatar(
    #     create_presigned_url(context.media_path + "character_images/asdasd-adsdafa-qwqqe-31312.jpg"),
    #     generate_listening_avatar_ssml(11.7),
    #     video_file_path=f"/tmp/02103599_listening.mp4",
    #     s3_prefix=context.media_path + 'avatar_assets'
    # )

    create_avatar(
        create_presigned_url(context.media_path + f"{asset_id}.mp3"),
        create_presigned_url(context.media_path + "character_images/" + re.search(r'character_images/(.*?)\?X-Amz-Algorithm=', asset['image']).group(1)),
        f"./avatar_assets{asset_id}.mp4",
        context.media_path
    )
    # print(json.dumps([c.text for c in t]))

    