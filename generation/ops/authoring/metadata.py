import json
import logging
from typing import List, Tuple

from core.helpers import extract_tag_content, print_json
from core.log import setup_logging
from core.clients.s3 import does_file_exist, load_json_from_s3, save_json_to_s3
from prompts.metadata_promptss import KEY_CONCEPTS_TITLE_GENERATION_SYSTEM_PROMPT, get_lesson_title_prompt, get_perspective_guidance_prompt,get_key_phrases_comprehensiveness_check_prompt, get_key_phrases_distinctness_check_prompt, get_key_phrases_prompt, get_key_phrases_qc_prompt, get_key_phrases_relevancy_and_terms_check_prompt, get_key_phrases_specificity_check_prompt, get_key_concepts_generation_system_prompt, get_key_concepts_qc_system_prompt
from core.context import APVideoContext as Context
from core.clients.openai import chat_complete, ensure_json, llm_complete, system_message, user_message
from core.typess import Feedback, KeyConcept, LessonContextPack, LessonMetadata
from core.stage_constantss import NUMBER_OF_QC_ITERATIONS

from core.logger import Logger
# logger = Logger("MetadataGenerator", logging.DEBUG)
logger = logging.getLogger(__name__)

from core.clients.openai import LLM


METADATA_MODEL = LLM.O1_PREVIEW


def generate_key_concepts(context: Context, lesson_title: str, boundaries_and_purpose: str, content_plan: dict, lesson_context_pack: LessonContextPack) -> Tuple[List[KeyConcept], List[Feedback]]:
    feedback_list: List[Feedback] = []
    key_concepts = []
    for iteration in range(NUMBER_OF_QC_ITERATIONS+1):
        logger.info(f"Iteration: {iteration}")
        messages = [
            {"role": "user", "content": get_key_concepts_generation_system_prompt(context, content_plan, lesson_context_pack.transcript_pack, lesson_title, boundaries_and_purpose)}
        ]
        for feedback in feedback_list:
            messages.append({"role": "assistant", "content": feedback.output})
            messages.append({"role": "user", "content": feedback.feedback})
            messages.append({
                "role": "user",
                "content": "Incorporate the above feedback and only include the key concepts in your response and nothing else."
            })
        logger.info("Generating key concepts")
        key_concepts_str = chat_complete(messages, model=METADATA_MODEL)
        key_concepts_dict = ensure_json(key_concepts_str) # type: ignore

        key_concepts = [
            KeyConcept(title=title, learning_objectives=objectives)
            for title, objectives in key_concepts_dict.items() # type: ignore
        ]

        logger.info(f"Generated key concepts for {lesson_title}")

        # QC the key concepts
        messages = [
            {"role": "user", "content": get_key_concepts_qc_system_prompt(context, content_plan, key_concepts, lesson_context_pack.transcript_pack)}
        ]
        logger.info("Sending key concepts to QC")
        qc_result = ensure_json(chat_complete(messages, model=METADATA_MODEL)) # type: ignore
        qc_pass = qc_result.get('qc_pass', False) # type: ignore
        if qc_pass:
            logger.info("Key concepts QC passed")
            break
        logger.info(f"Key concepts QC failed with feedback: {qc_result.get('feedback', '')}") # type: ignore
        feedback_list.append(Feedback(
            feedback=qc_result.get('feedback', ''), # type: ignore
            output=str(key_concepts_str)
        ))

    return key_concepts, feedback_list


def get_key_concepts_by_l3(context: Context, content_plan: dict) -> Tuple[List[KeyConcept], List[Feedback]]:
    key_concepts = []
    for l3_title, standards in content_plan.items():
        learning_objectives = []
        for standard, objectives in standards.items():
            learning_objectives.extend(objectives)
        key_concept = KeyConcept(
            title=l3_title,
            learning_objectives=learning_objectives
        )
        key_concepts.append(key_concept)

    messages = [
        system_message(KEY_CONCEPTS_TITLE_GENERATION_SYSTEM_PROMPT),
        user_message(f"Suggest {len(key_concepts)} titles for these {len(key_concepts)} L3s\n```json\n{json.dumps([c.dict() for c in key_concepts], indent=2)}\n```")
    ]
    titles = ensure_json(extract_tag_content('titles', llm_complete(messages, LLM.ANTHROPIC_CLAUDE_3_5_SONNET)))['titles'] # type: ignore

    key_concepts = [KeyConcept(**{**concept.dict(), 'title':title}) for title, concept in zip(titles, key_concepts)]

    print_json([c.dict() for c in key_concepts]) # type: ignore
    return key_concepts, []


def generate_key_phrases(context: Context, lesson_metadata: LessonMetadata, lesson_context_pack: LessonContextPack) -> Tuple[LessonMetadata, List[Feedback]]:

    key_phrase_feedback_list: List[Feedback] = []
    for iteration in range(NUMBER_OF_QC_ITERATIONS+1):
        logger.info(f"Key phrases iteration: {iteration}")
        messages = [
            {"role": "user", "content": get_key_phrases_prompt(context, lesson_metadata, lesson_context_pack)}
        ]
        for feedback in key_phrase_feedback_list:
            messages.append({"role": "assistant", "content": feedback.output})
            messages.append({"role": "user", "content": feedback.feedback})
            messages.append({
                "role": "user",
                "content": "Incorporate the above feedback and only include the required json in your response and nothing else."
            })
        logger.info("Generating key phrases")
        key_phrases_str = chat_complete(messages, model=METADATA_MODEL)
        key_phrases_dict = ensure_json(key_phrases_str) # type: ignore

        # Update key_phrases for each key concept
        for kc in lesson_metadata.key_concepts:
            if kc.title in key_phrases_dict:
                kc.key_phrases = key_phrases_dict[kc.title] # type: ignore
            else:
                # Print all the titles of key concepts in lesson metadata
                logger.info("Key Concept Titles:")
                for concept in lesson_metadata.key_concepts:
                    logger.info(f"{concept.title}")
                # Print all the keys of key_phrases_dict
                logger.info("Keys in key_phrases_dict:")
                for key in key_phrases_dict.keys(): # type: ignore
                    logger.info(f"{key}")
                logger.error(f"Key phrases not found for key concept: {kc.title}")
                raise Exception(f"Key phrases not found for key concept: {kc.title}")

        # Perform distinctness check
        distinctness_check_prompt = get_key_phrases_distinctness_check_prompt(context.subject, lesson_metadata)
        distinctness_check_result = ensure_json(chat_complete([{"role": "user", "content": distinctness_check_prompt}], model=METADATA_MODEL)) # type: ignore

        # Perform specificity check
        specificity_check_prompt = get_key_phrases_specificity_check_prompt(context.subject, context.chapter, lesson_metadata)
        specificity_check_result = ensure_json(chat_complete([{"role": "user", "content": specificity_check_prompt}], model=METADATA_MODEL)) # type: ignore

        # Perform relevancy and explained terms check
        relevancy_and_terms_check_prompt = get_key_phrases_relevancy_and_terms_check_prompt(context.subject, context.chapter, lesson_metadata)
        relevancy_and_terms_check_result = ensure_json(chat_complete([{"role": "user", "content": relevancy_and_terms_check_prompt}], model=METADATA_MODEL)) # type: ignore

        # Perform comprehensiveness check
        comprehensiveness_check_prompt = get_key_phrases_comprehensiveness_check_prompt(context.subject, lesson_metadata)
        comprehensiveness_check_result = ensure_json(chat_complete([{"role": "user", "content": comprehensiveness_check_prompt}], model=METADATA_MODEL)) # type: ignore
        # QC the key phrases
        messages = [
            {"role": "user", "content": get_key_phrases_qc_prompt(
                context,
                lesson_metadata,
                lesson_context_pack,
                json.dumps(distinctness_check_result, indent=2),
                json.dumps(specificity_check_result, indent=2),
                json.dumps(relevancy_and_terms_check_result, indent=2),
                json.dumps(comprehensiveness_check_result, indent=2)
            )}
        ]
        logger.info("Sending key phrases to QC")
        qc_result = ensure_json(chat_complete(messages, model=METADATA_MODEL)) # type: ignore
        qc_pass = qc_result.get('qc_pass', False) # type: ignore
        if qc_pass:
            logger.info("Key phrases QC passed")
            break
        logger.info(f"Key phrases QC failed with feedback: {qc_result.get('feedback', '')}") # type: ignore
        key_phrase_feedback_list.append(Feedback(
            feedback=qc_result.get('feedback', ''), # type: ignore
            output=str(key_phrases_str)
        ))
    return lesson_metadata, key_phrase_feedback_list


def generate_lesson_metadata(context: Context) -> Tuple[LessonMetadata, List[Feedback], List[Feedback]]:
    logger.info(f"Generating lesson metadata for chapter: {context.chapter}, subsection: {context.subsection}")
    # Check if metadata file exists
    if does_file_exist(context.metadata_path):
        logger.info("Loading existing metadata")
        metadata_json = load_json_from_s3(context.metadata_path)
        return LessonMetadata(**(metadata_json['lesson_metadata'])), [Feedback(**item) for item in metadata_json['key_concepts_feedback']], [Feedback(**item) for item in metadata_json['key_phrases_feedback']]

    content_plan = context.content_plan

    # Generate lesson title and boundaries_and_purpose
    messages = [
        {"role": "user", "content": get_lesson_title_prompt(context.subject, context.chapter, context.subsection, content_plan)}
    ]
    lesson_title_response = chat_complete(messages, model=METADATA_MODEL)
    lesson_title_data = ensure_json(lesson_title_response) if lesson_title_response else {}
    lesson_title = lesson_title_data.get('title', '').strip() # type: ignore
    boundaries_and_purpose = lesson_title_data.get('boundaries_and_purpose', '').strip() # type: ignore
    logger.info(f"Generated lesson title: {lesson_title}")
    logger.info(f"Generated boundaries and purpose: {boundaries_and_purpose}")

    # Generate perspective_guidance
    messages = [
        {"role": "user", "content": get_perspective_guidance_prompt(context.subject, lesson_title, context.subsection, context.chapter, content_plan, boundaries_and_purpose)}
    ]
    perspective_guidance_response = chat_complete(messages, model=METADATA_MODEL)
    perspective_guidance_data = ensure_json(perspective_guidance_response) if perspective_guidance_response else {}
    perspective_guidance = perspective_guidance_data.get('perspective_guidance', '').strip() # type: ignore
    logger.info(f"Generated perspective guidance")

    lesson_context_pack = LessonContextPack.from_context(context)

    # Generate key concepts
    if 'AP US History' in context.subject:
        key_concepts, feedback_list = get_key_concepts_by_l3(context, content_plan)
    else:
        key_concepts, feedback_list = generate_key_concepts(
            context, lesson_title, boundaries_and_purpose, content_plan, lesson_context_pack
        )

    lesson_metadata = LessonMetadata(lesson_title=lesson_title, key_concepts=key_concepts, boundaries_and_purpose=boundaries_and_purpose, perspective_guidance=perspective_guidance)

    # Generate key phrases
    lesson_metadata, key_phrase_feedback_list = generate_key_phrases(
        context, lesson_metadata, lesson_context_pack
    )

    logger.info(f"Generated lesson metadata: \n{json.dumps(lesson_metadata.dict(), indent=2)}")

    # Save the generated metadata
    save_json_to_s3({'lesson_metadata': lesson_metadata.dict(),
                     'key_concepts_feedback': [item.model_dump() for item in feedback_list],
                     'key_phrases_feedback': [item.model_dump() for item in key_phrase_feedback_list]},
                    context.metadata_path)
    logger.info(f"Saved lesson metadata to {context.metadata_path}")

    return lesson_metadata, feedback_list, key_phrase_feedback_list

if __name__ == '__main__':
    from core.context import prep_content_gen_input
    from config.courses import get_execution_input
    setup_logging(level=logging.DEBUG)
    exec_input    = get_execution_input(
        subject = "AP World History - v6", 
        subsection = "Explain the systems of government employed by Chinese dynasties and how they developed over time."
    )
    context = Context(**prep_content_gen_input(exec_input))
    # print_json(generate_lesson_metadata('', '', context.dict()))  

    print_json(generate_lesson_metadata(context))   # type: ignore