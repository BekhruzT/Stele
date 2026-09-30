import base64
import functools
import json
import logging
import mimetypes
import re
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple, Union, Callable

import requests
from core.context import Context
from prompts.clips_prompts import (
    IDENTIFY_LOCATION_SYSTEM_PROMPT, IDENTIFY_LOCATION_USER_PROMPT, IMAGE_GEN_SYSTEM_PROMPT,
    IMAGE_GEN_USER_PROMPT, LUMA_VIDEO_PROMPT, LUMA_VIDEO_USER_PROMPT)
from prompts.common_prompts import \
    get_subject_specific_clips_prompt_entries
from prompts.qc_prompts import (   
    QC_FINDER_SYSTEM_PROMPT, QC_FINDER_USER_PROMPT, content_guidelines
    )
from fuzzywuzzy import fuzz
from pydantic import BaseModel
from core.clients.openai import (LLM, assistant_message, ensure_json, llm_complete,
                          system_message, user_message)
from core.clients.s3 import load_json_from_s3

logger = logging.getLogger(__name__)

# Dictionary to store named semaphores. Each lock_name gets its own semaphore.
_named_semaphores = {}

def concurrency_slots(slots: int, lock_name: str):
    """
    A decorator that limits concurrency to 'slots' threads at once 
    for a given lock_name. Each distinct lock_name has its own semaphore. 
    
    Example usage:
    @concurrency_slots(slots=2, lock_name="video_generation")
    def generate_all_videos(...):
        ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # If we haven't created a semaphore for this lock_name yet, create one.
            if lock_name not in _named_semaphores:
                _named_semaphores[lock_name] = threading.Semaphore(slots)

            semaphore = _named_semaphores[lock_name]
            logger.info(f"Waiting to acquire {lock_name} slot...")
            with semaphore:
                logger.info(f"Acquired {lock_name} slot. Beginning '{func.__name__}'...")
                try:
                    return func(*args, **kwargs)
                finally:
                    logger.info(f"Releasing {lock_name} slot (finished '{func.__name__}').")
        return wrapper
    return decorator

def llm_call(
    system_prompt:str, 
    user_prompt: str, 
    model: LLM, 
    tag: Optional[str]=None, 
    is_json: bool = False, 
    history: List[Dict[str, str]]= [], 
    temperature: float = 0
) -> Tuple[List[Dict[str, str]], Any]:
    messages = [
        *([system_message(system_prompt)] if not history else history),
        user_message(user_prompt)
    ]
    response = llm_complete(messages, model = model, temperature = temperature) or ''
    messages.append(assistant_message(response))
    if tag is not None:
        response = extract_tag_content(tag, response)
    if is_json:
        response = ensure_json(response or '{}')
    return messages, response


def llm_call_with_qc(
    system_prompt: str, 
    user_prompt: str, 
    model: LLM = LLM.GPT_5, 
    tag: Optional[str] = None, 
    is_json: bool = False, 
    history: List[Dict[str, str]] = [],
    temperature: float = 0,
    # Optional QC-related parameters
    qc_requirements: Optional[str] = None,
    qc_model: LLM = LLM.CLAUDE_5_SONNET,
    type_of_content: str = "content",
    max_iterations: int = 2
) -> Tuple[List[Dict[str, str]], Any]:
    """
    Enhanced LLM call function with optional QC support.
    
    Args:
        system_prompt: System prompt for the main task
        user_prompt: User prompt for the main task
        model: LLM model to use for the main task
        tag: Optional tag to extract from response
        is_json: Whether to ensure response is JSON
        history: Previous conversation history
        qc_requirements: Optional requirements for QC check
        qc_model: Optional model to use for QC (defaults to CLAUDE_3_7_SONNET)
        type_of_content: Description of the type of content being generated (e.g., "text slide content", default is "content")
        max_iterations: Maximum QC iterations, default is 2
        
    Returns:
        Tuple containing:
        - Conversation history as list of messages
        - Final response (either string or dict depending on is_json)
    """
    from core.types import \
        Feedback
    from prompts.overlay_prompts import (
        QC_FEEDBACK_PROMPT, QC_RETURN_ONLY, QC_RETURN_TAG_HINT, QC_SYSTEM_PROMPT, QC_USER_PROMPT,
        length_violation_feedback)
    return_only = QC_RETURN_ONLY.format(output_format='JSON' if is_json else 'text',
                                        tag_hint=QC_RETURN_TAG_HINT.format(tag=tag) if tag is not None else '')
    
    messages = [
        *([system_message(system_prompt)] if not history else history),
        user_message(user_prompt)
    ]
    max_iterations = max_iterations if qc_requirements else 1
    
    feedback_list = []
        
    for iteration in range(max_iterations):
        logger.debug(f"Generating {type_of_content} {f'it-{iteration}' if max_iterations > 1 else ''}")
            
        # Add previous feedback if any  
        current_messages = messages.copy()
        for feedback in feedback_list:
            current_messages.append(assistant_message(feedback.output))
            current_messages.append(user_message(QC_FEEDBACK_PROMPT.format(
                    content_type=type_of_content,
                    feedback=feedback.feedback
                ) + return_only
            ))

        # Get task output
        _, response = llm_call('', current_messages[-1]['content'], model, tag, is_json, current_messages[:-1], temperature)

        current_messages.append(assistant_message(json.dumps(response, indent=2) if is_json else str(response)))
        logger.debug(f"Generated {type_of_content} {f'it-{iteration}' if max_iterations > 1 else ''}")
            
        # QC check
        if qc_requirements and iteration < max_iterations - 1:
            _, qc_result = llm_call(
                system_prompt=QC_SYSTEM_PROMPT,
                user_prompt=QC_USER_PROMPT.format(
                    content_type=type_of_content,
                    requirements=qc_requirements,
                    output=str(json.dumps(response, indent=2) if is_json else response)
                ),
                model=qc_model,
                tag="review",
                is_json=True
            )
                

            if type_of_content=="text slide content":
                length_limit = 510
                
                length = sum([len(point) for point in response['points']])
                if length > length_limit:
                    qc_result['qc_pass'] = False
                    qc_result['feedback'] += length_violation_feedback.format(length_limit=length_limit, overflow = length - length_limit)

            qc_pass = qc_result.get('qc_pass', False)

            
            if qc_pass:
                logger.debug(f"{type_of_content} passed QC")
                break

            logger.info(f"{type_of_content} QC failed with feedback: {qc_result.get('feedback', '')}")
            feedback_list.append(Feedback(
                feedback=qc_result.get('feedback', ''),
                output=json.dumps(response, indent=2) if is_json else str(response)
            ))

    return current_messages, response


def image_to_data_uri(image_path: str)->str:
    mime_type, _ = mimetypes.guess_type(image_path)
    if mime_type is None:
        raise ValueError(f"Could not determine MIME type for {image_path}")

    # Read the image file in binary mode
    with open(image_path, 'rb') as image_file:
        image_data = image_file.read()

    # Encode the binary data to base64
    base64_encoded_data = base64.b64encode(image_data).decode('utf-8')

    # Format the data URI
    data_uri = f"data:{mime_type};base64,{base64_encoded_data}"
    return data_uri


def exception_handler(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error: {e}")
            logger.error(f"Error Traceback: {traceback.format_exc()}")
            raise e
    return wrapper


def print_json(obj: dict, prefix: str = '') -> None:
    print(f"\n```{prefix}\n{json.dumps(obj, indent=2)}\n```")


def extract_tag_content(tag_name: str, text: str)->str:
    pattern = f"<{tag_name}[^>]*>(.*?)</{tag_name}>"
    match = re.search(pattern, text, re.DOTALL)
    
    if match:
        return match.group(1).strip()
    else:
        logger.error(f"No tag - {tag_name} - found:\n{text}\n")
        return None

def split_speaker_dialogue(line: str):
    return re.match(r'^\[([^]]+)\]:\s*(.*)$', line)

def split_transcript(transcript):
    # Remove any leading/trailing whitespace and split by newlines
    lines = transcript.strip().split('\n')
    
    total_words = 0  # Keeps track of the total words processed so far
    start_word_index = 0  # Start index for the current speaker's dialogue
    current_speaker = None
    current_dialogues = []
    speaker_segments = []

    for line in lines:
        # Check if the line starts with a speaker designation
        match = split_speaker_dialogue(line)
        if match:
            new_speaker = match.group(1).strip()
            new_dialogue = match.group(2).strip()
            
            # If we have a new speaker, add the previous segment and start a new one
            if current_speaker and (new_speaker != current_speaker):
                # Compute the end word index for the current speaker's dialogue
                end_word_index = total_words
                speaker_segments.append({
                    'speaker': current_speaker,
                    'dialogue': ' '.join(current_dialogues),
                    'word_count_range': (start_word_index, end_word_index)
                })
                current_dialogues = []  # Reset the current dialogues
                start_word_index = total_words  # Update the start index for the new speaker

            current_speaker = new_speaker
            # Count the words in the new dialogue line
            line_word_count = len(new_dialogue.strip().split())
            total_words += line_word_count
            current_dialogues.append(new_dialogue)
        else:
            # If there's no speaker, it's a continuation of the previous dialogue
            if current_speaker:
                continuation_line = line.strip()
                # Count the words in the continuation line
                line_word_count = len(continuation_line.split())
                total_words += line_word_count
                current_dialogues.append(continuation_line)
            else:
                # Handle prefix without speaker
                # This is unexpected, probably some prefix before the actual transcript
                # So we will just ignore it
                logger.info(f"Prefix without speaker: {line.strip()}")

    # Add the last speaker's dialogue
    if current_speaker:
        end_word_index = total_words
        speaker_segments.append({
            'speaker': current_speaker,
            'dialogue': ' '.join(current_dialogues),
            'word_count_range': (start_word_index, end_word_index)
        })

    return speaker_segments
        
def generate_img_prompt(subject: str, description: str) -> str:
    ssi = get_subject_specific_clips_prompt_entries(subject)
    messages = [
        system_message(IMAGE_GEN_SYSTEM_PROMPT.format(**ssi)),
        user_message(IMAGE_GEN_USER_PROMPT.format(description=description, **ssi))
    ]

    prompt = llm_complete(messages, model=LLM.CLAUDE_5_SONNET)
    
    extracted_prompt = extract_tag_content('prompt', prompt)
    if extracted_prompt:
        return extracted_prompt
    else:
        return prompt

def generate_video_prompt(subject: str, description: str, img_prompt: str) -> str:
    ssi = get_subject_specific_clips_prompt_entries(subject)

    messages = [
        system_message(LUMA_VIDEO_PROMPT.format(**ssi)),
        user_message(LUMA_VIDEO_USER_PROMPT.format(img_prompt=img_prompt, description=description))
    ]

    prompt = llm_complete(messages, model=LLM.CLAUDE_5_SONNET)
    
    extracted_prompt = extract_tag_content('prompt', prompt)
    if extracted_prompt:
        return extracted_prompt
    else:
        return prompt

def save_video(video_url: str, local_path: str)->None:
    try:
        with requests.get(video_url, stream=True) as response:
            response.raise_for_status()

            # total_size = int(response.headers.get('content-length', 0))
            # bytes_downloaded = 0

            with open(local_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
                        # bytes_downloaded += len(chunk)
                        # if total_size > 0:
                        #     percent = (bytes_downloaded / total_size) * 100
                        #     print(f'Downloaded {bytes_downloaded} of {total_size} bytes ({percent:.2f}%)', end='\r')

        logger.debug(f"Video downloaded successfully and saved to '{local_path}'.")
    except requests.exceptions.HTTPError as http_err:
        logger.error(f'HTTP error occurred: {http_err}')
    except Exception as err:
        logger.error(f'An error occurred: {err}') 


def sanitize_path(path):
    sanitized = re.sub(r'[^a-zA-Z0-9_\-/]', '_', path.strip())
    sanitized = re.sub(r'_+', '_', sanitized).strip('_')
    return sanitized


    
def fuzzy_find_matching_string(text: str, options: List[str], similarity_threshold: int = 95) -> str:
    best_score, best_match = max((fuzz.ratio(text, opt), opt) for opt in options)
    if best_score < similarity_threshold:
        print(f"Threshold: {similarity_threshold}, Input: {text}, Best: {best_match}, Score: {best_score}")
    return best_match


class LLMCallOutput(BaseModel):
    content: Union[str, Tuple[str, ...], dict, list]
    model: LLM
    history: List[Dict[str, str]]
    context: Optional[str] = None
    postprocess: Optional[Callable[[str], str]] = None

def qc_llm_call(content_type: str, evaluation_type: str):
    def decorator(llm_caller_func):
        def wrapper(*args, **kwargs):
            main_guidelines = content_guidelines[content_type]

            guidelines = main_guidelines['guidelines'].get(evaluation_type, None)
            llm_call_output = llm_caller_func(*args, **kwargs)
            if guidelines is None:
                logger.error(f"Couldn't find content type: {evaluation_type}")
                return llm_call_output.content

            content_tag = main_guidelines['name'].replace(' ', '_')
            content = json.dumps(llm_call_output.content, indent=2) if isinstance(llm_call_output.content, dict) or isinstance(llm_call_output.content, list) else llm_call_output.content
            _, finder_output = llm_call(
                system_prompt=QC_FINDER_SYSTEM_PROMPT.format(content_type=content_type.capitalize(), 
                                                             content_description=guidelines['description'],
                                                             quality_criteria=guidelines['guidelines'],
                                                             context=main_guidelines['context'],
                                                             general_content=main_guidelines['name']
                                                             ),
                user_prompt=QC_FINDER_USER_PROMPT.format(
                    transcript_segment=f"<{content_tag}>\n{content}\n</{content_tag}>",
                    context="" if llm_call_output.context is None else llm_call_output.context,
                    general_content=main_guidelines['name']
                ),
                model=LLM.CLAUDE_5_OPUS if evaluation_type=="CONCEPT EXPLANATION" or content_type=="VideoPlan"  else LLM.CLAUDE_5_SONNET
            )
            any_fail = any(x.lower() == 'fail' for x in re.findall(r'<evaluation>(.*?)</evaluation>', finder_output, flags=re.DOTALL))

            output = llm_call_output.content
            if any_fail:
                _, output = llm_call(
                    system_prompt='',
                    user_prompt=main_guidelines['fixer'].format(finder=finder_output),
                    model=llm_call_output.model,
                    history=llm_call_output.history
                )
                if llm_call_output.postprocess is not None:
                    output = llm_call_output.postprocess(output)
                
            return output
        return wrapper
    return decorator

def fix_single_icon(icon: str, icon_for: str, valid_icons: List[str]) -> str:
    from prompts.overlay_prompts import FIX_ICON_USER_PROMPT
    attempts = 0
    while icon not in valid_icons and attempts < 5:
        attempts += 1
        logger.warning(f"Icon '{icon}' is not a valid font awesome classic solid free icon. Attempt {attempts} of 5 to fix it.")
        _, icon = llm_call(
            system_prompt='',
            user_prompt=FIX_ICON_USER_PROMPT.format(icon=icon, valid_icons=json.dumps(valid_icons, indent=2), icon_for=icon_for),
            model=LLM.CLAUDE_5_OPUS,
            is_json=False,
            temperature=1
        )
    return icon

def identify_location(context: Context, snippet: str)->str:
    transcript = load_json_from_s3(context.transcripts_path)['lesson_transcript']
    history, location = llm_call(
        system_prompt=IDENTIFY_LOCATION_SYSTEM_PROMPT,
        user_prompt=IDENTIFY_LOCATION_USER_PROMPT.format(transcript=transcript, snippet=snippet),
        tag = "location",
        model=LLM.CLAUDE_5_SONNET
    )
    return location