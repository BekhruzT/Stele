import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple, Union
from xmlrpc.server import list_public_methods

from core.types import (
    MCQ, ArtifactImage, AvatarAsset, Concept, Diagram, DiagramType,
    DiagramVisual, OverlaysData, TextSlide, TranscriptConcept,
    TranscriptLesson, TranscriptOutput, TranscriptTiming, VideoPlan,
    WordTiming)
from core.media.clip_timings import \
    match_segment_timings
from core.log import (
    setup_logging, with_logging_context)
from core.helpers import (
    LLMCallOutput, extract_tag_content, llm_call, print_json)
from core.stage_constants import (
    CHARACTER_BUNDLE, elevenlabs_voice_descriptions, get_unit_from_chapter)
from core.media.html_to_video import (
    render_diagram_template, render_text_slide_template)
from core.media.media_assets import (
    convert_mov_to_mp4, update_transcript_with_artifact_reference)
from ops.repair.regenerate_concept_prompts import (
    SYSTEM_PROMPT_DETERMINE_NEED_FOR_CHANGE, SYSTEM_PROMPT_UPDATE_TRANSCRIPT,
    USER_PROMPT_DETERMINE_NEED_FOR_CHANGE, USER_PROMPT_UPDATE_TRANSCRIPT,
    regeneration_guidelines_by_asset)
from ops.repair.text_slides import \
    match_point_timings as match_slide_point_timings
from stages.avatar_clips import (
    create_avatar, find_best_match, find_best_voice, load_speaker,
    synthesize_speech)
from stages.local_render import \
    render_lesson
from stages.text_overlays import (
    identify_diagram_timings, identify_question_timings,
    identify_video_split_times, models, process_diagram_concept,
    process_text_slide_concept)
from stages.transcript import (
    add_transcript_pauses, format_concept, generate_questions_per_concept,
    get_transcript_string, shuffle_mcqs_options)
from prompts.prompts import (
    MCQ_PER_CONCEPT_SYSTEM_PROMPT, MCQ_PER_CONCEPT_USER_PROMPT)
from core.clients.images import (GeneratedImageTypes, generate_image,
                                          save_image)
from tenacity import retry, stop_after_attempt, wait_exponential, wait_none
from config.courses import get_execution_input
from core.context import APVideoContext as Context
from core.context import (get_lesson_context,
                                        prep_content_gen_input)
from core.hash import hash_image_description
from core.clients.openai import LLM, assistant_message, system_message, user_message
from core.clients.s3 import (create_presigned_url, does_file_exist, download,
                      load_json_from_s3, save_json_to_s3, upload_file_to_s3)
from core.clients.speech import get_audio_duration

logger = logging.getLogger(__name__)
setup_logging(level=logging.DEBUG)


def get_edited_path(path):
    return path if '-edited.json' in path else path.replace('.json', '-edited.json')

def wait_approval(approval_message):
    def decorator(func):
        def wrapper(*args, **kwargs):
            response = None
            while True:
                updated_kwargs = kwargs.copy()
                if response is not None:
                    updated_kwargs["custom_msg"] = response
                result = func(*args, **updated_kwargs)
                
                response = input(f"\n{approval_message} - {func.__name__} - Approve? (y/n): ").strip()
                
                if response.lower() == 'y':
                    if hasattr(result, 'file') and os.path.exists(result.name):
                        os.remove(result['file'])
                    return result
                
                print(f"Re-running {func.__name__}...")
        return wrapper
    return decorator

def update_intermediate_outputs(file: str, layer: str, data: dict):
    json_data = {context.key: {section_name: {concept_name: {}}}}
    if os.path.exists(file):
        try:
            with open(file, 'r') as f:
                json_data = json.load(f)
        except json.JSONDecodeError:
            pass
    
    json_data.setdefault(context.key, {}).setdefault(section_name, {}).setdefault(concept_name, {}).setdefault(layer, data)
    with open(file, 'w') as f:
        json.dump(json_data, f, indent=2)

def determine_change_type(asset_type: str, change_context: str, asset: Optional[str] = None) -> Tuple[bool, str]:
    if asset_type == "MCQs":
        return False, ""
    guidelines = regeneration_guidelines_by_asset[asset_type]
    history, response = llm_call(
        system_prompt=SYSTEM_PROMPT_DETERMINE_NEED_FOR_CHANGE.format(asset_type=asset_type, regeneration_guidelines=guidelines),
        user_prompt=USER_PROMPT_DETERMINE_NEED_FOR_CHANGE.format(
            asset_type=asset_type,
            change_context=change_context,
            asset="" if asset is None else f"Also here is the {asset_type}, identify whether it needs updating"
        ),
        model=LLM.CLAUDE_5_SONNET,
        tag="output",
        is_json=True
    )
    return response["regenerate"], response["reasoning"]

def update_transcript_content(transcript_content: str, change_request: str) -> str:
    history, updated_content = llm_call(
        system_prompt=SYSTEM_PROMPT_UPDATE_TRANSCRIPT,
        user_prompt=USER_PROMPT_UPDATE_TRANSCRIPT.format(
            transcript_content=transcript_content,
            change_request=change_request
        ),
        model=LLM.CLAUDE_5_SONNET,
        tag="transcript"
    )
    
    transcript = get_approval("transcript explanation", {"transcript": updated_content}, {"transcript": transcript_content})["transcript"]

    return transcript

def add_pauses_to_explanation(explanation: str, figure_name: str, comment: str = '') -> str:
    paused_transcript = add_transcript_pauses(f"[{figure_name}]: {explanation}", comment) 
    
    paused_transcript = re.sub(r'\[[^\]]*\]:', '', paused_transcript).strip() + "\n"

    paused_transcript = get_approval("paused transcript", {"paused_transcript": paused_transcript})["paused_transcript"]

    return paused_transcript

def get_approval(name: str, edited_json: Dict[str, Any], original_json: Optional[Dict[str, Any]] = None) -> None:
    filename = f"./{name}.json"
    
    if original_json and original_json!=edited_json:
        with open(filename, 'w') as f:
            json.dump(original_json, f, indent=2)
        subprocess.run(['git', 'add', filename])
    
    with open(filename, 'w') as f:
        json.dump(edited_json, f, indent=2)
    
    input(f"Saved {'and staged ' if original_json else ''}changes to {filename}")

    with open(filename, 'r') as f:
        result = json.load(f)
    
    if original_json and original_json!=edited_json:
        subprocess.run(['git', 'reset', '--quiet', filename])
    
    os.remove(filename)
    
    return result

def update_mcqs_for_concept(concept: Concept, original_mcqs: List[MCQ], original_explanation: str, updated_explanation: str) -> List[MCQ]:

    history, updated_mcqs = llm_call(
        system_prompt="",
        user_prompt=f"The transcript for the concept has been slightly updated, update the MCQs accordingly",
        history=[
            system_message(MCQ_PER_CONCEPT_SYSTEM_PROMPT.format(n_questions=min(len(concept.facts), 2))),
            user_message(MCQ_PER_CONCEPT_USER_PROMPT.format(concept_transcript=original_explanation, concept_syllabus=format_concept(concept))),
            assistant_message(f"<mcq_set>\n{json.dumps([mcq.model_dump() for mcq in original_mcqs], indent=2)}\n<mcq_set>")
        ],
        model=LLM.CLAUDE_5_SONNET,
        tag="mcq_set",
        is_json=True
    )

    updated_mcqs = get_approval("mcqs", updated_mcqs, [mcq.model_dump() for mcq in original_mcqs])
    return [MCQ(**mcq) for mcq in updated_mcqs]

def find_substring_indices(main_string, substring, new_substring):
    def replace_dash_with_space(text: str)->str:
        return re.sub(r'[\u2010-\u2015\u2212\u23AF\u23E4\u2500\u2501\u2E3A\u2E3B\uFE58\uFE63\uFF0D-]', ' ', text) 
    def normalize(text:str)->str:
        return re.sub(r'\W+', '', text).lower()
    def remove_break_tags(text:str)->str:
        return re.sub(r'\s+', ' ', re.sub(r'<break\s+time=[\"\'][^\"\']*[\"\']\s*>', '', text))

    words = substring.split()
    first_12 = normalize(remove_break_tags(" ".join(words[:12])))
    last_12 = normalize(remove_break_tags(" ".join(words[-12:])))
    print(last_12)

    main_string_words = main_string.split(" ")
    
    for start_idx, _ in enumerate(main_string_words):
        end_idx = start_idx + 12

        while end_idx<=len(main_string_words):
            current_segment = [w for w in main_string_words[start_idx:end_idx] if "<break" not in w and "\">" not in w]
            # print(len(current_segment), current_segment)
            if len(current_segment) == 12:
                if normalize(" ".join(current_segment)) == first_12:
                    print(f"MATCHED START 12 WORDS: {current_segment}")
                    start_index = start_idx
                elif normalize(" ".join(current_segment))[:len(last_12)] == last_12:
                    end_index = end_idx
                    print(end_index + 1 < len(main_string_words), main_string_words[end_idx], main_string_words[end_idx+1])
                    if end_index + 1 < len(main_string_words) and "<break" in main_string_words[end_idx] and "\">" in main_string_words[end_idx + 1]:
                        end_index += 2
                    print(f"MATCHED END 12 WORDS - {end_index}: {current_segment}")
                # print("MOVING TO NEXT INDEX")
                break
            else:
                end_idx += 1
    
    print(f"Found {start_index}, {end_index}: {main_string_words[start_index:end_index]}")
    leftover = ""
    if "\n" in main_string_words[end_index-1]:
        leftover = "\n" + "\n".join(main_string_words[end_index-1].split('\n')[1:])
    main_string_words[start_index:end_index] = (new_substring+leftover).split(" ")
    return " ".join(main_string_words)

def update_transcript_object(transcript: TranscriptOutput, section_name: str, concept_name: str, paused_concept_transcript: str, updated_concept_transcript: Optional[str] = None, updated_mcqs: Optional[List[MCQ]] = None):
    transcript_copy = deepcopy(transcript)
    
    original_explanation = transcript.lesson_transcript_breakdown.sections[section_name].explanations[concept_name].explanation
    
    transcript_copy.lesson_transcript_paused = find_substring_indices(transcript_copy.lesson_transcript_paused, original_explanation, paused_concept_transcript)
    
    if updated_mcqs is not None:
        transcript_copy.supplementary_content.questions[section_name][concept_name] = updated_mcqs

    if updated_concept_transcript is not None:
        transcript_copy.lesson_transcript = find_substring_indices(transcript_copy.lesson_transcript, original_explanation, updated_concept_transcript)
        
        transcript_copy.lesson_transcript_breakdown.sections[section_name].explanations[concept_name].explanation = updated_concept_transcript

        for ii, _ in enumerate(transcript_copy.supplementary_content.questions[section_name][concept_name]):
            transcript_copy.supplementary_content.questions[section_name][concept_name][ii].transcript = updated_concept_transcript

    return transcript_copy

def update_transcript_with_artifacts(context: Context, artifacts: List[ArtifactImage], transcript_concept: TranscriptConcept):
    updated_artifacts = []
    comments = '\n\nAlso please add the following pauses:'
    original_data = {"transcript": transcript_concept.explanation}
    transcript = transcript_concept.explanation
    for artifact in artifacts:
        print(artifact.name)
        avatar_assets = load_json_from_s3(context.avatar_assets_path)
        overlays = OverlaysData(**load_json_from_s3(context.text_overlays_path))
        _, concept_time = get_asset_time(avatar_assets, original_data['transcript'])
        diagram = next(overlay for overlay in (overlays.diagrams + overlays.text_slides) if overlay.end_time>concept_time and overlay.start_time<concept_time)

        # UPDATE TRANSCRIPT AND ARTIFACT
        transcript, updated_artifact = update_transcript_with_artifact_reference(transcript, diagram.model_dump(), artifact)
        fixed = get_approval("transcript_artifact", {"transcript": transcript, "artifact": updated_artifact.model_dump()}, {**original_data, "artifact": artifact.model_dump()})
        transcript, updated_artifact = fixed['transcript'], ArtifactImage(**fixed['artifact'])
        updated_artifacts.append(updated_artifact)

        # UPDATED PAUSED TRANSCRIPT
        comments += f"\n- A 4.0 seconds between these phrases: {updated_artifact.phrase}" if isinstance(updated_artifact.phrase, tuple) else f"\n- A 2.0 seconds after this phrase: {updated_artifact.phrase}" 
        
        # UPDATE VIDEO PLAN ARTIFACT PHRASES
        video_plan = VideoPlan(**load_json_from_s3(context.video_plan_path)['video_plan'])
        video_plan.update_artifact_image(updated_artifact)
        save_json_to_s3({'video_plan': video_plan.model_dump(), 'qc_iterations': []}, get_edited_path(context.video_plan_path))

    paused_concept_transcript = add_pauses_to_explanation(transcript, transcript_concept.figure_name, comments)

    return transcript, paused_concept_transcript, updated_artifacts

def regenerate_transcript(
    context: Context,
    section_name: str,
    concept_name: str,
    change_request: Union[str, list],
    raw_transcript_needs_update: Optional[bool] = None,
    mcqs_need_update: Optional[bool] = None,
) -> TranscriptOutput:
    transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path))
    video_plan = VideoPlan(**load_json_from_s3(context.video_plan_path)['video_plan'])
    
    # Get the current concept's transcript content
    concept_transcript = transcript.lesson_transcript_breakdown.sections[section_name].explanations[concept_name]
    
    artifacts = []
    if isinstance(change_request, str):
        # Determine if change requires raw transcript or paused transcript updates
        if raw_transcript_needs_update is None:
            raw_transcript_needs_update, _ = determine_change_type("Raw Transcript", change_context=f"Transcript Changes Requested: {change_request}")
            logger.info(f"Change type determined: {raw_transcript_needs_update}")
        
        if raw_transcript_needs_update:    # Update the transcript content
            updated_concept_transcript = update_transcript_content(concept_transcript.explanation, change_request)
            paused_concept_transcript = add_pauses_to_explanation(updated_concept_transcript, concept_transcript.figure_name)

            section_plan = next(section for section in video_plan.sections if section.section_title == section_name)
            concept_plan = next(concept for concept in section_plan.concepts if concept.concept_name == concept_name)
            if mcqs_need_update is None:
                mcqs_need_update, _ = determine_change_type(
                    asset_type = "MCQs", 
                    change_context = f"Original Transcript: {concept_transcript.explanation}\n\nUpdated Transcript: {updated_concept_transcript}\n\nConcept was not changed:\n\n{format_concept(concept_plan)}",
                    asset = [q.model_dump() for q in transcript.supplementary_content.questions[section_name][concept_name]]
                )

            if mcqs_need_update:
                mcqs = update_mcqs_for_concept(
                    concept=concept_plan, 
                    original_mcqs=transcript.supplementary_content.questions[section_name][concept_name], 
                    original_explanation=concept_transcript.explanation, 
                    updated_explanation=updated_concept_transcript
                )
                transcript.supplementary_content.questions[section_name][concept_name] = shuffle_mcqs_options(mcqs)
        
        else:
            paused_concept_transcript = add_pauses_to_explanation(concept_transcript.explanation, concept_transcript.figure_name)
    
    else:
        updated_concept_transcript, paused_concept_transcript, artifacts = update_transcript_with_artifacts(context, change_request, concept_transcript)

    transcript_output = update_transcript_object(transcript, section_name, concept_name, 
        paused_concept_transcript=paused_concept_transcript,
        updated_concept_transcript=updated_concept_transcript if isinstance(change_request, list) or raw_transcript_needs_update else None,
        updated_mcqs=mcqs if mcqs_need_update else None
    ) 
    
    # Save updated transcript
    transcript_output = TranscriptOutput(**get_approval("transcript output", transcript_output.model_dump(), transcript.model_dump()))
    save_json_to_s3(transcript_output.model_dump(), get_edited_path(context.transcripts_path))
    update_intermediate_outputs(f"./intermediate-results.json", "Transcript", {"paused_explanation": paused_concept_transcript, "original_explanation": concept_transcript.explanation, "artifacts": [a.model_dump() for a in artifacts]})
    return paused_concept_transcript, concept_transcript.explanation, artifacts

@wait_approval("AUDIO")
def generate_avatar_audio(context: Context, id: str, text: str, voice_id: str, custom_msg: Optional[str] = None):
    if custom_msg and custom_msg.strip() in elevenlabs_voice_descriptions:
        voice_id = custom_msg.strip()
    print(voice_id)

    if voice_id in ['MALE', 'FEMALE']:
        voices = ['pqHfZKP75CvOlQylNhV4', 'nPczCjzI2devNBz1zQrb', 'iP95p4xoKVk53GoZ742B', 'CwhRBWXzGAHq8TQ4Fs17', 'bIHbv24MWmeRgasZH58o'] if voice_id == 'MALE' else ['Xb7hH8MSUJpSbSDYk0k2', '9BWtsMINqrJLrRacOk9x', 'cgSgspJ2msm6clMCkdW9','pFZP5JQG7iQjIQuC4Bku', 'XrExE9yKIg1WjnnlVkGX', 'SAz9YHcvj6GT2YYXdXww', 'EXAVITQu4vr4xnSDxMaL']

        files = []
        for ii, _id in enumerate(voices):
            file_path = f"./{id} - {ii} - {_id}.mp3"
            timings, _ = synthesize_speech(
                file_path=file_path, text=text,
                s3_media_path=context.media_path, voice=_id, speed=1.0
            )
            files.append(file_path)
        
        final_path = files[int(input("Pick voice").strip())]
        os.rename(final_path, f"./{id}.mp3")

        for file_path in files:
            if file_path != final_path and os.path.exists(file_path):
                os.remove(file_path)

    else:
        file_path = f"/tmp/{id}.mp3"
        timings, _ = synthesize_speech(
            file_path=file_path, text=text,
            s3_media_path=context.media_path, voice=voice_id, speed=1.0
        )

        final_path = f"/tmp/denoised-{id}.mp3" if os.path.exists(f"/tmp/denoised-{id}.mp3") else file_path

        shutil.copy2(final_path, f"./{id}.mp3")

    return timings

def get_asset_time(avatar_assets: dict, original_explanation: str):
    transcript_timings = TranscriptTiming(timings=avatar_assets['lesson_timings'])
    start_index, end_index = match_segment_timings(transcript_timings, original_explanation)
    asset_time = transcript_timings.timings[end_index].start_time
    return (start_index, end_index), asset_time

def regenerate_audio(context: Context, section_name: str, concept_name: str, original_explanation: str, paused_concept_transcript: str)->dict:
    concept_transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path)).lesson_transcript_breakdown.sections[section_name].explanations[concept_name]
    
    avatar_assets = load_json_from_s3(context.avatar_assets_path)

    (start_index, end_index), asset_time = get_asset_time(avatar_assets, original_explanation)
    asset_index, asset = next((ii, AvatarAsset(**asset)) for ii, asset in enumerate(avatar_assets['avatar_assets']) if asset['end_time']>asset_time and asset['start_time']<asset_time)
    # download(asset.src, './tmp.mp3')
    n_figure_appearances = len(list(filter(lambda x: x['avatar_name'] == concept_transcript.figure_name, avatar_assets['avatar_assets'])))
    if asset.image.startswith('https://gen-ai-textbooks-dev.s3.amazonaws.com'):
        s3_portrait_path = context.media_path + "character_images/" + re.search(r'character_images/(.*?)\?X-Amz-Algorithm=', asset.image).group(1)
    else:
        portrait_file = f"{uuid.uuid4()}.png"
        s3_portrait_path = context.media_path + "character_images/" + portrait_file
        save_image(asset.image, f"/tmp/{portrait_file}")
        upload_file_to_s3(f"/tmp/{portrait_file}", s3_portrait_path)
        asset.image = s3_portrait_path
    best_match = find_best_match(concept_transcript.figure_name, CHARACTER_BUNDLE)
    if best_match and best_match in CHARACTER_BUNDLE:
        edited_path = f"{CHARACTER_BUNDLE[best_match][:-5]}-edited.json"
        character_data = load_json_from_s3(edited_path if does_file_exist(edited_path) else CHARACTER_BUNDLE[best_match])
        voice_id = character_data['voiceId']
    else:
        voice_id = find_best_voice(context, concept_transcript.figure_name, asset.prompt)

        if n_figure_appearances > 1:
            print(f"Figure {concept_transcript.figure_name} wasn't in character bundle and appears more than once in the video. Chosen voice is: {voice_id}")
            voice_id = 'MALE' if voice_id in ['pqHfZKP75CvOlQylNhV4', 'nPczCjzI2devNBz1zQrb', 'iP95p4xoKVk53GoZ742B', 'CwhRBWXzGAHq8TQ4Fs17', 'bIHbv24MWmeRgasZH58o'] else 'FEMALE'

    new_id = hash_image_description(paused_concept_transcript)
    asset.timings = generate_avatar_audio(context, new_id, paused_concept_transcript, voice_id)
    asset.src = context.media_path + f"{new_id}.mp3"
    
    upload_file_to_s3(f"./{new_id}.mp3", asset.src)

    audio_time = get_audio_duration(f"./{new_id}.mp3")
    delta_time = audio_time - (asset.end_time - asset.start_time)
    print(audio_time, (asset.end_time, asset.start_time), delta_time)

    asset.avatar_clip = create_avatar(
        create_presigned_url(asset.src),
        create_presigned_url(s3_portrait_path),
        f"/tmp/avatar_assets{new_id}.mp4",
        context.media_path
    )

    os.remove(f"./{new_id}.mp3")
    asset.end_time = round(asset.start_time + audio_time, 3)

    avatar_assets['avatar_assets'][asset_index] = asset.model_dump()
    for ii in range(asset_index+1, len(avatar_assets['avatar_assets'])):
        avatar_assets['avatar_assets'][ii]['start_time'] = round(avatar_assets['avatar_assets'][ii]['start_time'] + delta_time, 3)
        avatar_assets['avatar_assets'][ii]['end_time'] = round(avatar_assets['avatar_assets'][ii]['end_time'] + delta_time, 3)
        if avatar_assets['avatar_assets'][ii]['avatar_display_time'] > 0.1:
            avatar_assets['avatar_assets'][ii]['avatar_display_time'] = round(avatar_assets['avatar_assets'][ii]['avatar_display_time'] + delta_time, 3)

    avatar_assets["lesson_timings"][start_index:end_index+1] = [{"text": t.text, "start_time": round(t.start_time + asset.start_time, 3), "end_time": round(t.end_time + asset.start_time, 3)} for t in asset.timings]
    for ii in range(start_index + len(asset.timings), len(avatar_assets["lesson_timings"])):
        avatar_assets["lesson_timings"][ii]['start_time'] = round(avatar_assets["lesson_timings"][ii]['start_time'] + delta_time, 3)
        avatar_assets["lesson_timings"][ii]['end_time'] = round(avatar_assets["lesson_timings"][ii]['end_time'] + delta_time, 3)
    
    for ii, avatar_asset in enumerate(avatar_assets['avatar_introductions']):
        if avatar_asset['start_time']>asset_time:
            avatar_assets['avatar_introductions'][ii]['start_time'] = round(avatar_asset['start_time'] + delta_time, 3)
            avatar_assets['avatar_introductions'][ii]['end_time'] = round(avatar_asset['end_time'] + delta_time, 3)

    avatar_assets = get_approval("avatar assets", avatar_assets, load_json_from_s3(context.avatar_assets_path.replace('-edited.json', '.json')))
    save_json_to_s3(avatar_assets, get_edited_path(context.avatar_assets_path))

    update_intermediate_outputs(f"./intermediate-results.json", "Avatar Assets", {"concept_time": asset_time, "delta_time": delta_time})

    return avatar_assets, asset_time, delta_time

def remove_timings_info(diagram) -> dict:
    if isinstance(diagram, dict):
        keys_to_remove = []
        for key in diagram:
            if key in ["phrase", "start_time"]:
                keys_to_remove.append(key)
            elif isinstance(diagram[key], (dict, list)):
                diagram[key] = remove_timings_info(diagram[key])
                
        for key in keys_to_remove:
            diagram.pop(key)
            
    elif isinstance(diagram, list):
        for i in range(len(diagram)):
            if isinstance(diagram[i], (dict, list)):
                diagram[i] = remove_timings_info(diagram[i])
                
    return diagram

@retry(stop=stop_after_attempt(3), wait=wait_none())
def render_diagram(context: Context, diagram: Union[TextSlide, Diagram], diagram_visuals: List[DiagramVisual], concept_transcript: TranscriptConcept, concept_timings: TranscriptTiming):
    # print(concept_timings)
    if isinstance(diagram, TextSlide):
        diagram.visuals = diagram_visuals
        diagram.fill_visual_timings(concept_timings)

        updated_diagram = match_slide_point_timings(diagram, concept_transcript.explanation, concept_timings)

        updated_diagram.visuals = diagram_visuals
        updated_diagram.fill_visual_timings(concept_timings)

        diagram = TextSlide(**get_approval("diagram", updated_diagram.model_dump(), diagram.model_dump()))
        diagram.src = render_text_slide_template(context, diagram)

    else:   
        diagram_model = identify_diagram_timings(
            models[diagram.type.value], remove_timings_info(diagram.model_dump()),
            concept_transcript.explanation, concept_timings, start_time=diagram.start_time,
            custom='- This text is designed for a tree diagram. Some node titles may not appear in the transcript as they represent implicit groupings. Regardless, assign a phrase to each node. Ensure that the phrase appears before its child node phrases and is logically placed when the transcript discusses the relevant subject.\n- Also remember to ensure the phrase begins at the exact starting point of the text for each title node. The end can extend beyond, but the beginning must coincide with the start of the point.\n- To reiterate parent node phrases must precede the child node phrase at all times. This is an absolute requirement.\n- Make sure your JSON response adheres to the Pydantic model of TreeDiagram provided.' if diagram.type==DiagramType.TREE else '', 
        )
        updated_diagram = Diagram(
            type=diagram.type, data=diagram_model, start_index=diagram.start_index, end_index=diagram.end_index,
            start_time=diagram_model.start_time, end_time=concept_timings.timings[-1].end_time,
        )
        updated_diagram.data.visuals = diagram_visuals
        updated_diagram.data.fill_visual_timings(concept_timings)

        diagram = Diagram(**get_approval("diagram", updated_diagram.model_dump(), diagram.model_dump()))
        diagram.src = render_diagram_template(context, diagram)
    
    convert_mov_to_mp4(f"/tmp/{os.path.basename(diagram.src)}")
    if input(f"Diagram {os.path.basename(diagram.src).replace('.mov', '.mp4')} is good?") == 'n':
        raise 
    else:
        os.remove(os.path.basename(diagram.src).replace('.mov', '.mp4'))
    return diagram

def regenerate_text_overlays(context: Context, section_name: str, concept_name: str, concept_time: float, delta_time: float, artifacts: List[ArtifactImage]):
    transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path))
    concept_transcript = transcript.lesson_transcript_breakdown.sections[section_name].explanations[concept_name]

    avatar_assets = load_json_from_s3(context.avatar_assets_path)
    overlays = OverlaysData(**load_json_from_s3(context.text_overlays_path))

    transcript_timings = TranscriptTiming(timings=avatar_assets['lesson_timings'])
    start_index, end_index = match_segment_timings(transcript_timings, concept_transcript.explanation)
    concept_timings = TranscriptTiming(timings=transcript_timings.timings[start_index:end_index+1])

    diagram = next(overlay for overlay in (overlays.diagrams + overlays.text_slides) if overlay.end_time>concept_time and overlay.start_time<concept_time)
    diagram_index = next(ii for ii, overlay in enumerate(overlays.text_slides if isinstance(diagram, TextSlide) else overlays.diagrams) if overlay.end_time>concept_time and overlay.start_time<concept_time)

    diagram_content_needs_change = False #determine_change_type(f"Diamgam", f"change context", diagram.model_dump())

    if diagram_content_needs_change:
        section_plan = next(section for section in VideoPlan(**load_json_from_s3(context.video_plan_path)['video_plan']).sections if section.section_title == section_name)
        concept_plan = next(concept for concept in section_plan.concepts if concept.concept_name == concept_name)
        if isinstance(diagram, TextSlide):

            updated_diagram = process_text_slide_concept({'concept_transcript': concept_transcript.model_dump(), **concept_plan.model_dump()})
            diagram = TextSlide(**get_approval("diagram", updated_diagram.model_dump(), diagram.model_dump()))

        else:
            updated_diagram = process_diagram_concept({'concept_transcript': concept_transcript.model_dump(), 'start_time': diagram.start_time, **concept_plan.model_dump()}, transcript_timings)
            diagram = Diagram(**get_approval("diagram", updated_diagram.model_dump(), diagram.model_dump()))


    diagram_visuals = [DiagramVisual(src=a.src, caption=a.name, fact=a.fact, phrase=a.phrase) for a in artifacts]
    diagram = render_diagram(context, diagram, diagram_visuals, concept_transcript, concept_timings)

    if isinstance(diagram, TextSlide):
        overlays.text_slides[diagram_index] = diagram
    else:
        overlays.diagrams[diagram_index] = diagram

    for ii, slide in enumerate(overlays.text_slides):
        if slide.start_time > (diagram.end_time-delta_time):
            overlays.text_slides[ii].start_time = round(overlays.text_slides[ii].start_time + delta_time, 3) 
            overlays.text_slides[ii].end_time = round(overlays.text_slides[ii].end_time + delta_time, 3) 
            
    for ii, _diagram in enumerate(overlays.diagrams):
        if _diagram.start_time > (diagram.end_time-delta_time):
            overlays.diagrams[ii].start_time = round(overlays.diagrams[ii].start_time + delta_time, 3) 
            overlays.diagrams[ii].data.start_time = round(overlays.diagrams[ii].data.start_time + delta_time, 3) 
            overlays.diagrams[ii].end_time = round(overlays.diagrams[ii].end_time + delta_time, 3) 


    overlays.conclusion_slide.start_time = round(overlays.conclusion_slide.start_time + delta_time, 3) 
    overlays.conclusion_slide.data.start_time = round(overlays.conclusion_slide.data.start_time + delta_time, 3) 
    overlays.conclusion_slide.end_time = round(overlays.conclusion_slide.end_time + delta_time, 3) 

    overlays.video_splits = identify_video_split_times(transcript, transcript_timings)
    overlays.questions = identify_question_timings(transcript, transcript_timings)
    
    overlays = get_approval("overlays", overlays.model_dump(), load_json_from_s3(context.text_overlays_path.replace('-edited.json', '.json')))
    save_json_to_s3(overlays, get_edited_path(context.text_overlays_path))

    update_intermediate_outputs(f"./intermediate-results.json", "Text Overlays", "DONE")

    return overlays

def regenerate_clips(context: Context, concept_time: float, delta_time: float):
    clips = load_json_from_s3(context.clips_path)
    for ii, clip in enumerate(clips['clips']):
        if clip['start_time']>concept_time:
            clips['clips'][ii]['start_time'] = round(clip['start_time'] + delta_time, 3)
            clips['clips'][ii]['end_time'] = round(clip['end_time'] + delta_time, 3)

    # clips = get_approval("clips", clips, load_json_from_s3(context.clips_path.replace('-edited.json', '.json')))
    save_json_to_s3(clips, get_edited_path(context.clips_path))

    update_intermediate_outputs(f"./intermediate-results.json", "Clips", "DONE")
    return clips

def regenerate_render(context: Context):
    output = render_lesson('', '', context.model_dump())
    save_json_to_s3(output, get_edited_path(context.lesson_video_path))

    return output

def regenerate_concept(context: Context, section_name: str, concept_name: str, change_requested: str, do_render: bool = True):
    if os.path.exists(f"./intermediate-results.json"):
        intermediate_results = json.load(open(f"./intermediate-results.json", 'r')).get(context.key, {}).get(section_name, {}).get(concept_name, {})
    else:
        intermediate_results = {}
    
    if "Transcript" in intermediate_results:
        paused_explanation, original_explanation, artifacts = intermediate_results["Transcript"]["paused_explanation"], intermediate_results["Transcript"]["original_explanation"], intermediate_results["Transcript"]["artifacts"]
        artifacts = [ArtifactImage(**a) for a in artifacts]
    else:
        paused_explanation, original_explanation, artifacts = regenerate_transcript(context, section_name, concept_name, change_requested)

    if "Avatar Assets" in intermediate_results:
        concept_time, delta_time = intermediate_results["Avatar Assets"]["concept_time"], intermediate_results["Avatar Assets"]["delta_time"]
    else:
        _, concept_time, delta_time = regenerate_audio(context, section_name, concept_name, original_explanation, paused_explanation)
    
    if "Text Overlays" in intermediate_results:
        pass
    else:
        regenerate_text_overlays(context, section_name, concept_name, concept_time, delta_time, artifacts)

    if "Clips" in intermediate_results:
        pass
    else:
        regenerate_clips(context, concept_time, delta_time)
    
    if do_render:
        regenerate_render(context)


if __name__=="__main__":
    exec_input    = get_execution_input(
        subject = "AP World History - vUnit_3_new", 
        subsection = "Explain how and why various land-based empires developed and expanded from 1450 to 1750."
    )
    context = Context(**prep_content_gen_input(exec_input))
    section_name = "Origins of the Gunpowder Empires"
    concept_name = "Defining Gunpowder Empires"
    regenerate_concept(context, section_name, concept_name, "Simplify the wording for the explanation", False)