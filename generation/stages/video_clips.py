import concurrent.futures
import json
import logging
import os
import time
import fal_client
from typing import List, Optional, Tuple

from core.types import (
    Clip, ImagesMetadata, LayerName, VideoDetails, VideoClipQC, VideoMetadata)
from core.log import (
    ContextAwareThreadPoolExecutor, with_logging_context)
from core.media.media_assets import (
    is_video_black, speed_up_video
)
from core.helpers import (
    concurrency_slots, exception_handler, llm_call, generate_img_prompt, generate_video_prompt,
    extract_tag_content, save_video)
from prompts.clips_prompts import (
    AI_VIDEO_QC_PROMPT, AI_VIDEO_QC_SEVERITY_CHECK, 
    SECURE_VIDEO_PROMPT_SYSTEM_PROMPT)
from core.clients.images import GeneratedImageTypes
from lumaai import LumaAI
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed, wait_chain
from stages.image_clips import generate_image_wrapper
from core.context import Context
from core.clients.gemini import gemini_media_analysis, delete_old_gemini_files
from core.clients.openai import (LLM, assistant_message, llm_complete, system_message, user_message)
from core.clients.s3 import (create_presigned_url, does_file_exist,
                      load_json_from_s3, save_json_to_s3, upload_file_to_s3)

logger = logging.getLogger(__name__)


def secure_prompt(prompt: str):

    messages = [
        system_message(SECURE_VIDEO_PROMPT_SYSTEM_PROMPT),
        user_message(prompt)
    ]

    response = llm_complete(messages, LLM.CLAUDE_5_SONNET)
    
    return extract_tag_content('prompt', response)

def reimagine_image_prompt(context: Context, clip: Clip, qc_reasoning: str):
    from prompts.clips_prompts import (
        REIMAGINE_SCENE_EXCLUDED_FIGURES, REIMAGINE_SCENE_QC_REASON, REIMAGINE_SCENE_TOLERANCE,
        REIMAGINE_SCENE_USER_PROMPT, get_system_prompt_define_clips, get_user_prompt_define_clips)

    history = [
        system_message(get_system_prompt_define_clips(context)),
        user_message(get_user_prompt_define_clips(clip.text, {'text': clip.text, **REIMAGINE_SCENE_TOLERANCE}, REIMAGINE_SCENE_EXCLUDED_FIGURES)),
        assistant_message("<segments>{out}</segments>".format(out=json.dumps({"text": clip.text, "media": {"description": clip.media.description}}, indent=2)))
    ]

    user_msg = REIMAGINE_SCENE_USER_PROMPT
    if qc_reasoning:
        user_msg += REIMAGINE_SCENE_QC_REASON.format(qc_reasoning=qc_reasoning)

    _, clips_raw = llm_call(
        system_prompt='',
        user_prompt=user_msg,
        model=LLM.CLAUDE_5_SONNET,
        tag="segments",
        history=history, 
        is_json=True
    )
    if isinstance(clips_raw, list):
        clip.media.description = clips_raw[0]['media']['description']
    else:
        clip.media.description = clips_raw['media']['description']

    clip.media.img_prompt =  generate_img_prompt(context.subject, clip.media.description)
    clip.media.video_prompt = generate_video_prompt(context.subject, clip.media.description, clip.media.video_prompt)

    return clip


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=7, max=90))
def gemini_video_qc(video_path: str) -> VideoClipQC:
    chat, response = gemini_media_analysis(AI_VIDEO_QC_PROMPT, video_path, LLM.GEMINI_2_5)

    verdict = extract_tag_content("verdict", response)
    reason = extract_tag_content("reason", response)

    if verdict is None:
        raise Exception(f"Gemini QC didn't return a verdict. Recieved response:\n{response}")
    
    qc = VideoClipQC(passed=verdict.lower() == 'pass', reason=reason)
    if not qc.passed:
        try:
            severity_response = chat.send_message(AI_VIDEO_QC_SEVERITY_CHECK).text.strip()
            qc.severity = extract_tag_content("severity", severity_response)
        except:
            qc.severity = "UNKNOWN"

        logger.info(f"AI Video {os.path.basename(video_path)} failed. Severity: {qc.severity}. Reason: {reason}.")
    return qc

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=7, max=90))
def call_luma_generation(client, prompt: str, keyframe: dict):
    generation = client.generations.create(
        model="ray-1-6",
        prompt=prompt,
        keyframes={"frame0": keyframe}  # type: ignore
    )
    POLL_INTERVAL = 5 
    while True:
        time.sleep(POLL_INTERVAL)
        generation = client.generations.get(id=generation.id)

        if generation.state == "completed":
            video_url = generation.assets.video
            return generation, video_url
        elif generation.state == "failed":
            logger.error(f"Generation failed with reason: {generation.failure_reason}")
            logger.error(f"Generation: {generation}")
            raise Exception(f"Generation failed with reason: {generation.failure_reason}")
        
def create_generation_with_retries(client, prompt: str, keyframe: dict, max_retries: int):
    retry_count = 0

    while retry_count <= max_retries:
        try:
            return call_luma_generation(client, prompt, keyframe)
        except Exception as e:
            logger.error(f'Error during generation creation: {e}')
        retry_count += 1
        if retry_count == 2:
            prompt = 'Create a slow motion zoom in effect.'
        else:
            prompt = secure_prompt(prompt)
        logger.info(f'Retrying with updated prompt: "{prompt}". Retry count: {retry_count}')
    return None, None

@exception_handler
def generate_luma_video(video_src: str, prompt: str, s3_image_path: str, duration: float, retry: int = 0, status: str = '') -> str:
    MAX_RETRIES = 2
    logger.info(f'{status} Generating Luma video for {s3_image_path[48:]}: {prompt[:20]}')

    client = LumaAI(auth_token=os.environ.get("LUMAAI_API_KEY"))
    image_url = create_presigned_url(s3_image_path, url_style='path')

    extend_count = 0 if duration <= 5 else int((duration-5.0001)//4 + 1.1)
    generation, video_url = create_generation_with_retries(
        client=client,
        prompt=prompt,
        keyframe={
            "type": "image",
            "url": image_url
        },
        max_retries=MAX_RETRIES
    )

    if not generation:
        raise Exception('Failed to generate initial video.')
        

    # Extend the video as needed to reach the desired duration
    for i in range(extend_count):
        logger.info(f'{status} Extending video ({i + 1}/{extend_count}) for {s3_image_path}. Prompt: {prompt[:20]}')
        generation, video_url = create_generation_with_retries(
            client=client,
            prompt=prompt,
            keyframe={
                "type": "generation",
                "id": generation.id
            },
            max_retries=MAX_RETRIES
        )

        if not generation:
            logger.warning('Failed to extend the video. Using last successful video.')
            break

    # Save the final video to the specified path
    save_video(video_url, video_src)

    if is_video_black(video_src):
        if retry < 5:
            logger.warning(f"Generated video is black: {video_src}.\nGeneration: {generation}\nRegenerating...")
            return generate_luma_video(video_src, prompt, s3_image_path, duration, retry + 1)
        else:
            logger.error(f"Generated video is black even after 5 retries: {video_src}.\nGeneration: {generation}")
            raise Exception("Generated video is black")
    
    return video_url

@retry(stop=stop_after_attempt(3), wait=wait_chain(wait_fixed(5), wait_fixed(30)))
def generate_kling_video(video_src: str, prompt: str, s3_image_path: str, duration: int, status: str = '') -> str:
    logger.info(f'{status} Generating KLING video for {s3_image_path[48:]}: {prompt[:20]}')
    duration = 5 if duration<=5 else 10

    result = fal_client.run(
        "fal-ai/kling-video/v1.6/pro/image-to-video",
            arguments={
            "prompt": prompt,
            "image_url": create_presigned_url(s3_image_path),
            "duration": str(int(duration)),
        }
    )
    
    logger.info(result)

    save_video(result['video']['url'], video_src)
    return result['video']['url']

def generate_ai_video(video_src: str, prompt: str, s3_image_path: str, duration: float, status: str = '') -> VideoDetails:
    # model = 'KLING' if duration <= 10 else 'LUMA'
    model = 'KLING'
    if model == 'KLING':
        try:
            url = generate_kling_video(video_src, prompt, s3_image_path, min(9.5, duration), status=status)
        except Exception as e:
            logger.warning(f"KLING Video generation failed, falling back to LUMAI. Reason: {e}")
            url = generate_luma_video(video_src, prompt, s3_image_path, duration, status=status)
    if model == 'LUMA':
        url = generate_luma_video(video_src, prompt, s3_image_path, duration, status=status)
    return VideoDetails(prompt=prompt, src=video_src, model=model)


def generate_ai_video_with_qc(context: Context, clip: Clip, video_src: str, s3_image_path: str, status: str = '', retry: int = 0) -> list[VideoDetails]:
    logger.info(f"{status}) {retry} Starting Video Gen with QC on {clip.media.id}.")
    
    if retry!= 0:
        video_src = f"/tmp/{clip.media.id}-{retry}.mp4"

    video_details = generate_ai_video(video_src, clip.media.video_prompt, s3_image_path, clip.duration)
    video_details.qc = gemini_video_qc(video_src)
    video_details.retry = retry

    return [video_details] # REMOVE LINE TO ENABLE VIDEO QC WITH GEMINI
    
    all_video_details = [video_details]
    if retry<2 and ((not video_details.qc.passed) and video_details.qc.severity != 'MINOR'):
    # if retry<2 and not video_details.qc.passed:
        logger.info(f"{status}) {retry} Regenerating Video {video_src}. QC Failed.")
        
        if retry>0:
            clip = reimagine_image_prompt(context, clip, video_details.qc.reason) 
            image_model = GeneratedImageTypes.FLUX
            logger.info(f"{status}) Regenerating Image with {image_model}. {clip.media.img_prompt}")

        generate_image_wrapper(
            context,
            clip,
            video_src.replace('.mp4', '.png')
        )
        upload_file_to_s3(video_src.replace('.mp4', '.png'), s3_image_path)

        # Get list of VideoDetails from recursive call and extend our list
        additional_details = generate_ai_video_with_qc(context, clip, video_src, s3_image_path, status=status, retry = retry+1)
        all_video_details.extend(additional_details)
    else:
        logger.info(f"{status}) Completing Video generation. Final QC status: {'Pass' if video_details.qc.passed else 'Fail'}")

    return all_video_details

@exception_handler
def process_generate_ai_video(context: Context, clip: Clip, prompt: Optional[str]=None, status: str='') -> VideoMetadata:
    media = clip.media
    image_metadata = ImagesMetadata(**load_json_from_s3(context.media_path + f'images/{media.id}/{media.id}.json'))

    video_src = f'/tmp/{media.id}.mp4'
    s3_videos_folder = context.media_path + f'videos/{media.id}/'

    video_metadata = None
    if does_file_exist(s3_videos_folder + f'{media.id}.json'):
        video_metadata = VideoMetadata(**load_json_from_s3(s3_videos_folder + f'{media.id}.json'))

    logger.debug(f"{status} GENERATING VIDEO FOR: {media.id} {s3_videos_folder + f'{media.id}.mp4'}")
    
    s3_image_path = image_metadata.get_best_image().src
    clip.media.video_prompt = prompt if prompt else (media.video_prompt or "Slow-motion video, gentle crane shot")
    video_details = generate_ai_video_with_qc(context, clip, video_src, s3_image_path, status=status)

    if video_metadata:
        video_metadata.videos.extend(video_details)
        video_metadata.n_regenerations += len(video_details)
        video_metadata.human_choice = len(video_metadata.videos)-1
    else:
        video_metadata = VideoMetadata(
            id = media.id,
            prompt = clip.media.video_prompt,
            videos = video_details,
        )

    for ii, video in enumerate(video_details):

        if (clip.end_time - clip.start_time)>9.9:
            factor = 9.9/(clip.end_time - clip.start_time)
            speed_up_video(video.src, factor)
            logger.info(f"Found an over 10 second video with duration {round(clip.end_time - clip.start_time, 3)}s, slowing it down {factor}x")

        s3_file_path = s3_videos_folder + f'{media.id}-v{len(video_metadata.videos)}-{video.retry}.mp4'
        upload_file_to_s3(video.src, s3_file_path)
        video_metadata.videos[-len(video_details) + ii].src = s3_file_path
    
    save_json_to_s3(video_metadata.dict(), s3_videos_folder + f'{media.id}.json')
    return video_metadata


def collect_ungenerated_videos(context: Context, clips: List[Clip]) -> Tuple[List[VideoMetadata], List[Clip]]:
    generated_videos = []
    not_generated_clips = []
    
    def process_clip(clip):
        s3_videos_folder = context.media_path + f'videos/{clip.media.id}/'
        file_path = s3_videos_folder + f'{clip.media.id}.json'
        if clip.media.type == 'IMAGE':
            if ImagesMetadata(**load_json_from_s3(context.media_path + f'images/{clip.media.id}/{clip.media.id}.json')).type in [GeneratedImageTypes.FLUX, GeneratedImageTypes.GPT, GeneratedImageTypes.DALLE, GeneratedImageTypes.MIDJOURNEY]:
                logger.info(f"Found type image but generated with AI. Overriding type, running video gen: {clip.media.id}")
                return ('not_generated', clip)
            logger.info(f"Found type image. Skipping video gen: {clip.media.id}")
            return ('skip', {})        
        
        elif does_file_exist(file_path):
            data = load_json_from_s3(file_path)
            video_metadata = VideoMetadata(**data)
            return ('generated', video_metadata)
        
        else:
            return ('not_generated', clip)
    
    with ContextAwareThreadPoolExecutor(max_workers=32) as executor:
        futures = [executor.submit(process_clip, clip) for clip in clips]
        
        for future in concurrent.futures.as_completed(futures):
            result_type, result_value = future.result()
            if result_type == 'skip':
                continue
            if result_type == 'generated':
                generated_videos.append(result_value)
            else:
                not_generated_clips.append(result_value)
    
    return generated_videos, not_generated_clips
    
@with_logging_context(layer=LayerName.VIDEOS)
@exception_handler
@concurrency_slots(slots=3, lock_name="VIDEO_GEN_LOCK")
def generate_all_videos(output_path: str, output_type: str, inputs: dict, force: bool = False) -> dict:
    context = Context(**inputs)
    clips = [Clip(**clip) for clip in load_json_from_s3(context.clips_path)['clips']]

    start = time.time()
    if not force:
        generated_videos, not_generated_clips = collect_ungenerated_videos(context, clips)
    else:
        generated_videos, not_generated_clips = [], clips

    delete_old_gemini_files()

    logger.info(f"Identified {len(not_generated_clips)} videos to generate in {time.time() - start}s")

    futures = []
    with ContextAwareThreadPoolExecutor(max_workers=7) as exec: #50/min - 20/s. - 12x3 exceeding limit
        for i, clip in enumerate(not_generated_clips, 1):
            futures.append(exec.submit(process_generate_ai_video, context, clip, status=f"[{i}/{len(not_generated_clips)}]"))

    for future in futures:
        generated_videos.append(future.result())

    return {'videos': [metadata.dict() for metadata in generated_videos]}
