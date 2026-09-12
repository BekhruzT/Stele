import io
import json
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import MutableMapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any, Dict, List, Tuple, Optional

import boto3
import cairosvg
import fal_client
import requests
from bs4 import BeautifulSoup
from core.log import (
    ContextAwareThreadPoolExecutor, setup_logging)
from core.stage_constants import \
    get_sheet_info_by_subject
from core.parsers import str_2_json
from googleapiclient.discovery import build
from core.clients.openai import generate_openai_image
from prompts.images.qc import MULTIQUERY_PROMPT
from prompts.images.system_prompts import (AI_PROMPT_TO_GOOGLE_QUERY_PROMPT,
                                    CLASSIFY_IMAGE_DESCRIPTION_SYSTEM_PROMPT,
                                    FETCH_DESCRIPTION_TUNE_SYSTEM_PROMPT,
                                    GENERATE_MERMAID_CODE_SYSTEM_PROMPT,
                                    GENERATE_PLOTLY_DIAGRAM_PROMPT,
                                    GENERATE_SVG_CODE_SYSTEM_PROMPT,
                                    IMAGE_DESCRIPTION_TUNE_SYSTEM_PROMPT,
                                    REMOVE_NSFW_CONCEPTS_SYSTEM_PROMPT,
                                    get_subject_agnostic_prompt)
from prompts.images.user_prompts import (CLASSIFY_IMAGE_DESCRIPTION_TUNE_USER_PROMPT,
                                  CODE_PLOTLY_DIAGRAM_PROMPT,
                                  FETCH_DESCRIPTION_TUNE_USER_PROMPT,
                                  GENERATE_MERMAID_CODE_USER_PROMPT,
                                  GENERATE_SVG_CODE_USER_PROMPT,
                                  IMAGE_DESCRIPTION_TUNE_USER_PROMPT,
                                  PLAN_PLOTLY_DIAGRAM_PROMPT,
                                  REMOVE_NSFW_CONCEPTS_USER_PROMPT)
from tenacity import retry, stop_after_attempt, wait_exponential
from core.constants import (AWS_REGION, GCP_API_KEY, GCP_SEARCH_CXID,
                             MERMAID_LAMBDA_NAME, MIDJOURNEY_LAMBDA_URL,
                             TIKTOK_AWS_ACCESS_KEY_ID,
                             TIKTOK_AWS_SECRET_ACCESS_KEY)
from core.logger import Logger
from core.clients.openai import (LLM, add_to_messages, chat_complete,
                          generate_image_dalle, llm_complete, system_message,
                          user_message)

# logger = Logger(__name__, logging.DEBUG)
logger = logging.getLogger(__name__)


class GeneratedImageTypes(Enum):
    WEB = "web"
    SVG = "svg"
    MERMAID = "mermaid"
    PLOTLY = "plotly"
    MANIM_PYPLOT = "Manim.py Plot"
    UPLOAD = "upload image"
    URL = "from url"
    MIDJOURNEY = "MIDJOURNEY"
    GPT = "GPT"
    DALLE = "DALLE"
    FLUX = "FLUX"


def generate_image(grade: str, subject: str, standard_id: str, image_description: str, image_class: GeneratedImageTypes,
                   image_path: str, cost_callback=None) -> Tuple[List[str],
                                                                 List[str], Any]:
    image_urls = None
    image_citations = None
    custom_output = {}
    if image_class == GeneratedImageTypes.SVG:
        generate_svg_image(image_description, grade, standard_id, image_path, cost_callback)
    elif image_class == GeneratedImageTypes.MERMAID:
        generate_mermaid_image(image_description, grade, standard_id, image_path, cost_callback)
    elif image_class == GeneratedImageTypes.WEB:
        image_urls, image_citations = generate_web_image(image_description)

        if not image_urls:
            logger.info(f"COULDN'T FIND WEB IMAGES FOR: {image_description}")
            image_urls, custom_output = generate_ai_image(
                image_description, grade, subject, standard_id, cost_callback)

    elif image_class == GeneratedImageTypes.PLOTLY:
        custom_output = generate_diagram(image_description, grade, subject, image_path)
    else:
        image_urls, custom_output = generate_ai_image(
            image_description, grade, subject, standard_id, cost_callback, image_class=image_class)
    return image_urls, image_citations, custom_output


def generate_svg_image(image_description, grade, standard_id, image_path, cost_callback=None):
    logger.info(f"Generating svg code for image: {image_description}")
    svg_code = generate_svg_code(image_description, grade, standard_id, cost_callback)
    logger.info(f"Generated svg code for image: {image_description}. SVG code: {svg_code}")
    svg_to_png(svg_code, image_path)


def generate_mermaid_image(image_description, grade, standard_id, image_path, cost_callback=None):
    mermaid_code = generate_mermaid_code(image_description, grade, standard_id, cost_callback)
    uri = generate_daigram(mermaid_code)
    logger.info(f"Generated diagram from mermaid code: {mermaid_code}. Diagram URI: {uri}")
    save_image(uri, image_path)


def generate_web_image(image_description, count=8):
    image_urls = []
    image_citations = []

    query = ai_prompt_to_google_query(image_description)
    logger.info(f"Searching for images with query: {query}. Original prompt: {image_description[:30]}")
    for domain in ['.edu', '.org', '.gov', '.ac']:
        n_results = max(5, count - len(image_urls))
        query_results = query_google(query, domain, n_results)

        if int(query_results['searchInformation']['totalResults']) == 0:
            logger.info(f"FOUND 0 IMAGES in domain {domain} for {query}")
            continue
        for item in query_results["items"]:
            try:
                image_uri = item['link']
                image_type = image_uri.split(".")[-1]
                logger.info(f"Attempting to download map image: {query} from {image_uri}")

                if image_uri.split('.')[-1] in ['webp', 'png', 'jpg', 'jpeg']:
                    image_urls.append(image_uri)
                    image_citations.append(
                        f"<a href=\"{image_uri}\">{item['title']}</a>, used under CC-BY-SA | CC-BY-ND")
            except Exception as error:
                logger.error(f"Failed to download image from: {image_uri}. Error: {error}")

        if len(image_urls) > count*1.1:
            break

    return image_urls, image_citations


@retry(stop=stop_after_attempt(1), wait=wait_exponential(multiplier=1, max=15))
def query_google(image_description, domain='.edu', n_results=5):
    service = build("customsearch", "v1", developerKey=GCP_API_KEY)
    res = service.cse().list(
        q=image_description,
        cx=GCP_SEARCH_CXID,
        num=n_results,
        searchType='image',
        fileType='jpg|png|webp',
        safe='medium',
        rights='cc_publicdomain|cc_attribute|cc_sharealike|cc_nonderived|cc_zero|cc_by|cc_by-nd|cc_by-sa',
        # imgSize='MEDIUM|LARGE',
        siteSearch=domain
    ).execute()

    return res


def generate_ai_image(
        image_description, grade, subject, standard_id, cost_callback, image_class: GeneratedImageTypes=GeneratedImageTypes.FLUX) -> Tuple[
        List[str],
        List[Dict[str, str]]]:
    # multiquery = multiquery_image_description( image_description, grade, subject, 2, standard_id, cost_callback) 
    multiquery = [image_description]

    # logger.info(f"Generate Multiquery: {'; '.join(multiquery)}")

    image_details = []

    models = [image_class]  #["MIDJOURNEY", "DALLE", "FLUX"]

    def get_image_for_query_and_model(query: str, model: GeneratedImageTypes)-> Dict[str, str]:
        if model == GeneratedImageTypes.MIDJOURNEY:
            src = generate_image_util(query)
        elif model == GeneratedImageTypes.DALLE:
            src = generate_image_dalle(query)
        elif model == GeneratedImageTypes.GPT:
            src = generate_openai_image(query)
        elif model == GeneratedImageTypes.FLUX:
            print("Generating Flux Image")
            src = generate_flux_image(query)
            if src == "NSFW":
                logger.warning(f"NSFW content detected in query and couldn't be fixed: {query}\nTrying DALLE...")
                src = generate_image_dalle(query)
        else:
            raise ValueError(f"Unknown model: {model}")
        return {
            "prompt": query,
            "src": src,
            "model": model
        }

    tasks = [(query, model) for query in multiquery for model in models]
    with ContextAwareThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(get_image_for_query_and_model, query, model) for query, model in tasks]
        for future in as_completed(futures):
            try:
                image_details.append(future.result())
            except Exception as exc:
                logger.error(f'Generated an exception: {exc}')

    return [img['src'] for img in image_details], image_details

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=4, max=90))
def generate_flux_image(query: str, nsfw_retry: int = 0, width: int = 1280, height: int = 720)->str:
    handler = fal_client.submit(
        "fal-ai/flux-pro/v1.1",
        arguments={
            "prompt": query,
            "image_size": {
                "width": width,
                "height": height
            }
        },
    )
    result = handler.get()
    
    if result.get('has_nsfw_concepts') and result['has_nsfw_concepts'][0]:
        from core.helpers import \
            llm_call

        if nsfw_retry > 6:
            logger.warning(f"NSFW content detected after maximum retries for query: {query}")
            return "NSFW"
        elif nsfw_retry > 2:
            logger.info(f"NSFW content detected, attempting to modify query (retry {nsfw_retry})")
            _, new_query = llm_call(
                system_prompt=REMOVE_NSFW_CONCEPTS_SYSTEM_PROMPT,
                user_prompt=REMOVE_NSFW_CONCEPTS_USER_PROMPT.format(prompt=query),
                model=LLM.CLAUDE_3_7_SONNET_THINKING,
                tag="new_prompt",
                temperature=1
            )
            return generate_flux_image(new_query, nsfw_retry + 1)
        else:
            logger.info(f"NSFW content detected, retrying with same query (retry {nsfw_retry})")
            return generate_flux_image(query, nsfw_retry + 1)
            
    return result['images'][0]['url']

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=4, max=90))
def generate_flux_image_portrait(query: str, nsfw_retry: int = 0) -> str:
    nsfw_text = f"(NSFW retry {nsfw_retry}, {'same query' if nsfw_retry <= 3 else 'new query'}) " if nsfw_retry > 0 else ""
    logger.info(f"{nsfw_text}Generating flux image portrait for query: {query}")
    handler = fal_client.submit(
        "fal-ai/flux-pro",
        arguments={
            "prompt": query,
            "image_size": {"width": 720, "height": 1280}
        },
    )
    result = handler.get()
    
    if result.get('has_nsfw_concepts') and result['has_nsfw_concepts'][0]:
        from core.helpers import \
            llm_call

        if nsfw_retry > 6:
            return "NSFW"
        elif nsfw_retry > 2:
            _, new_query = llm_call(
                system_prompt=REMOVE_NSFW_CONCEPTS_SYSTEM_PROMPT,
                user_prompt=REMOVE_NSFW_CONCEPTS_USER_PROMPT.format(prompt=query),
                model=LLM.CLAUDE_3_7_SONNET_THINKING,
                tag="new_prompt",
                temperature=1
            )
            return generate_flux_image_portrait(new_query, nsfw_retry + 1)
        else:
            return generate_flux_image_portrait(query, nsfw_retry + 1)
            
    return result['images'][0]['url']

    
def multiquery_image_description(description: str, grade, subject, n, standard_id, cost_callback) -> List[str]:
    tuned_image_description = tune_image_description(description, grade, subject, standard_id, cost_callback)

    if n>0:
        messages = [
            system_message(""),
            user_message(MULTIQUERY_PROMPT, n=2, query=tuned_image_description)
        ]
        response = chat_complete(messages, cost_callback=cost_callback)
        return [description, tuned_image_description, *[r for r in response.split("\n") if len(r.strip()) > 0]]
    return [description, tuned_image_description]


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=30))
def tune_image_description(image_description: str, grade: str, subject: str, standard_id: str, cost_callback=None):
    messages = [
        system_message(get_subject_agnostic_prompt(IMAGE_DESCRIPTION_TUNE_SYSTEM_PROMPT, {'subject': subject})),
        user_message(IMAGE_DESCRIPTION_TUNE_USER_PROMPT, grade=grade,
                     standard_id=standard_id, image_description=image_description)
    ]
    try:
        tuned_prompt_response = chat_complete(messages, cost_callback=cost_callback)
        logger.info(f'Tuned prompt: {tuned_prompt_response}')
        tuned_prompt = json.loads(tuned_prompt_response.strip('`').strip('json'))['tuned_prompt']
        return tuned_prompt
    except Exception as error:
        logger.error(f"Failed to tune image description: {image_description}. Error: {error}")
        raise


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=30))
def classify_image(image_description: str, grade: str, standard_id: str, cost_callback=None):
    messages = [
        system_message(CLASSIFY_IMAGE_DESCRIPTION_SYSTEM_PROMPT),
        user_message(CLASSIFY_IMAGE_DESCRIPTION_TUNE_USER_PROMPT, grade=grade,
                     standard_id=standard_id, image_description=image_description)
    ]
    try:
        image_class = chat_complete(messages, cost_callback=cost_callback)
        classified_image = str_2_json(image_class)
        image_type = classified_image.get("type")
        return GeneratedImageTypes[image_type.upper()]
    except Exception as error:
        logger.error(f"Failed to classify image: {image_description}. Error: {error}")
        raise


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=30))
def generate_mermaid_code(image_description: str, grade: str, standard_id: str, cost_callback=None):
    messages = [
        system_message(GENERATE_MERMAID_CODE_SYSTEM_PROMPT),
        user_message(GENERATE_MERMAID_CODE_USER_PROMPT, grade=grade,
                     standard_id=standard_id, image_description=image_description)
    ]
    try:
        mermaid_code_response = chat_complete(messages, cost_callback=cost_callback)
        start_index = mermaid_code_response.find('```mermaid') + len('```mermaid')
        end_index = mermaid_code_response.rfind('```')
        mermaid_code = mermaid_code_response[start_index:end_index].strip()
        return mermaid_code
    except Exception as error:
        logger.error(f"Failed to generate mermaid code for image: {image_description}. Error: {error}")
        raise


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=30))
def generate_svg_code(image_description: str, grade: str, standard_id: str, cost_callback=None):
    messages = [
        system_message(GENERATE_SVG_CODE_SYSTEM_PROMPT),
        user_message(GENERATE_SVG_CODE_USER_PROMPT, grade=grade,
                     standard_id=standard_id, image_description=image_description)
    ]
    try:
        svg_code_response = chat_complete(messages, cost_callback=cost_callback)
        start_index = svg_code_response.find('```svg') + len('```svg')
        end_index = svg_code_response.rfind('```')
        svg_code = svg_code_response[start_index:end_index].strip()
        return svg_code
    except Exception as error:
        logger.error(f"Failed to generate svg code for image: {image_description}. Error: {error}")
        raise


def get_browser_headers():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36'
    }
    return headers


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, max=5))
def save_image(image_url: str, image_path: str):
    try:
        # logger.info(f"Saving image from {image_url} to {image_path}")
        response = requests.get(image_url, timeout=30)
        # logger.info(f"Fetched image from {image_url} with status code: {response.status_code}")

        if response.status_code == 403:  # some website prohibits image scraping
            logger.info(
                f"Failed to download image from {image_url}. Status code: {response.status_code}. Retrying posing as a broswer...")
            headers = get_browser_headers()
            response = requests.get(image_url, headers=headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to download image from {image_url} with status code: {response.status_code}. Skipping for now. Please download this manually!")

        with open(image_path, 'wb') as handler:
            handler.write(response.content)

        # logger.info(f"Successfully downloaded image from {image_url} and saved at {image_path}")
    except Exception as error:
        logger.error(f"Failed to save image from {image_url} to {image_path}. Error: {error}")
        raise


def svg_to_png(svg_code: str, image_path: str):
    try:
        cairosvg.svg2png(bytestring=svg_code, write_to=image_path)
    except Exception as error:
        raise Exception(f"Failed to convert SVG to PNG: {error}")
    logger.info(f"Successfully saved SVG to PNG at {image_path}")


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=30))
def generate_daigram(mermaid_code: str):
    try:
        client = boto3.client(
            'lambda',
            aws_access_key_id=TIKTOK_AWS_ACCESS_KEY_ID,
            aws_secret_access_key=TIKTOK_AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )

        response = client.invoke(
            FunctionName=MERMAID_LAMBDA_NAME,
            InvocationType='RequestResponse',
            LogType='Tail',
            Payload=json.dumps({"text": mermaid_code, "sk": str(uuid.uuid4())}).encode("utf-8"),
        )

        payload_data = json.loads(response['Payload'].read().decode('utf-8'))
        image_uri = payload_data.get('img_url')

        return image_uri
    except Exception as error:
        logger.error(f"Failed to generate diagram from mermaid code: {mermaid_code}. Error: {error}")
        raise


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=30))
def generate_image_util(prompt: str):
    payload = json.dumps({
        "prompt": prompt
    })
    headers = {
        'Content-Type': 'application/json'
    }
    # logger.info(f"Generating image for prompt: {prompt}")
    response = requests.post(MIDJOURNEY_LAMBDA_URL, headers=headers, data=payload, timeout=240)
    if response.status_code != 200:
        raise Exception(
            f"Failed to generate image for {prompt}. Failed with status {response.status_code}, message: {response.text}")
    return json.loads(response.text)['uri']


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, max=30))
def tune_image_description_for_caption(alt: str, content: str, cost_callback=None):
    messages = [
        system_message(FETCH_DESCRIPTION_TUNE_SYSTEM_PROMPT),
        user_message(FETCH_DESCRIPTION_TUNE_USER_PROMPT, alt=alt, content=content)
    ]
    try:
        tuned_prompt_response = chat_complete(messages, cost_callback=cost_callback)
        start_index = tuned_prompt_response.find('```detailed') + len('```detailed')
        end_index = tuned_prompt_response.rfind('```')
        tuned_prompt = tuned_prompt_response[start_index:end_index].strip()
        return tuned_prompt
    except Exception as error:
        logger.error(f"Failed to tune image description for caption - {alt}. Error: {error}")
        raise


def generate_image_caption(image_description: str, context: str, cost_callback=None):
    logger.info(f"Generating image caption for image: {image_description}")
    image_caption = tune_image_description_for_caption(image_description, context, cost_callback)
    return image_caption


def code_interpreter(code: str) -> str:
    buffer = io.StringIO()
    sys.stdout = buffer
    exec(code)
    sys.stdout = sys.__stdout__
    output = buffer.getvalue()
    buffer.close()
    return output


def generate_diagram(image_description: str, grade: str, subject: str, image_path: str, retry_count: int = 0) -> str:
    messages = [
        system_message(GENERATE_PLOTLY_DIAGRAM_PROMPT, description=image_description),
        user_message(PLAN_PLOTLY_DIAGRAM_PROMPT, description=image_description)
    ]

    plan = chat_complete(messages, model='gpt-4-turbo')
    messages = add_to_messages(messages, plan, CODE_PLOTLY_DIAGRAM_PROMPT.format(description=image_description))

    code = chat_complete(messages, model='gpt-4-turbo')
    code = re.findall(r"```python(.*?)```", code, re.DOTALL)[0]

    code_interpreter(code + f'\nfig.write_image("{image_path}")' +
                     f'\nfig.write_image("./functions/images/utils/image.png")')

    if not os.path.exists(image_path):
        if retry_count >= 3:
            raise FileNotFoundError(f"Failed to create image at {image_path} after 3 retries.")
        return generate_diagram(image_description, grade, subject, image_path, retry_count + 1)
    return code


def ai_prompt_to_google_query(prompt: str) -> str:
    from core.helpers import \
        extract_tag_content
    messages = [
        system_message(AI_PROMPT_TO_GOOGLE_QUERY_PROMPT),
        user_message(prompt)
    ]

    query = extract_tag_content('query', llm_complete(messages, LLM.ANTHROPIC_CLAUDE_3_5_SONNET))

    return query

def find_lesson_map_from_db(subject: str, target_chapter: str, target_subsection: str) -> dict:
    from core.clients.gsheet import \
        GoogleSheetsClient
    sheet_info = get_sheet_info_by_subject(subject)['Maps']

    g_client = GoogleSheetsClient(sheet_info['sheet_id'])
    data = g_client.read_batch_from_sheet(sheet_info['sheet_name'], 1, 85, 6)
    chapter_dict, pattern = {}, re.compile(r'^=IMAGE\("(.*)"\)$')
    for _, chapter, subsection, desc, map_cell, is_good in data:
        match = pattern.match(map_cell)
        url = match.group(1) if match else map_cell
        chapter_dict.setdefault(chapter, {})[subsection] = {"description": desc, "img_url": url, "is_good": is_good}
    lesson_map_info = chapter_dict.get(target_chapter, {}).get(target_subsection, {})
    return lesson_map_info if lesson_map_info.get("is_good", False) else {}

def find_matching_image_from_db(prompt: str, target_chapter: str, target_subsection: str) -> dict:
    images = load_json_from_s3('custom/ap_history/mapped_images.json')['images']
    image_captions = "\n".join([f"{ii}) {image['description']}" for ii, image in enumerate(images)])

    messages = [
        system_message(MAP_IMAGE_PROMPT_TO_CAPTIONS_PROMPT.format(image_captions=image_captions)),
        user_message(prompt)
    ]

    response = str_2_json(extract_tag_content('decision', llm_complete(messages, LLM.ANTHROPIC_CLAUDE_3_5_SONNET)))

    if response['confidence'] == 2:
        return images[response['best_image_index']]['url']
    else:
        return ''

if __name__ == "__main__":
    setup_logging()

    print(generate_flux_image("Create a photorealistic image of a bustling Pre-Columbian village square during daytime, with indigenous families arranging tribute goods on woven reed mats. In the foreground, show people in traditional cotton clothing sorting vibrant textiles, clay pottery vessels, and stacks of corn and beans. Include children helping their parents bundle goods, emphasizing the communal atmosphere. The background features earthen adobe buildings with stepped doorways, and a stepped pyramid temple rises prominently against a clear blue sky. Natural lighting casts soft shadows across the plaza, highlighting the warm earth tones of the architecture and the colorful tribute items. Wide-angle perspective to capture both the detailed activities and architectural context."))