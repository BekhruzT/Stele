import base64
import inspect
import json
import logging
import os
import tempfile
import traceback
from enum import Enum
from pathlib import Path
from typing import Dict, List, Union, Optional
import uuid
import anthropic
import openai
import requests
from core.parsers import str_2_json
from tenacity import (retry, retry_if_not_exception_type, stop_after_attempt,
                      wait_exponential)
from core.clients.s3 import upload_file_to_s3
from core.constants import (OPENAI_API_KEY, OPENAI_ORGANIZATION_ID, TFY_API_KEY,
                            TFY_BASE_URL)
from core.pricing import gpt4_cost
from prompts.common_prompts import ENSURE_JSON_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

openai.api_key = OPENAI_API_KEY
openai.organization = OPENAI_ORGANIZATION_ID


class LLM(str, Enum):
    GPT_5 = "gpt-5.5"
    CLAUDE_5_SONNET = "claude-sonnet-5"
    CLAUDE_5_OPUS = "claude-opus-5"
    CLAUDE_FABLE_5 = "claude-fable-5"
    GEMINI_3_1_PRO = "gemini-3.1-pro-preview"
    GEMINI_3_FLASH = "gemini-3.6-flash"
    # Not gateway-routed: gemini.py needs Google's file upload API for video QC.
    GEMINI_2_5 = "gemini-2.5-pro-preview-03-25"

# Every model the gateway answers to. Absent means uncallable; there is no vendor fallback.
GATEWAY_MODEL_SLUGS: Dict[str, str] = {
    LLM.GPT_5.value: "openai-group/gpt-5.5",
    LLM.CLAUDE_5_SONNET.value: "claude-group/claude-sonnet-5",
    LLM.CLAUDE_5_OPUS.value: "claude-group/claude-opus-5",
    LLM.CLAUDE_FABLE_5.value: "claude-group/claude-fable-5",
    LLM.GEMINI_3_1_PRO.value: "gemini-group/gemini-3.1-pro",
    LLM.GEMINI_3_FLASH.value: "gemini-group/gemini-3.6-flash",
}

TFY_REQUIRED_MSG = ("TFY_API_KEY and TFY_BASE_URL are required: every chat completion "
                    "routes through the TrueFoundry gateway.")


def gateway_slug(model: Union[LLM, str]) -> str:
    """Resolve a model to its gateway slug, refusing anything unmapped or unconfigured."""
    name = model.value if isinstance(model, LLM) else model
    if not TFY_API_KEY or not TFY_BASE_URL:
        raise ValueError(TFY_REQUIRED_MSG)
    if name not in GATEWAY_MODEL_SLUGS:
        raise ValueError(f"No TrueFoundry gateway mapping for model {name!r}. "
                         f"Known: {', '.join(sorted(GATEWAY_MODEL_SLUGS))}")
    return GATEWAY_MODEL_SLUGS[name]

def add_to_messages(messages: List[Dict[str, str]], assistant: str, user: str) -> List[Dict[str, str]]:
    messages.extend([
        {"role": "assistant", "content": assistant},
        {"role": "user", "content": user}
    ])
    return messages


def openai_gpt4v_message(url, n):
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"This is Image {n}"},
            {
                "type": "image_url",
                "image_url": {
                    "url": url
                }
            },
        ],
    }


def system_message(prompt: str, *args, **kwargs):
    return {
        "role": "system",
        "content": prompt
    }

def assistant_message(prompt: str, *args, **kwargs):
    if kwargs:
        prompt = prompt.format(**kwargs)
    return {
        "role": "assistant",
        "content": prompt
    }

def user_message(prompt: str, *args, **kwargs):
    if kwargs:
        prompt = prompt.format(**kwargs)
    return {
        "role": "user",
        "content": prompt
    }


def ensure_json_prompt(response: str):
    return [
        {"role": "system", "content": ENSURE_JSON_SYSTEM_PROMPT},
        {"role": "user", "content": f"{response}"}
    ]

def log_llm_message(messages, response, invoker):
    # return
    filename = './prompts.txt'
    text = "\n".join([f"[[ {m['role']} ]]\n{m['content']}\n" for m in messages])
    text = f"\n######################## {invoker} ########################\n{text}\n[[ response ]]\n{response}\n########################################################\n"
    # utf-8 explicitly, because Windows defaults to cp1252 and raises on the arrows, dashes
    # and curly quotes models emit constantly. And never fatal: this runs inside
    # chat_complete after the completion has been paid for, so a failure to write a debug
    # log used to discard the response and burn all three retries doing it again.
    try:
        with open(filename, 'a', encoding='utf-8') as file:
            file.write(text)
    except Exception as error:
        logger.warning(f"Could not append to {filename}: {error}")

def get_caller_function():
    # Get the full stack
    stack = inspect.stack()
    # Define utility functions to skip
    utility_functions = ['llm_complete', 'chat_complete', 'call_openai_vision',
                         'log_llm_message', 'chat_complete', 'llm_call', 'llm_call_with_qc', 
                         'ensure_json', 'get_caller_function', '__call__', 'wrapped_f', '<module>']
    # Find the first function that's not in our utility list
    for frame in stack:
        if frame.function not in utility_functions:
            return frame.function
    # Fallback if we can't find a non-utility function
    return "unknown_caller"

@retry(stop=stop_after_attempt(30), wait=wait_exponential(multiplier=1, max=60),
       retry=retry_if_not_exception_type(ValueError))
def llm_complete(messages: List[Dict], model: Union[LLM, str] = LLM.GPT_5, temperature: float = 0, max_tokens: int = 4000,
                 cost_callback=None):
    # Deliberately outside the try: the handler below swallows every exception and returns
    # None, so a guard raised inside it would become the silent failure it exists to stop.
    # Fail fast: an unmapped model is a config error, and the retry decorator would stall 25min.
    gateway_slug(model)
    try:
        return chat_complete(messages, model, temperature, max_tokens, cost_callback)
    except Exception:
        logger.error(traceback.format_exc())

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=60),
       retry=retry_if_not_exception_type(ValueError))
def chat_complete(messages: List[Dict], model: Union[LLM, str] = LLM.GPT_5, temperature: float = 0, max_tokens: Union[int, None] = None,
                  cost_callback=None):
    """One chat completion through the TrueFoundry gateway, on whichever vendor owns the model."""
    slug = gateway_slug(model)
    # temperature is never sent and max_tokens reaches Claude only; reasoning models reject both.
    response = (claude_complete(messages, slug, max_tokens) if slug.startswith("claude-group/")
                else openai_complete(messages, slug, cost_callback))
    log_llm_message(messages, response, get_caller_function())
    return response


def openai_complete(messages: List[Dict], slug: str, cost_callback=None) -> Optional[str]:
    """A completion over the gateway's OpenAI-compatible route, which every vendor answers on."""
    try:
        response = openai.OpenAI(api_key=TFY_API_KEY, base_url=TFY_BASE_URL).chat.completions.create(
            model=slug,
            messages=messages,  # type: ignore
        )
        if cost_callback and response.usage:
            cost_callback(*gpt4_cost(response.usage.prompt_tokens, response.usage.completion_tokens))
        return response.choices[0].message.content
    except Exception as error:
        logger.error(f"Error from gateway model {slug}: {error}\nTraceback: {traceback.format_exc()}")
        raise


def claude_complete(messages: List[Dict], slug: str, max_tokens: Union[int, None] = None) -> Optional[str]:
    """A completion over the gateway's native Anthropic route, which wants system split out."""
    # Anthropic refuses a blank system prompt, and llm_call passes '' all over the stages.
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    try:
        completion = anthropic.Anthropic(
            api_key="unused-tfy-gateway",
            base_url=TFY_BASE_URL,
            default_headers={"x-tfy-api-key": TFY_API_KEY},
            timeout=1200.0,
        ).messages.create(
            model=slug,
            max_tokens=max_tokens or 50000,
            messages=[m for m in messages if m["role"] != "system"],  # type: ignore
            **({"system": system} if system else {}),
        )
        return next((block.text for block in completion.content if block.type == "text"), None)
    except Exception as error:
        logger.error(f"Error from gateway model {slug}: {error}\nTraceback: {traceback.format_exc()}")
        raise


def call_openai_vision(messages: List[Dict], model: Union[LLM, str] = LLM.GPT_5):
    """Vision through the gateway, retried once with every image inlined as a data URI."""
    slug = gateway_slug(model)
    try:
        response = openai_complete(messages, slug)
    except Exception:
        for message in messages:
            if 'content' in message and isinstance(message['content'], list):
                for content_part in message['content']:
                    if content_part.get('type') == 'image_url' and 'image_url' in content_part:
                        image_info = content_part['image_url']
                        if 'url' in image_info:
                            image_url = image_info['url']
                            try:
                                fetched = requests.get(image_url)
                                fetched.raise_for_status()
                                image_base64 = base64.b64encode(fetched.content).decode('utf-8')
                                image_info['url'] = f"data:image/png;base64,{image_base64}"

                            except Exception as e2:
                                logger.error(f"Error handling image at {image_url}: {e2}")
        response = openai_complete(messages, slug)
    log_llm_message(messages, response, get_caller_function())
    return response


def ensure_json(response: str) -> Union[Dict, List]:
    try:
        return str_2_json(response)
    except:
        logger.info(f"Failed to parse json: {response}")
        corrected_resp = chat_complete(ensure_json_prompt(response), LLM.GPT_5)
        corrected_resp = corrected_resp.removeprefix("```json").removesuffix("```")
        logger.info(f'corrected resp: {corrected_resp}')
        obj = json.loads(corrected_resp, strict=False)
        return obj


def generate_image_dalle(prompt, n=1, model: str = "dall-e-3"):
    client = openai.OpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORGANIZATION_ID)

    response = client.images.generate(
        model=model,
        prompt=prompt,
        n=n,
        size="1792x1024",
        quality="hd",
        style='natural'
    )
    return response.data[0].url


def generate_openai_image(prompt: str, image_path: Optional[str] = None, quality: str = "high") -> str:
    client = openai.OpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORGANIZATION_ID)

    if image_path is None:
        image_path = str(Path(tempfile.gettempdir()) / f"{uuid.uuid4()}.png")
    
    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size='1536x1024',
        quality=quality
    )

    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)

    # Save the image to a file
    with open(image_path, "wb") as f:
        f.write(image_bytes)
    image_url = upload_file_to_s3(image_path, f'GPT_Images/{os.path.basename(image_path)}', s3_bucket='gen-ai-textbooks-media')
    return  image_url


