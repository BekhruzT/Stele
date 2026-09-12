import base64
import inspect
import json
import logging
import os
import time
import traceback
from enum import Enum
from json import JSONDecodeError
from pathlib import Path
from typing import Dict, List, Union, Optional
import uuid
import openai
import requests
from core.parsers import str_2_json
from langchain.agents import Tool, initialize_agent
from langchain_community.chat_models import ChatOpenAI
from langchain_community.utilities import GoogleSearchAPIWrapper
from openai import OpenAI
from tenacity import (retry, retry_if_not_exception_type, stop_after_attempt,
                      wait_exponential)
from core.clients.s3 import load_json_from_s3, upload_file_to_s3
from core.constants import OPENAI_API_KEY, OPENAI_ORGANIZATION_ID
from core.logger import Logger
from core.pricing import gpt4_cost

# logger = Logger("OpenAIClient", logging.DEBUG)
logger = logging.getLogger(__name__)

openai.api_key = OPENAI_API_KEY
openai.organization = OPENAI_ORGANIZATION_ID


class LLM(str, Enum):
    GPT_4_0613 = 'gpt-4-0613'
    GPT_4_TURBO = 'gpt-4-turbo'
    GPT_4_1 = 'gpt-4.1'
    GPT_4_O = 'gpt-4o'
    GPT_4_O_LATEST = 'gpt-4o-2024-08-06'
    O1_PREVIEW = 'o1'
    O1 = 'o1'
    # GEMINI_2_5 = "gemini-2.5-pro-preview-05-06"
    GEMINI_2_5 = "gemini-2.5-pro-preview-03-25"

    # ponytail: Anthropic is retired. These four keep their old names but carry GPT values,
    # so they are enum aliases of the members above and the ~58 call sites that spell
    # LLM.CLAUDE_3_7_SONNET keep working untouched. They must stay below their targets;
    # an alias resolves to whichever member was defined first.
    #
    # The ceiling: CLAUDE_3_7_SONNET_THINKING used to buy a real extra tier via
    # thinking={"budget_tokens": 6000}, and now collapses onto the same model as the
    # non-thinking calls. Upgrading means routing it to a reasoning model, which needs a
    # new branch in chat_complete for max_completion_tokens and a fixed temperature.
    CLAUDE_3_7_SONNET = 'gpt-4.1'
    CLAUDE_3_7_SONNET_THINKING = 'gpt-4.1'
    ANTHROPIC_CLAUDE_3_5_SONNET = 'gpt-4o'
    ANTHROPIC_CLAUDE_3_5_SONNET_V2 = 'gpt-4o'

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


def print_openai_messages(messages: List[Dict[str, str]]):
    logger.info("\n\n".join([f"{v['role']}\n{v['content']}" for v in messages]))


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
        {"role": "system", "content": '''The user will provide a broken JSON response that GPT provided earlier.
1. You will respond only with the corrected format of that same exact JSON Object.
2. Ensure that python json.loads() will accept this JSON string as a dict.
3. If the JSON is already in corrected format then respond with that corrected JSON, never respond in any other format other than JSON.'''},
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
def llm_complete(messages: List[Dict], model: Union[LLM, str] = "gpt-4o", temperature: float = 0, max_tokens: int = 4000,
                 cost_callback=None):
    model = model.value if isinstance(model, LLM) else model
    # Deliberately outside the try: the handler below swallows every exception and returns
    # None, so a guard raised inside it would become the silent failure it exists to stop.
    # The decorator excludes ValueError for the same reason -- a bad model name is a config
    # error, and retrying it 30 times with backoff stalls for ~25 minutes before giving up.
    if not (model.startswith("gpt") or model.startswith("o1")):
        raise ValueError(
            f"{model!r} is not an OpenAI model. The Anthropic route was removed; add the "
            f"model to LLM with a gpt-* value, or call its own client directly as Gemini does."
        )
    try:
        return chat_complete(messages, model, temperature, max_tokens, cost_callback)
    except Exception:
        logger.error(traceback.format_exc())

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=60))
def chat_complete(messages: List[Dict], model: str = "gpt-4-0613", temperature: float = 0, max_tokens: Union[int, None] = None,
                  cost_callback=None):
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORGANIZATION_ID)
        if model == "o1-preview" or model == "o1":
            # if messages[0]['role'] == 'system':
                # messages[0]['role'] = 'developer'
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=300
            )
        else:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
        if cost_callback:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            prompt_cost, completion_cost = gpt4_cost(prompt_tokens, completion_tokens)
            cost_callback(prompt_cost, completion_cost)
        log_llm_message(messages, response.choices[0].message.content, get_caller_function())
        return response.choices[0].message.content
    except Exception as error:
        logger.error(f"Error from OpenAI: {error}\nTraceback: {traceback.format_exc()}")
        raise


def call_openai_vision(messages: List[Dict], model: str = "gpt-4o"):
    client = openai.OpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORGANIZATION_ID)
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            max_tokens=4000
        )
        log_llm_message(messages, response.choices[0].message.content, get_caller_function())
        return response.choices[0].message.content
    except Exception as e:
        for message in messages:
            if 'content' in message and isinstance(message['content'], list):
                for content_part in message['content']:
                    if content_part.get('type') == 'image_url' and 'image_url' in content_part:
                        image_info = content_part['image_url']
                        if 'url' in image_info:
                            image_url = image_info['url']
                            try:
                                response = requests.get(image_url)
                                response.raise_for_status()
                                image_data = response.content
                                image_base64 = base64.b64encode(image_data).decode('utf-8')
                                image_info['url'] = f"data:image/png;base64,{image_base64}"

                            except Exception as e2:
                                logger.error(f"Error handling image at {image_url}: {e2}")
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=4000
            )
            log_llm_message(messages, response.choices[0].message.content, get_caller_function())
            return response.choices[0].message.content
        except Exception as e3:
            logger.error(f"Second attempt failed with error: {e3}")
            raise e3


def ensure_json(response: str) -> Union[Dict, List]:
    try:
        return str_2_json(response)
    except:
        logger.info(f"Failed to parse json: {response}")
        corrected_resp = chat_complete(ensure_json_prompt(response), "gpt-4o")
        corrected_resp = corrected_resp.removeprefix("```json").removesuffix("```")
        logger.info(f'corrected resp: {corrected_resp}')
        obj = json.loads(corrected_resp, strict=False)
        return obj


def get_langchain_agent(model: str = "gpt-4-0613"):
    search = GoogleSearchAPIWrapper(k=3)
    tool = Tool(
        name="Google Search",
        description="Search Google for recent results.",
        func=search.run,
    )
    tools = [tool]
    llm = ChatOpenAI(model_name=model, temperature=0)
    agent = initialize_agent(tools, llm, agent="zero-shot-react-description", verbose=True)
    return agent


class OpenaiAssistantConversation:
    def __init__(self, assistant_id, thread_id=None):
        self.assistant_id = assistant_id
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.thread = self.client.beta.threads.retrieve(thread_id) if thread_id else self.client.beta.threads.create()

    def _wait_on_run(self, thread_run):
        terminal_status = ["cancelled", "failed", "completed", "expired", "requires_action"]
        # logger.info(f'Entering loop to check for terminal status')
        i = 0
        while thread_run.status not in terminal_status:
            thread_run = self.client.beta.threads.runs.retrieve(
                thread_id=self.thread.id,
                run_id=thread_run.id,
            )
            time.sleep(1)
            i += 1
            # if i % 15 == 0:
            # logger.info(f'Waiting for thread run to complete: {thread_run.status}')
        return thread_run

    @retry(stop=stop_after_attempt(30), wait=wait_exponential(multiplier=1, max=60))
    def ask_assistant_sync(self, query_input: str):
        try:
            message = self.client.beta.threads.messages.create(
                thread_id=self.thread.id,
                role="user",
                content=query_input,
            )
            # logger.info(f'Created message with id {message.id} and {message}')
            run = self.client.beta.threads.runs.create(
                thread_id=self.thread.id,
                assistant_id=self.assistant_id,
            )
            # logger.info(f'Created run with id {run.id} and {run}')
            run = self._wait_on_run(run)
            # logger.info(f'Returning run  with status {run.status} info as {run}')
            if run.status == "failed":
                logger.error(f"Failed run - {run.status}. {self.thread.id}. {run.last_error}")
                raise Exception("Failed Run")
            return run, message
        except Exception as e:
            logger.error(f"Error asking assistant: {e}")
            raise e

    def fetch_messages_after(self, message):
        messages = self.client.beta.threads.messages.list(
            thread_id=self.thread.id, order="asc", after=message.id
        )
        return messages

    def delete_message(self, message):
        deleted_message = self.client.beta.threads.messages.delete(
            message_id=message.id,
            thread_id=self.thread.id,
        )
        return deleted_message


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


def generate_speech_via_openai(text:str, speech_file_path='./speech.mp3', voice='echo')->dict:
    response = openai.audio.speech.create(
        model="tts-1-hd",
        voice=voice,
        input=text
    )
    response.stream_to_file(speech_file_path)

    return response


def tts(speech_file_path='./speach.mp3'):
    client = openai.OpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORGANIZATION_ID)

    audio_file = open(speech_file_path, "rb")
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file
    )
    return response

def generate_openai_image(prompt: str, image_path: Optional[str] = None):
    client = openai.OpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORGANIZATION_ID)

    if image_path is None:
        image_path = f"/tmp/{uuid.uuid4()}"
    
    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size='1536x1024',
        quality='high'
    )

    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)

    # Save the image to a file
    with open(image_path, "wb") as f:
        f.write(image_bytes)
    image_url = upload_file_to_s3(image_path, f'GPT_Images/{os.path.basename(image_path)}', s3_bucket='gen-ai-textbooks-media')
    return  image_url


