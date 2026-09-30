import json
import time
import os
import logging
from core.clients.openai import system_message, user_message, llm_complete
from typing import List, Optional, Tuple
from concurrent.futures import as_completed

from core.clients.openai import LLM
from core.clients.s3 import upload_file_to_s3, create_presigned_url, save_json_to_s3, load_json_from_s3, does_file_exist
from core.context import Context
from core.helpers import exception_handler, extract_tag_content, identify_location
from prompts.clips_prompts import AUDIENCE, IMAGE_PROMPT_REWRITE_FROM_QC, IMAGE_PROMPT_REWRITE_FROM_QC_USER, WEB_MAP_CONDITIONS
from core.clients.images import generate_image, GeneratedImageTypes, save_image
from core.clients.image_qc import image_quality_check, absolute_image_qc
from core.types import Clip, ImageDetails, ImagesMetadata, LayerName
from config.subject_profiles import resolve_profile
from tenacity import retry, stop_after_attempt, wait_exponential
from core.log import with_logging_context, ContextAwareThreadPoolExecutor

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=7, max=90))
def subject_specific_image_qc(context: Context, image_path: str, prompt: str, snippet: str, location:Optional[str]=None) -> Tuple[bool, str]:
    
    if location is None:
        location = identify_location(context, snippet)

    qc_conditions = resolve_profile(context.subject).images.conditions(
        period=context.chapter, location=location,
        subject=context.subject, title=context.title)

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
        user_message(IMAGE_PROMPT_REWRITE_FROM_QC_USER.format(prompt=prompt, evaluation=json.dumps(failed_evals, indent=2)))
    ]

    response = extract_tag_content('prompt', llm_complete(messages, model=LLM.GPT_5))
    return False, response


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
            AUDIENCE, context.subject, img_metadata.type, img_metadata.prompt, image_urls)
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
        logger.info(f"Detected a map image, searching the web: {prompt[:30]}")
        urls, image_citations, _ = generate_image(AUDIENCE, context.subject, clip.media.description, GeneratedImageTypes.WEB, image_src)
        best_image_index, confidence, evaluations = image_quality_check(AUDIENCE, context.subject, GeneratedImageTypes.WEB, prompt + WEB_MAP_CONDITIONS, urls)
        if confidence>3 and best_image_index and image_citations:
            url = urls[best_image_index]
    
    image_urls, image_citations, custom_output = [], None, None
    max_retries = 3 
    retry_count = 0
    
    if not url or img_class == GeneratedImageTypes.FLUX:
        logger.debug(f"Generating image with class {img_class}: {prompt}")
        img_class = GeneratedImageTypes.FLUX
        while retry_count < max_retries:
            # Generate the image
            image_urls, image_citations, custom_output = generate_image(
                AUDIENCE,
                context.subject,
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
def process_generate_image(context: Context, clip: Clip, status: str = '',
                           web_images: bool = True) -> ImagesMetadata:
    image_hash = clip.media.id
    image_src = f'/tmp/{image_hash}.png'
    s3_images_folder = context.media_path + f'images/{image_hash}/'

    logger.info(f"{status} Generating Image {image_hash}. Will save in {s3_images_folder}")

    image_class, image_urls, image_citations, custom_output = generate_image_wrapper(
        context,
        clip,
        image_src,
        type=None if web_images else GeneratedImageTypes.FLUX,
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

    start = time.time()
    if not force:
        generated_images, not_generated_clips = collect_ungenerated_images(context, clips)
    else:
        generated_images, not_generated_clips = [], clips
    logger.info(f"Identified {len(not_generated_clips)} images to generate in {time.time() - start}s")
    
    web_images = bool(inputs.get("LAYER_WEB_IMAGES", True))
    futures = []
    with ContextAwareThreadPoolExecutor(max_workers=12) as exec: # Limits Uknown
        for i, not_generated_clip in enumerate(not_generated_clips, 1):
            futures.append(exec.submit(process_generate_image, context, not_generated_clip,
                                       status=f"[{i}/{len(not_generated_clips)}]",
                                       web_images=web_images))

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
