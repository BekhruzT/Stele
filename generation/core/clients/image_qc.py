import logging
import json
import concurrent.futures
from tenacity import retry, wait_exponential, stop_after_attempt
from typing import List, Dict, Union
from pydantic import BaseModel, Field
from openai import BadRequestError
from core.clients.images import GeneratedImageTypes
from core.clients.openai import chat_complete, openai_gpt4v_message, call_openai_vision, LLM, ensure_json
from core.helpers import image_to_data_uri
from prompts.images.qc import get_subject_agnostic_prompt, IMAGES_QC_SYSTEM_PROMPT2, IMAGES_QC_ENHANCE_DESRIPTION, case_specifications, ABSOLUTE_IMAGE_EVAL_PROMPT, ABSOLUTE_IMAGE_EVAL_USER_PROMPT, ABSOLUTE_IMAGE_ENHANCER_PROMPT, IMAGE_VISIBLE_PROMPT

from core.parsers import str_2_json

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
    """Judge one image against its conditions on the gateway's vision route; local files become data URIs."""
    url = image_path if image_path.startswith('http') else image_to_data_uri(image_path)
    response = call_openai_vision([
        {"role": "system", "content": ABSOLUTE_IMAGE_EVAL_PROMPT},
        {"role": "user", "content": ABSOLUTE_IMAGE_EVAL_USER_PROMPT.format(conditions=json.dumps(conditions, indent=2))},
        openai_gpt4v_message(url, 0),
    ])

    return ensure_json(response)


def image_quality_check(
        audience: str,
        subject: str,
        _type: GeneratedImageTypes,
        description: Union[str, dict],
        image_links: List[str]) -> str:
    logger.info(f"Starting quality check on image: {description}\n{image_links}")

    conditions = description if isinstance(
        description, dict) else enhance_description(audience, subject,
                                                    description, _type)

    logger.info(f"Generated image conditions:\n{conditions}")
    evaluations, best_image_index = divide_and_conquer(audience, subject,
                                                       conditions, image_links, _type)
    logger.info(f"Evaluation Results of {description}: {json.dumps(evaluations, indent=2)}")
    confidence = evaluations['Final']['confidence']

    return best_image_index, confidence, evaluations


def enhance_description(audience: str, subject: str, description: str, _type: GeneratedImageTypes, eval_type='relative'):
    prompt = IMAGES_QC_ENHANCE_DESRIPTION
    if eval_type!='relative':
        prompt = ABSOLUTE_IMAGE_ENHANCER_PROMPT
    messages = [
        {"role": "system",
         "content": get_subject_agnostic_prompt(prompt, {'audience': audience, 'subject': subject})},
        *case_specifications[_type.value]['examples'],
        {"role": "user", "content": description}, ]
    response = chat_complete(messages, model=LLM.GPT_5)
    return ImageDescription(**str_2_json(response))


def divide_and_conquer(
        audience: str, 
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
            evaluation, best_image = evaluate_images(audience, subject, conditions, division, _type)
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
                audience, subject, conditions, list(best_images.values()), _type)
            _index = image_links.index(list(best_images.values())[best])
            evaluations["Final"] = final_eval.dict()
    else:
        logger.info(f"NO DIVISIONS, FINAL EVAL: {best_images}")
        final_eval, _index = evaluate_images(audience, subject, conditions, image_links, _type)
        evaluations["Final"] = final_eval.dict()

    return evaluations, _index


def check_url(url, ii):
    try:
        call_openai_vision([{"role": "system", "content": IMAGE_VISIBLE_PROMPT}, openai_gpt4v_message(url, ii)])
        return url, True
    except BadRequestError:
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
        audience: str,
        subject: str,
        conditions: ImageDescription,
        image_urls: List[str],
        _type: GeneratedImageTypes):
    if len(image_urls) == 1:
        return ImageEvaluationBody(
            **{"Best Image": "Image 0", "Justification": "Only Image", "Confidence": 2, "Images": image_urls}), 0

    system_message = {"role": "system", "content": get_subject_agnostic_prompt(IMAGES_QC_SYSTEM_PROMPT2, 
        {'audience': audience, 'subject': subject, 'case_specifics': case_specifications[_type.value]['main_prompt'], 'conditions':conditions.dict()})}

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


