import logging
import json
import os
import uuid
import concurrent.futures
from tenacity import retry, wait_exponential, stop_after_attempt
from typing import List, Dict, Tuple, Union
from pydantic import BaseModel, Field
from openai import OpenAI, BadRequestError
from core.clients.images import GeneratedImageTypes, save_image
from core.log import setup_logging
from core.clients.openai import chat_complete, openai_gpt4v_message, add_to_messages, call_openai_vision, system_message, user_message, llm_complete, LLM, ensure_json
from core.helpers import image_to_data_uri
from core.logger import Logger
from core.clients.s3 import create_presigned_url, upload_file_to_s3, delete_file_from_s3
from prompts.images.qc import get_subject_agnostic_prompt, IMAGES_QC_SYSTEM_PROMPT2, IMAGES_QC_ENHANCE_DESRIPTION, case_specifications, UPDATE_DESCRIPTION_PROMPTS, ABSOLUTE_IMAGE_EVAL_PROMPT, ABSOLUTE_IMAGE_ENHANCER_PROMPT

from core.parsers import str_2_json

# logger = Logger("ImageQC", logging.DEBUG)
logger = logging.getLogger(__name__)


class ImageDescription(BaseModel):
    must: Union[List[str], str]
    should: List[str]
    must_not: List[str]


class ImageEvaluationBody(BaseModel):
    best_image: str = Field(..., alias="Best Image")
    justification: str = Field(..., alias="Justification")
    confidence: int = Field(..., alias="Confidence")
    images: List[str] = Field(..., alias="Images")


def absolute_image_qc(image_path: str, conditions: Dict[str, List[str]]):
    """Judge one generated image against its conditions.

    Runs on OpenAI vision rather than Gemini, for the same reason the Claude calls moved:
    one provider, one key. Gemini was also the only thing here needing GEMINI_API_KEY, which
    has never been valid in this .env, so every image QC failed at the last step after the
    FLUX spend had already happened.

    A local file becomes a data URI. The alternative is what the commented-out code below
    used to do -- upload to S3 and presign it -- which local mode has no bucket for.
    """
    url = image_path if image_path.startswith('http') else image_to_data_uri(image_path)
    response = call_openai_vision([
        {"role": "system", "content": ABSOLUTE_IMAGE_EVAL_PROMPT},
        {"role": "user", "content": f"Evaluate this Image. Make sure to dedicate a sentence per: Analysis, Assessment, and Justification for every condition. Evaluation should necessarily include 3 sentences per condition. Be verbose but specific. Conditions to meet: \n```\n{json.dumps(conditions, indent=2)}\n```"},
        openai_gpt4v_message(url, 0),
    ])

    return ensure_json(response)


def image_quality_check(
        grade: str,
        subject: str,
        _type: GeneratedImageTypes,
        description: Union[str, dict],
        image_links: List[str]) -> str:
    logger.info(f"Starting quality check on image: {description}\n{image_links}")

    conditions = description if isinstance(
        description, dict) else enhance_description(grade, subject,
                                                    description, _type)

    logger.info(f"Generated image conditions:\n{conditions}")
    evaluations, best_image_index = divide_and_conquer(grade, subject,
                                                       conditions, image_links, _type)
    logger.info(f"Evaluation Results of {description}: {json.dumps(evaluations, indent=2)}")
    confidence = evaluations['Final']['confidence']

    return best_image_index, confidence, evaluations


def enhance_description(grade: str, subject: str, description: str, _type: GeneratedImageTypes, eval_type='relative'):
    prompt = IMAGES_QC_ENHANCE_DESRIPTION
    if eval_type!='relative':
        prompt = ABSOLUTE_IMAGE_ENHANCER_PROMPT
    messages = [
        {"role": "system",
         "content": get_subject_agnostic_prompt(prompt, {'grade': grade, 'subject': subject})},
        *case_specifications[_type.value]['examples'],
        {"role": "user", "content": description}, ]
    response = chat_complete(messages, model="gpt-4-0613")
    return ImageDescription(**str_2_json(response))


def divide_and_conquer(
        grade: str, 
        subject: str,
        conditions: ImageDescription,
        image_links: List[str],
        _type: GeneratedImageTypes):
    n_links = len(image_links)
    evaluations = {}
    best_images = {}

    if n_links > 4:
        divisions = [image_links[ii:ii + 4]
                     for ii in range(0, len(image_links), 4)]
        for ii, division in enumerate(divisions):
            evaluation, best_image = evaluate_images(grade, subject, conditions, division, _type)
            evaluations[f"Division {ii}"] = evaluation.dict()
            if evaluation.confidence > 2:
                best_images[f"Division {ii}"] = division[best_image]
            else:
                logger.info(f"Ommiting Division {ii} image set as none is a good fit.")

        if len(best_images) == 0:
            evaluations["Final"] = {
                "best_image": "None",
                "justification": "No fit image found in any division",
                "confidence": 0}
            _index = -1

        elif len(best_images) == 1:
            logger.info(f"SINGLE BEST IMAGE IN DIVISION: {best_images}")
            only_division = list(best_images.keys())[0]
            _index = image_links.index(list(best_images.values())[0])
            evaluations["Final"] = evaluations[only_division]

        else:
            logger.info(f"MULTIPLE BEST IMAGES IN DIVISION: {best_images}")
            final_eval, best = evaluate_images(
                grade, subject, conditions, list(best_images.values()), _type)
            _index = image_links.index(list(best_images.values())[best])
            evaluations["Final"] = final_eval.dict()
    else:
        logger.info(f"NO DIVISIONS, FINAL EVAL: {best_images}")
        final_eval, _index = evaluate_images(grade, subject, conditions, image_links, _type)
        evaluations["Final"] = final_eval.dict()

    return evaluations, _index


def check_url(url, ii):
    try:
        response = call_openai_vision(
            [{"role": "system", "content": "Is image visible? Return yes or no"}, openai_gpt4v_message(url, ii)])
        return url, True
    except BadRequestError as e:
        logger.error(f"Found invalid image: {url}")
        return url, False


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=30))
def evaluate_with_retry(system_message: Dict[str, str], image_urls: List[str]):
    try:
        response = call_openai_vision(
            [system_message, *[openai_gpt4v_message(url, ii) for ii, url in enumerate(image_urls)]])
    except BadRequestError as e:
        logger.error(f"Found at least one invalid image: {e}")
        valid = {url: False for url in image_urls}
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(
                    check_url,
                    url,
                    ii): url for ii,
                url in enumerate(image_urls)}
            for future in concurrent.futures.as_completed(futures):
                url, result = future.result()
                valid[url] = result
        logger.info(f"Valid Images: {valid}")
        user_messages = []
        for url, is_valid in valid.items():
            if is_valid:
                user_messages.append(
                    openai_gpt4v_message(
                        url, image_urls.index(url)))

        if len(user_messages):
            response = call_openai_vision([system_message, *user_messages])
        else:
            return json.dumps(
                {"Best Image": "None", "Justification": "Only good image", "Confidence": 1})
    except Exception as e:
        raise e
    return response


def evaluate_images(
        grade: str,
        subject: str,
        conditions: ImageDescription,
        image_urls: List[str],
        _type: GeneratedImageTypes):
    if len(image_urls) == 1:
        return ImageEvaluationBody(
            **{"Best Image": "Image 0", "Justification": "Only Image", "Confidence": 2, "Images": image_urls}), 0

    system_message = {"role": "system", "content": get_subject_agnostic_prompt(IMAGES_QC_SYSTEM_PROMPT2, 
        {'grade': grade, 'subject': subject, 'case_specifics': case_specifications[_type.value]['main_prompt'], 'conditions':conditions.dict()})}

    response = evaluate_with_retry(system_message, image_urls)

    try:
        image_eval = ImageEvaluationBody(Images = image_urls, **str_2_json(response))
    except Exception as error:
        logger.error(f"Unacceptected response: {error}. Response body: {response}")
        raise error

    _index = image_eval.best_image[-1]
    # index of best image in image_urls
    best_image_index = int(_index) if _index.isdigit() else -1
    
    return image_eval, best_image_index


def correct_image_description(
        description: str,
        evaluation: dict,
        _type: GeneratedImageTypes):
    logger.info(f"Type {case_specifications[_type.value]}. {_type.value}")
    messages = [
        {"role": "system", "content": UPDATE_DESCRIPTION_PROMPTS[0].format(case_specific_practices=case_specifications[_type.value]['update_description_prompt'])},
        {"role": "user", "content": UPDATE_DESCRIPTION_PROMPTS[1].format(evaluation=evaluation, description=description)}
    ]
    analysis = chat_complete(messages, model="gpt-4-1106-preview")

    messages = add_to_messages(
        messages,
        analysis,
        UPDATE_DESCRIPTION_PROMPTS[2].format(description = case_specifications[_type.value]['final_query_prompt']))
    logger.info(json.dumps(messages, indent = 2))
    new_query = chat_complete(messages, model="gpt-4-1106-preview")
    logger.info(new_query)
    return str_2_json(new_query)['query']

if __name__ == "__main__":

    setup_logging(level=logging.DEBUG)

    def test_eval_results(evals,
            best_image_index,
            true_description,
            original_description):
        correct_eval = best_image_index == '0'
        return {"original_description": original_description,
                "description": true_description[best_image_index],
                "Correct": correct_eval, **evals}

    events = json.load(open('./event.json'))["GOOGLE"]

    result = []
    for event in events:
        best_image_index, confidence, evaluations = image_quality_check(
            GeneratedImageTypes.WEB, event['description'], event['image_links'])
        logger.info(best_image_index, confidence, evaluations)
        break
        # result.extend([test_eval_results(e,
        #                                  best_image_index,
        #                                  event['true_descriptions'],
        #                                  event["description"]["must"]) for e in evaluations])
    logger.info(json.dumps(result, indent=2))