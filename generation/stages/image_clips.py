import concurrent.futures
import json
import requests
import time
import re
import os
import string
import logging
import boto3
import traceback
from core.clients.openai import system_message, user_message, llm_complete, assistant_message
from typing import List, Dict, Optional, Any, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
import concurrent.futures
import uuid
import subprocess
from pydantic import BaseModel, root_validator, model_validator

from core.clients.openai import generate_speech_via_openai, tts, LLM
from core.clients.s3 import upload_file_to_s3, copy_s3_object, create_presigned_url, download, save_json_to_s3, read_content_from_s3, load_json_from_s3, does_file_exist
from core.context import APVideoContext as Context
from core.parsers import str_2_json
from core.helpers import construct_phrases, exception_handler, print_json, extract_tag_content, classify_image, llm_call, identify_location
from prompts.clips_prompts import IMAGE_CLASSIFICATION_PROMPT, MAP_IMAGE_PROMPT_TO_CAPTIONS_PROMPT, IMAGE_PROMPT_REWRITE_FROM_QC
from core.clients.images import generate_image, GeneratedImageTypes, save_image, find_lesson_map_from_db
from core.clients.image_qc import image_quality_check, absolute_image_qc
from core.hash import hash_image_description
from core.clients.sheets import update_images
from core.types import Media, Clip, ImageDetails, ImagesMetadata, OverlaysData, VideoMetadata, VideoDetails, LayerName
from core.stage_constants import get_unit_from_chapter
from lumaai import LumaAI
from tenacity import retry, stop_after_attempt, wait_exponential
from core.log import setup_logging, with_logging_context, ContextAwareThreadPoolExecutor

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=7, max=90))
def subject_specific_image_qc(context: Context, image_path: str, prompt: str, snippet: str, location:Optional[str]=None) -> Tuple[bool, str]:
    
    if location is None:
        location = identify_location(context, snippet)

    subject = context.subject.split('-')[0].strip()
    qc_conditions = {
        "history": [
            f"The image does not contain any elements that are anachronistic the time period, except for those specifically requested in the image prompt. The scene is set in the period - {get_unit_from_chapter(subject, context.chapter)}, so all elements should be appropriate for that era unless more contemporary objects are specifically requested.",
            "The image does not contain any legible textual or numeric elements.",
            f"The image content must be appropriate for the specified location. The image will be shown during a discussion about {location}, as part of the {subject} lesson on '{context.subsection}'. Ensure all elements shown realistically match both the identified location and the relevant time period.",
            f"If the image includes people, their appearance, clothing, hairstyles, and overall style should match their ethnicity and the time period ({get_unit_from_chapter(subject, context.chapter)}).",
            f"If people are the main subjects in the image and their faces are shown close-up (for example, a group sitting around a table), ensure each person's appearance while matching their ethnicity and the time period, also appears distinct. Faces should not look too similar; appropriate variation in age, beard style, hairstyle, and skin tone should be present."

        ],
        "biology": [
            "The image maintains correct anatomical proportions and relationships between biological structures. Cellular components, organs, or organisms should be sized appropriately relative to each other and follow established biological scaling.",
            "The image does not contain impossible or physically contradictory biological features (e.g., misplaced organelles, incorrect number of limbs/structures, anatomically impossible connections between systems).",
            "The image does not contain any text overlays, arrows, labels, numerical markers, or annotation-style elements unless specifically requested in the prompt. The visualization should be clean and free of explanatory additions.",
        ]
    }
    qc_conditions = qc_conditions['history' if 'history' in subject.lower() else 'biology']

    qc_response = absolute_image_qc(image_path, qc_conditions)
    logger.debug(f"\n```QC Response\n{json.dumps(qc_response, indent=2)}\n```")
    failed_evals = [
        {
            'condition': condition,
            'evaluation': response['evaluation']
        }
        for condition, response in qc_response.items()
        if response['status'] == 'FAIL'
    ]
    
    if not len(failed_evals):
        return True, qc_response

    logger.debug(f"\n```Fails\n{json.dumps(failed_evals, indent=2)}\n```")
    messages = [
        system_message(IMAGE_PROMPT_REWRITE_FROM_QC),
        user_message(f"Here is the original image prompt:\n<original_prompt>{prompt}</original_prompt>\nThe evaluation feedback for this prompt is:\n<evaluation>{json.dumps(failed_evals, indent=2)}</evaluation>")
    ]

    response = extract_tag_content('prompt', llm_complete(messages, model=LLM.GPT_4_O_LATEST))
    return False, response

def choose_best_image(context: Context, metadata: ImagesMetadata, best_img_index: int) -> ImagesMetadata:
    s3_file_path = context.base_path + f"/images/{metadata.id}.png"
    best_img_path = metadata.image[best_img_index].src

    metadata.human_choice = best_img_index

    copy_s3_object(best_img_path, s3_file_path)
    return metadata


def regenerate_image(context: Context, clip_idx: int, images_metadata: ImagesMetadata) -> ImagesMetadata:
    image_src = f'/tmp/{images_metadata.id}.png'
    s3_images_folder = context.media_path + f"images/{images_metadata.id}/"
    clips = load_json_from_s3(context.clips_path)

    images_metadata.image = []
    images_metadata.n_regenerations += 1

    image_urls, image_citations, custom_output = generate_image(
        context.grade,
        context.subject,
        '',
        images_metadata.prompt,
        images_metadata.type,
        image_src
    )
    images_metadata.image = [ImageDetails(**img) for img in custom_output] if custom_output else[ImageDetails(src=url)
                                                                                                 for url in image_urls] if image_urls else[ImageDetails(src=image_src)]
    for ii, image in enumerate(images_metadata.image):
        try:
            if image.src.startswith('http'):
                save_image(image.src, image_src)

            s3_file_path = s3_images_folder + f'{os.path.basename(image_src)}'
            upload_file_to_s3(image_src, s3_file_path)
            images_metadata.image[ii].src = s3_file_path
            image_src = f'/tmp/{images_metadata.id}-v{ii}.png'
        except Exception as e:
            logger.error(f"{e}. Couldn't save image {image.src}")
            continue

    clips['clips'][clip_idx]['media']['img_prompt'] = images_metadata.prompt

    save_json_to_s3(clips, context.clips_path)
    save_json_to_s3(images_metadata.dict(), s3_images_folder + f"{images_metadata.id}.json")

    return images_metadata


def set_best_image_qc_choice(context: Context, img_metadata: ImagesMetadata) -> ImagesMetadata:
    if img_metadata.human_choice is not None and img_metadata.qc_choice is None:
        img_metadata.qc_choice = img_metadata.human_choice 

    elif img_metadata.qc_choice is None and len(img_metadata.image) == 1:
        img_metadata.qc_choice = 0

    elif img_metadata.qc_choice is None and (img_metadata.type == GeneratedImageTypes.WEB or img_metadata.type in [GeneratedImageTypes.FLUX, GeneratedImageTypes.GPT] ):
        image_urls = [
            image.src if 'http' in image.src else create_presigned_url(image.src)
            for image in img_metadata.image
        ]
        best_image_index, confidence, evaluations = image_quality_check(
            context.grade, context.subject, img_metadata.type, img_metadata.prompt, image_urls)
        img_metadata.evaluation = evaluations
        img_metadata.qc_choice = best_image_index if best_image_index is not None else 0
    else:
        img_metadata.qc_choice = 0 if img_metadata.qc_choice is None else img_metadata.qc_choice

    save_json_to_s3(img_metadata.dict(), context.media_path + f'images/{img_metadata.id}/{img_metadata.id}.json')
    return img_metadata


def generate_image_wrapper(context: Context, clip: Clip, image_src: str, type: Optional[GeneratedImageTypes] = None) -> Tuple:
    img_class = (GeneratedImageTypes.WEB if clip.media.type == 'IMAGE' else GeneratedImageTypes.FLUX) if type is None else type
    prompt = clip.media.img_prompt


    url = ''
    if img_class == GeneratedImageTypes.WEB:
        logger.info(f"Detected a map image: {prompt[:30]}")
        url = find_lesson_map_from_db(context.subject, context.chapter, context.subsection).get("img_url", "")
        if not url:
            logger.info(f"Didn't find a suitable map in Maps Dataset, defaulting to google search.")
            urls, image_citations, _ = generate_image(context.grade, context.subject, '', clip.media.description, GeneratedImageTypes.WEB, image_src)

            conditions = """
Further conditions, which should be captured as part of the enhanced description.
- Must not include any legends or keys, unless they are directly relevant to the intended purpose of the map.
- Should preferably be a high-definition landscape image.
- Should ideally be a simple, minimalistic map that captures the intended purpose without any unnecessary details.
"""
            best_image_index, confidence, evaluations = image_quality_check(context.grade, context.subject, GeneratedImageTypes.WEB, prompt + conditions, urls)

            if confidence>3 and best_image_index and image_citations:
                url = urls[best_image_index]
    
    image_urls, image_citations, custom_output = [], None, None
    max_retries = 3 
    retry_count = 0
    
    if not url or img_class == GeneratedImageTypes.FLUX:
        logger.debug(f"Generating image with class {img_class}: {prompt}")
        img_class = GeneratedImageTypes.FLUX
        unit = get_unit_from_chapter(context.subject, context.chapter)
        while retry_count < max_retries:
            # Generate the image
            image_urls, image_citations, custom_output = generate_image(
                context.grade,
                context.subject,
                '',
                prompt,
                img_class,
                image_src
            )
            save_image(image_urls[0], image_src)
            if img_class == GeneratedImageTypes.FLUX:
                # Perform QC on the generated image
                status, new_prompt = subject_specific_image_qc(context, image_src, prompt, clip.text, location=clip.location)
                if status:
                    logger.debug(f"QC passed for image: {image_urls[0]}")
                    break
                else:
                    prompt = new_prompt  # Update the prompt with the new prompt from QC
                    logger.debug(f"QC failed for image: {image_urls[0]}. Updating prompt to: '{prompt}' and regenerating image")
                    retry_count += 1
            else:
                break
        else:
            logger.debug("Maximum retries reached without passing QC. Proceeding with the last generated image.")
    
    if url:
        image_urls.append(url)
    
    return img_class, image_urls, image_citations, custom_output


@exception_handler
def process_generate_image(context: Context, clip: Clip, status: str='') -> ImagesMetadata:
    image_hash = clip.media.id
    image_src = f'/tmp/{image_hash}.png'
    s3_images_folder = context.media_path + f'images/{image_hash}/'

    logger.info(f"{status} Generating Image {image_hash}. Will save in {s3_images_folder}")

    image_class, image_urls, image_citations, custom_output = generate_image_wrapper(
        context,
        clip,
        image_src
    )

    img_metadata = ImagesMetadata(
        id=clip.media.id, prompt=clip.media.img_prompt, image=[ImageDetails(**img) for img in custom_output]
        if custom_output else[ImageDetails(src=url) for url in image_urls]
        if image_urls else[ImageDetails(src=image_src)], type=image_class)

    for ii, image in enumerate(img_metadata.image):
        try:
            if image.src.startswith('http'):
                save_image(image.src, image_src)

            s3_file_path = s3_images_folder + f'{os.path.basename(image_src)}'
            upload_file_to_s3(image_src, s3_file_path)
            img_metadata.image[ii].src = s3_file_path
            image_src = f'/tmp/{image_hash}-v{ii}.png'
        except Exception as e:
            logger.error(f"{e}. Couldn't save image {image.src}")
            continue

    save_json_to_s3(img_metadata.dict(), s3_images_folder + f'{image_hash}.json')
    return img_metadata


def collect_ungenerated_images(context: Context, clips: List[Clip]) -> Tuple[List[ImagesMetadata], List[Clip]]:
    generated_images = []
    not_generated_clips = []

    def process_clip(clip: Clip):
        s3_images_folder = context.media_path + f'images/{clip.media.id}/'
        file_path = s3_images_folder + f'{clip.media.id}.json'
        if does_file_exist(file_path):
            image_metadata = ImagesMetadata(**load_json_from_s3(file_path))
            return ('generated', image_metadata)
        else:
            return ('not_generated', clip)

    with ContextAwareThreadPoolExecutor(max_workers=20) as executor:
        results = executor.map(process_clip, clips)

    for status, data in results:
        if status == 'generated':
            generated_images.append(data)
        else:
            not_generated_clips.append(data)

    return generated_images, not_generated_clips


@with_logging_context(layer=LayerName.IMAGES)
@exception_handler
def generate_all_images(output_path: str, output_type: str, inputs: dict, force: bool = False, qc: bool = True) -> None:
    context = Context(**inputs)
    logger.info(f"Running Image Generation for Topic: {context.key}")

    clips = [Clip(**clip) for clip in load_json_from_s3(context.clips_path)['clips']]

    update_images() # Update image mappings in S3

    start = time.time()
    if not force:
        generated_images, not_generated_clips = collect_ungenerated_images(context, clips)
    else:
        generated_images, not_generated_clips = [], clips
    logger.info(f"Identified {len(not_generated_clips)} images to generate in {time.time() - start}s")
    
    futures = []
    with ContextAwareThreadPoolExecutor(max_workers=12) as exec: # Limits Uknown
        for i, not_generated_clip in enumerate(not_generated_clips, 1):
            futures.append(exec.submit(process_generate_image, context, not_generated_clip, status=f"[{i}/{len(not_generated_clips)}]"))

    for i, future in enumerate(as_completed(futures), 1):
        generated_images.append(future.result())

    if qc:
        with ContextAwareThreadPoolExecutor(max_workers=5) as exec:
            for img_metadata in generated_images:
                futures.append(exec.submit(set_best_image_qc_choice, context, img_metadata))

        result = []
        for i, future in enumerate(as_completed(futures), 1):
            result.append(future.result())

    logger.info(f"Total time for Image Generation: {time.time() - start}s")
    return {'images': [metadata.dict() for metadata in result]}


if __name__ == '__main__':
    from core.context import prep_content_gen_input
    from config.courses import get_execution_input
    from core.clients.images import generate_flux_image
    setup_logging(level=logging.DEBUG)
    exec_input    = get_execution_input(
        subject = "AP World History - vUnit_1", 
        subsection = "Explain the effects of agriculture on social organization in Europe from c. 1200 to c. 1450."
    )
    context = Context(**prep_content_gen_input(exec_input))
    # generate_all_images('', '', context.model_dump())

    # gemini_media_analysis("Describe this image", "./regen-img-ec5cdf8b.png")
    print(generate_flux_image("Hello World"))