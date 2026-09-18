import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import random
from core.types import (
    MCQ, Concept, ConclusionSlideNew, LayerName, LessonMetadata, Section,
    TeachingTechnique, TranscriptConcept, TranscriptLesson, TranscriptOutput,
    TranscriptSection, TranscriptSupplements, VideoPlan, LessonKnowledgeGraph)
from core.log import (
    setup_logging, with_logging_context)
from core.helpers import (
    exception_handler, extract_tag_content, llm_call, print_json, LLMCallOutput, qc_llm_call,
    replace_spaces, retrieve_markdown_element)
from core.stage_constants import \
    get_unit_from_chapter
from prompts import \
    video_planner_prompts
from prompts.prompts import (
    CONCLUSION_SLIDE_BULLETS_SYSTEM_PROMPT,
    CONCLUSION_TRANSCRIPT_SYSTEM_PROMPT, CONCLUSION_TRANSCRIPT_USER_PROMPT,
    EXPLANATION_TECHNIQUE_PER_CONCEPT_SYSTEM_PROMPT,
    EXPLANATION_TECHNIQUE_PER_CONCEPT_USER_PROMPT,
    get_expository_intro_system_prompt,
    GENERATE_EXPOSITORY_INTRODUCTION_USER_PROMPT,
    GENERATE_QUESTION_CONNECTIONS_SYSTEM_PROMPT,
    GENERATE_QUESTION_CONNECTIONS_USER_PROMPT,
    GENERATE_QUESTION_FINAL_SYSTEM_PROMPT, GENERATE_QUESTION_FINAL_USER_PROMPT,
    GENERATE_SECTION_OVERVIEW_SYSTEM_PROMPT,
    GENERATE_SECTION_OVERVIEW_USER_PROMPT, MCQ_PER_CONCEPT_SYSTEM_PROMPT,
    MCQ_PER_CONCEPT_USER_PROMPT, RECAP_PLAN_SYSTEM_PROMPT, RECAP_PLAN_USER_PROMPT,
    SYNTHESIZE_RELATIONSHIPS_SYSTEM_PROMPT, SYNTHESIZE_RELATIONSHIPS_USER_PROMPT,
    get_explanation_base_system_prompt, get_explanation_base_system_prompt, get_explanation_base_user_prompt,
    introduce_historic_figure_sub_prompt, language_guidelines,
    get_lore_cold_open_system_prompt, LORE_COLD_OPEN_USER_PROMPT,
    get_lore_segment_system_prompt, LORE_SEGMENT_USER_PROMPT,
    get_lore_bridge_system_prompt, LORE_BRIDGE_USER_PROMPT,
    get_lore_close_system_prompt, LORE_CLOSE_USER_PROMPT)
from core.parsers import str_2_json
from elevenlabs import HistoryAlignmentResponseModel
from pydantic import BaseModel
from core.context import APVideoContext as Context
from core.clients.openai import (LLM, chat_complete, llm_complete, system_message,
                          user_message, ensure_json)
from core.clients.s3 import load_json_from_s3
from core.clients.speech import add_narration_pauses

logger = logging.getLogger(__name__)
   
format_concept = lambda c: f"Concept: {c.concept_name}.\nConcept Details:\n" + '\n'.join(c.facts) + ""

def shuffle_mcqs_options(mcqs: List[MCQ]) -> List[MCQ]:
    shuffled_mcqs = []
    for mcq in mcqs:
        shuffled_options = mcq.answer_options.copy()
        random.shuffle(shuffled_options)
        option_ids = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
        for i, option in enumerate(shuffled_options):
            option.id = option_ids[i]
        mcq.answer_options = shuffled_options
        shuffled_mcqs.append(mcq)
    return shuffled_mcqs
 
@qc_llm_call("MCQs", "MCQs")
def generate_questions_per_concept(concept: Concept, concept_trancript: str) -> List[MCQ]:
    allow_right_answer_longest = random.random() < 0.25

    history, mcqs = llm_call(
        system_prompt=MCQ_PER_CONCEPT_SYSTEM_PROMPT.format(n_questions=min(len(concept.facts), 2)),
        user_prompt=MCQ_PER_CONCEPT_USER_PROMPT.format(
            concept_transcript=concept_trancript, 
            concept_syllabus=format_concept(concept)
        ),
        model=LLM.CLAUDE_5_OPUS,
        tag="mcq_set",
        is_json=True
    )

    qc_context = f"<transcript>\n{concept_trancript}\n</transcript>"
    if not allow_right_answer_longest:
        violated_mcqs = []
        for i, mcq in enumerate(mcqs, 1):
            correct_option_length = len(next(opt for opt in mcq["answer_options"] if opt["correct"])["answer"])*0.95
            is_longest = all(len(opt["answer"]) < correct_option_length for opt in mcq["answer_options"] if not opt["correct"])
            violated_mcqs.append(str(i)) if is_longest else None
        qc_context += f"\n\nCorrect answer is the longest for MCQs: {', '.join(violated_mcqs)}. Suggest a fix for the MCQ options as you evaluate Answer Length Balance. Do not overextend incorrect answer options, as this would make the correct answer noticeably shorter. Instead, slightly extend exactly {random.choice([1, 2])} of the incorrect options for each invalid MCQ to ensure the correct answer is not the longest." if violated_mcqs else "\n\nSkip evaluation of Answer Length Balance."
    else: 
        qc_context += "\n\nSkip evaluation of Answer Length Balance."

    return LLMCallOutput(content=mcqs, model=LLM.CLAUDE_5_OPUS, history=history, 
                        postprocess = lambda text: [mcq if isinstance(mcq, dict) else ensure_json(mcq) for mcq in json.loads(extract_tag_content('mcq_set', text))],
                        context=qc_context)

def generate_questions(sections: List[Section], transcript_object: TranscriptLesson) -> Dict[str, Dict[str, List[MCQ]]]:
    questions = {}
    for section_name, section in transcript_object.sections.items():
        section_plan = next(section_plan for section_plan in sections if section_plan.section_title==section_name)
        questions[section_plan.section_title] = {}
        for concept_name, explanation in section.explanations.items():
            concept_plan = next(concept_plan for concept_plan in section_plan.concepts if concept_plan.concept_name==concept_name)
            
            mcqs = generate_questions_per_concept(concept_plan, explanation.explanation)
            print_json(mcqs)
            mcqs = [MCQ(**mcq, transcript=explanation.explanation) for mcq in mcqs]
            questions[section_plan.section_title][concept_plan.concept_name] = shuffle_mcqs_options(mcqs)

    return questions

def postprocess_transcripts(introduction_transcript: str, main_transcript: str, conclusion_transcript: str) -> Tuple[str]:
    introduction_transcript = replace_spaces(introduction_transcript)
    main_transcript = replace_spaces(main_transcript)
    conclusion_transcript = replace_spaces(conclusion_transcript)
    return introduction_transcript, main_transcript, conclusion_transcript

def get_transcript_string(lesson_transcript: TranscriptLesson) -> str:
    transcript = f"[Host]: {lesson_transcript.introduction}"
    for ii, (section_title, section) in enumerate(lesson_transcript.sections.items()):
        if section.overview:
            transcript += f"\n\n[Host]: {section.overview}"
        for jj, (concept_title, concept) in enumerate(section.explanations.items()):
            if jj == 0:
                transcript += f"\n\n[Host]: {concept.question}\n\n[{concept.figure_name}]: {concept.explanation}\n\n[Host]: {concept.recap}"
            else:
                transcript += f" {concept.question}\n\n[{concept.figure_name}]: {concept.explanation}\n\n[Host]: {concept.recap}"
    transcript += f"\n\n[Host]: {lesson_transcript.conclusion}"
    return transcript

def choose_concept_explanation_technique(concept: str) -> str:
    # techniques = list(explanation_technique_guidelines.keys())
    
    _, chosen_technique = llm_call(
        system_prompt=EXPLANATION_TECHNIQUE_PER_CONCEPT_SYSTEM_PROMPT,
        user_prompt=EXPLANATION_TECHNIQUE_PER_CONCEPT_USER_PROMPT.format(concept=concept),
        model=LLM.CLAUDE_5_SONNET,
        tag="decision"
    )

    return chosen_technique

def add_transcript_pauses(transcript: str, comment: str = '') -> str:
    """Add deterministic pauses without rewriting any narration."""
    return add_narration_pauses(transcript)

@qc_llm_call('Transcript', 'LESSON INTRODUCTION')
def generate_introduction_transcript(context: Context, video_plan: VideoPlan) -> LLMCallOutput:
    lesson_plan = "\n".join([section.simple_title + "\n  - Concepts: " + 
                             "; ".join([concept.concept_name for concept in section.concepts]) for section in video_plan.sections]
                             )
    
    history, introduction = llm_call(
        system_prompt=get_expository_intro_system_prompt(context.subject, video_plan.included_map),
        user_prompt=GENERATE_EXPOSITORY_INTRODUCTION_USER_PROMPT.format(
            topic=video_plan.simple_title,
            unit=get_unit_from_chapter(context.subject, context.chapter),
            sections=lesson_plan
        ),
        model=LLM.CLAUDE_5_OPUS,
        tag="introduction"
    )
    return LLMCallOutput(content=introduction, model=LLM.CLAUDE_5_SONNET, history=history, 
                         postprocess = lambda text: extract_tag_content('introduction', text))

@qc_llm_call('Transcript', 'SECTION OVERVIEW')
def generate_section_overview(context: Context, video_plan: VideoPlan, sections: List[Section], section_n: int) -> LLMCallOutput:
    previous_sections = "; ".join([section.section_title for section in sections[:section_n]])
    current_section = sections[section_n]

    history, section_overview = llm_call(
        system_prompt=GENERATE_SECTION_OVERVIEW_SYSTEM_PROMPT.format(subject=context.subject),
        user_prompt=GENERATE_SECTION_OVERVIEW_USER_PROMPT.format(
            lesson_title=video_plan.simple_title,
            previous_sections=previous_sections if len(previous_sections) else "None. This is the first section.",
            section_title=current_section.simple_title,
            section_n=section_n + 1,
            concepts="\n".join([" - " + concept.concept_name for concept in current_section.concepts])
        ),
        model=LLM.CLAUDE_5_SONNET,
        tag="section_overview"
    )
    return LLMCallOutput(content=section_overview, model=LLM.CLAUDE_5_SONNET, history=history, 
                        postprocess = lambda text: extract_tag_content('section_overview', text))



def generate_section_conclusions(context: Context, video_plan: VideoPlan, main_transcript: str) -> Dict:
    lesson_plan  = {
        "sections": {
            section.section_title: {
                "concepts": {
                    concept.concept_name: {
                        "concept_details": [concept.concept, *concept.facts]
                    } for concept in section.concepts
                }
            } for section in video_plan.sections
        }
    }

    _, conclusion_bullets = llm_call(
        system_prompt=CONCLUSION_SLIDE_BULLETS_SYSTEM_PROMPT.format(subject=context.subject),
        user_prompt=f"```json\n{json.dumps(lesson_plan, indent=2)}\n```",
        model=LLM.GPT_5,
        is_json=True
    )
    print_json(conclusion_bullets)

    section_conclusions = {}
    for section_title, bullets in conclusion_bullets.items():
        conclusion_info = dict(
            topic=video_plan.lesson_title,
            section=section_title,
            bullets=bullets
        )
        _, conclusion_transcript = llm_call(
            system_prompt=CONCLUSION_TRANSCRIPT_SYSTEM_PROMPT.format(subject=context.subject),
            user_prompt=json.dumps(conclusion_info, indent=2),
            model=LLM.GPT_5,
            tag="conclusion_transcript"
        )
        section_conclusions[section_title] = conclusion_transcript
    print_json(section_conclusions)
    return conclusion_bullets, section_conclusions

@qc_llm_call('Transcript', 'LESSON CONCLUSION')
def generate_lesson_conclusion_transcript(context: Context, video_plan: VideoPlan, conclusion_bullets: dict) -> str:
    history, conclusion_transcript = llm_call(
        system_prompt=CONCLUSION_TRANSCRIPT_SYSTEM_PROMPT.format(subject=context.subject),
        user_prompt=CONCLUSION_TRANSCRIPT_USER_PROMPT.format(title=video_plan.lesson_title, bullets=json.dumps(conclusion_bullets, indent=2)),
        model=LLM.CLAUDE_5_SONNET,
        tag="conclusion_transcript"
    )
    return LLMCallOutput(content=conclusion_transcript, model=LLM.CLAUDE_5_SONNET, history=history, 
                        postprocess = lambda text: extract_tag_content('conclusion_transcript', text))

def generate_lesson_conclusion(context: Context, video_plan: VideoPlan) -> Tuple[ConclusionSlideNew, str]:
    lesson_plan  = {
        video_plan.lesson_title: {
                "sections": {
                    section.section_title: {
                        "section_details": [concept.concept for concept in section.concepts]
                    } for section in video_plan.sections
                } 
            } 
        }
    
    _, conclusion_bullets = llm_call(
        system_prompt=CONCLUSION_SLIDE_BULLETS_SYSTEM_PROMPT.format(subject=context.subject),
        user_prompt=f"There are {len(lesson_plan[video_plan.lesson_title]['sections'])} sections. Ensure that there is only one main-bullet and one sub-bullet for each section, no more.\n```json\n{json.dumps(lesson_plan, indent=2)}\n```",
        model=LLM.CLAUDE_5_SONNET,
        is_json=True
    )

    conclusion_transcript = generate_lesson_conclusion_transcript(context, video_plan, conclusion_bullets)

    slide = ConclusionSlideNew(
        title = list(conclusion_bullets.keys())[0],
        bullets = [
            ConclusionSlideNew.MainBullet(
                text = k,
                sub_points = [ConclusionSlideNew.MainBullet.SubBullet(text=sub_bullet) for sub_bullet in v])
            for k,v in list(conclusion_bullets.values())[0].items()
        ]
    )

    return slide, conclusion_transcript

# @with_logging_context
@qc_llm_call('Transcript', 'CURIOUS QUESTION')
def generate_question(
    context: Context,
    video_plan: VideoPlan,
    previous_recap: str,
    section_n: int,
    concept_n: int,
    is_figure_intro: bool = False
) -> str:
    """
    Step 1: Generate Question
    Two-step approach:
      (a) Identify connections (O1)
      (b) Define final question (Claude)
    """
    concepts = video_plan.sections[section_n].concepts
    concept = concepts[concept_n]
    upcoming_concepts = "\n".join([format_concept(c) for c in concepts[concept_n+1:]])

    history, connections_response = llm_call(
        system_prompt=GENERATE_QUESTION_CONNECTIONS_SYSTEM_PROMPT.format(language_guidelines=language_guidelines),
        user_prompt=GENERATE_QUESTION_CONNECTIONS_USER_PROMPT.format(
            previous_concept=format_concept(concepts[concept_n-1]) if concept_n>0 else f"Since this is the first concept in the lesson and the previous concept is undefined, you can formulate a question connected to the topic itself. This could be a question that provides context or requests more information on a specific part of the title.\n\nIf the title doesn't seem to be a good fit, you can also establish a connection with the historical figure - {concept.figure_name}, who will be answering the question. This connection could relate to the figure's experiences, knowledge, or expertise.\n\nTry both approaches: connecting to the topic and the figure himself. Remember, whatever you choose, you need to satisfy these three goals: The question extends naturally from already established information, the new concept and underlying details serve as a natural answer to the question even in their raw form, and the question doesn't get ahead of ourselves in trying to answer the topic objective.",
            course_concepts="\n".join([format_concept(c) for c in concepts[:concept_n-1]]) if concept_n>1 else "",
            topic=context.subsection,
            concept=format_concept(concept)
        ),
        model=LLM.GPT_5,
        tag="best_connection"
    )

    history, paragraph = llm_call(
        system_prompt=GENERATE_QUESTION_FINAL_SYSTEM_PROMPT,
        user_prompt=GENERATE_QUESTION_FINAL_USER_PROMPT.format(
            last_words=previous_recap,
            upcoming_concepts=upcoming_concepts,
            figure_name=concept.figure_name,
            historic_figure_intro=introduce_historic_figure_sub_prompt.format(figure_name=concept.figure_name, upcoming_concepts=upcoming_concepts) if is_figure_intro else "",
            historic_figure_part="\n  - Character introduction (1 sentence)" if is_figure_intro else "",
        ),
        model=LLM.CLAUDE_5_SONNET,
        history=history
    )

    is_figure_reintro = not is_figure_intro and ((concept_n>0 and concepts[concept_n-1].figure_name != concept.figure_name) or (concept_n==0 and section_n>0))
    # print("Is figure reintro", concept.concept_name, concept.figure_name, is_figure_reintro)
    context = "The question doesn't require the historical figure's name to be mentioned, so disregard the 'Referring to the historical figure' quality criteria, marking it as a PASS."
    if is_figure_reintro:
        context = f"The question must directly address the historical figure. The figure answering the question is {concept.figure_name}. If the question doesn't mention {concept.figure_name} by name, correctly mark the 'Referring to the historical figure' quality criteria as a FAIL."

    postprocessor = lambda text: (lambda s: (' '.join(s[:-1]), s[-1] if s else ''))(re.split( r'(?<!\b(?:Dr|Mr)\.)(?<=[.!?])\s+', extract_tag_content("paragraph", text)))

    return LLMCallOutput(content=postprocessor(paragraph), model=LLM.CLAUDE_5_SONNET, history=history, postprocess=postprocessor, context=context)

@qc_llm_call('Transcript', 'CONCEPT EXPLANATION')
def generate_explanation(
    context: Context,
    knowledge_graph: LessonKnowledgeGraph,
    video_plan: VideoPlan,
    section_n: int,
    concept_n: int,
    question: str
) -> str:
    """
    Step 2: Generate Explanation
    Two-step approach to produce base explanation (O1) then rewritten version (Claude).
    """
    sections = video_plan.sections
    concept = sections[section_n].concepts[concept_n]
    formatted_concept = f"Concept: {concept.concept_name}.\nConcept Details:\n" + "\n".join(
        fact if knowledge_graph.find_xu_fact(fact) is None else fact + " (CROSS UNIT DETAIL)" for fact in concept.facts
    )

    previous_concepts = "\n".join([format_concept(concept) for section in sections[:section_n] for concept in section.concepts ] + [format_concept(prev_concept) for prev_concept in sections[section_n].concepts[:concept_n]])
    
    # Get relationships for this concept
    current_concept_relationships = video_plan.get_current_concept_relationships(concept)
    prior_concepts_relationships, prior_lessons_relationships = video_plan.get_prior_relationships(concept)

    relationships = ""
    if current_concept_relationships + prior_concepts_relationships + prior_lessons_relationships:
        _, relationships = llm_call(
            system_prompt=SYNTHESIZE_RELATIONSHIPS_SYSTEM_PROMPT,
            user_prompt=SYNTHESIZE_RELATIONSHIPS_USER_PROMPT.format(
                concept_syllabus=formatted_concept,
                related_concepts=json.dumps([r.model_dump() for r in current_concept_relationships + prior_concepts_relationships] + 
                                            [{**r.model_dump(), 'intra_unit': True} for r in prior_lessons_relationships], indent=2),
                intra_unit_concepts=f"\nIf a concept has its field \"intra_unit\" set to True, add the marker \"(INTRA UNIT)\" at the end of the relationship statement, just before the period.\n" if prior_lessons_relationships else ""
            ),
            tag="relationship_statement",
            model=LLM.CLAUDE_5_SONNET
        )
    else:
        logger.warning(f"No relationships found for concept {concept.concept_name}")

    history, explanations = llm_call(
        system_prompt=get_explanation_base_system_prompt(
            subject=context.subject,
            figure_name=concept.figure_name,
            concept_title=concept.concept_name,
            concept=relationships if relationships else formatted_concept,
            explanation_techniques=[technique.choice.value for technique in concept.teaching_techniques],
            relationships=relationships
        ),
        user_prompt=get_explanation_base_user_prompt(
            topic=context.subsection,
            previous_concepts=previous_concepts,
            upcoming_concepts="\n".join([format_concept(upcoming_concept) for upcoming_concept in sections[section_n].concepts[concept_n+1:]]),
            question=question,
            concept=relationships if relationships else formatted_concept,
            teaching_techniques=concept.teaching_techniques,
            ask_question=concept.includes_question
        ),
        tag="answer",
        model=LLM.GPT_5
    )

    syllabus = f"Concept: {concept.concept_name}.\nConcept Details:\n  - " + "\n  - ".join(concept.facts)
    context = f"The syllabus for this concept is provided below, verify that the transcript fully covers all the details mentioned in the syllabus:\n<syllabus>\n{syllabus}\n</syllabus>"
    return LLMCallOutput(content=explanations, model=LLM.GPT_5, history=history, context=context,
                        postprocess = lambda text: extract_tag_content('answer', text))

# @with_logging_context
def generate_recap(
    context: Context,
    concept: str,
    explanation: str
) -> str:
    """
    Step 3: Generate Recap
    Two-step approach to plan recap (O1) then finalize recap (Claude).
    """
    _, recap = llm_call(
        system_prompt=RECAP_PLAN_SYSTEM_PROMPT.format(language_guidelines=language_guidelines),
        user_prompt=RECAP_PLAN_USER_PROMPT.format(
            concept=concept,
            concept_explanation=explanation
        ),
        tag="recap",
        model=LLM.GPT_5
    )

    return recap.strip()

# @with_logging_context
def generate_main_transcript(
    context: Context,
    knowledge_graph: LessonKnowledgeGraph,
    video_plan: VideoPlan,
    section_n: int,
    last_words = ""
) -> Dict[str, TranscriptConcept]:
    """
    For every concept:
      1) Generate Question
      2) Generate Explanation
      3) Generate Recap
    Return consolidated transcript data.
    """
    transcript_data = {}
    section_overview = ""
    previous_recap = last_words

    section = video_plan.sections[section_n]
    for ii, concept in enumerate(section.concepts):
        # Check if avatar appeared previously in this or past sections
        is_figure_intro = not any(
            c.figure_name == concept.figure_name 
            for c in [
                *[pc for s in video_plan.sections[:section_n] for pc in s.concepts],
                *section.concepts[:ii]
            ]
        )

        logger.info(f"Generating question for concept {ii}")
        recap, question = generate_question(
            context=context,
            video_plan=video_plan,
            section_n=section_n,
            concept_n=ii,
            previous_recap=previous_recap,
            is_figure_intro=is_figure_intro
        )
        if ii!= 0:
            transcript_data[section.concepts[ii-1].concept_name].recap = recap
        else:
            section_overview = recap
        # question = "I hear Buddhism branched out into many schools, can you tell me about them?"
        logger.debug(f"Recap: {recap}, Question: {question}")

        logger.info(f"Generating explanation for concept {ii}")
        explanation = generate_explanation(
            context=context,
            knowledge_graph=knowledge_graph,
            video_plan=video_plan,
            section_n=section_n,
            concept_n=ii,
            question=question
        )
        logger.debug(f"Explanation: {explanation}")

        logger.info(f"Generating recap for concept {ii}")
        recap = generate_recap(
            context=context,
            concept=concept.concept_name,
            explanation=explanation
        )

        logger.debug(f"Recap: {recap}")
        transcript_data[concept.concept_name] = TranscriptConcept(
            question=question,
            explanation=explanation,
            recap=recap,
            figure_name=concept.figure_name,
            concept=concept.concept
        )

        previous_recap = recap

    return section_overview, transcript_data

# ==================== LORE / SLEEP NARRATION ================================================

def _tail_words(text: str, n: int = 600) -> str:
    words = text.split()
    return " ".join(words[-n:])


def generate_lore_cold_open(context: Context, video_plan: VideoPlan, target_minutes: int) -> str:
    sections_summary = "\n".join(
        f"- {section.simple_title}: " + "; ".join(c.concept_name for c in section.concepts)
        for section in video_plan.sections
    )
    _, response = llm_call(
        system_prompt=get_lore_cold_open_system_prompt(context.subject, target_minutes),
        user_prompt=LORE_COLD_OPEN_USER_PROMPT.format(
            topic=video_plan.simple_title,
            sections=sections_summary
        ),
        model=LLM.CLAUDE_5_OPUS,
        tag="cold_open"
    )
    return response.strip()


def generate_lore_segment(
    context: Context,
    topic: str,
    concept,
    narrative_so_far: str,
    upcoming_note: str,
    progress_pct: int
) -> str:
    _, response = llm_call(
        system_prompt=get_lore_segment_system_prompt(progress_pct),
        user_prompt=LORE_SEGMENT_USER_PROMPT.format(
            topic=topic,
            narrative_so_far=narrative_so_far or "This is the very beginning of the story.",
            concept=format_concept(concept),
            upcoming=upcoming_note
        ),
        model=LLM.CLAUDE_5_OPUS,
        tag="segment"
    )
    return response.strip()


def generate_lore_bridge(previous_ending: str, next_opening_note: str) -> str:
    _, response = llm_call(
        system_prompt=get_lore_bridge_system_prompt(),
        user_prompt=LORE_BRIDGE_USER_PROMPT.format(
            previous_ending=previous_ending,
            next_opening_note=next_opening_note
        ),
        model=LLM.CLAUDE_5_SONNET,
        tag="bridge"
    )
    return response.strip()


def generate_lore_close(topic: str, opening_note: str, narrative_so_far: str, target_words: int) -> str:
    _, response = llm_call(
        system_prompt=get_lore_close_system_prompt(target_words),
        user_prompt=LORE_CLOSE_USER_PROMPT.format(
            topic=topic,
            opening_note=opening_note,
            narrative_so_far=narrative_so_far
        ),
        model=LLM.CLAUDE_5_OPUS,
        tag="close"
    )
    return response.strip()


def get_lore_transcript_string(lesson_transcript: TranscriptLesson) -> str:
    blocks = [lesson_transcript.introduction]
    for section in lesson_transcript.sections.values():
        if section.overview:
            blocks.append(section.overview)
        for concept in section.explanations.values():
            if concept.question:
                blocks.append(concept.question)
            blocks.append(concept.explanation)
            if concept.recap:
                blocks.append(concept.recap)
    if lesson_transcript.conclusion:
        blocks.append(lesson_transcript.conclusion)
    return "\n\n".join(f"[Host]: {block}" for block in blocks if block)


def generate_lore_lesson_transcript(
    context: Context,
    video_plan: VideoPlan,
    narration_params: Dict[str, Any]
) -> Dict[str, Any]:
    """Single-host 'sleep lore' narration: one continuous story, no Q&A, no MCQs, built to run 60+ min."""
    target_minutes = narration_params.get("target_minutes", 60)
    wpm = narration_params.get("words_per_minute", 135)
    total_words = target_minutes * wpm

    concepts = [(section, concept) for section in video_plan.sections for concept in section.concepts]
    n = len(concepts)
    if n == 0:
        raise ValueError("Lore narration needs at least one concept in the video plan")

    cold_open_words = min(450, max(250, round(total_words * 0.05)))
    close_words = min(300, max(150, round(total_words * 0.04)))
    bridge_words_total = max(0, n - 1) * 60
    segment_words = max(150, round(
        max(total_words - cold_open_words - close_words - bridge_words_total, n * 150) / n
    ))

    logger.info(f"Lore narration: {n} concepts, ~{segment_words} words each, target {total_words} total")

    logger.info("Generating lore cold open")
    cold_open = generate_lore_cold_open(context, video_plan, target_minutes)

    lesson_transcript = TranscriptLesson(introduction=cold_open, sections={}, conclusion='')
    narrative_so_far = cold_open
    opening_note = cold_open[:800]

    concept_global_index = 0
    for section_index, section in enumerate(video_plan.sections):
        section_overview = ""
        if section_index > 0:
            next_concept = section.concepts[0]
            logger.info(f"Generating lore bridge into section {section_index}")
            section_overview = generate_lore_bridge(
                previous_ending=_tail_words(narrative_so_far, 150),
                next_opening_note=f"{section.simple_title}: {format_concept(next_concept)}"
            )
            narrative_so_far += "\n\n" + section_overview

        explanations: Dict[str, TranscriptConcept] = {}
        for local_index, concept in enumerate(section.concepts):
            progress_pct = round(100 * concept_global_index / max(1, n - 1)) if n > 1 else 0
            next_global = concept_global_index + 1
            upcoming_note = (format_concept(concepts[next_global][1]) if next_global < n
                            else "This is the final substory; the piece closes after it.")

            logger.info(f"Generating lore segment {concept_global_index + 1}/{n}: {concept.concept_name}")
            segment = generate_lore_segment(
                context=context,
                topic=video_plan.simple_title,
                concept=concept,
                narrative_so_far=_tail_words(narrative_so_far),
                upcoming_note=upcoming_note,
                progress_pct=progress_pct
            )
            narrative_so_far += "\n\n" + segment

            bridge = ""
            is_last_in_section = local_index == len(section.concepts) - 1
            is_last_overall = concept_global_index == n - 1
            if not is_last_overall and not is_last_in_section:
                next_concept = section.concepts[local_index + 1]
                logger.info(f"Generating lore bridge after segment {concept_global_index + 1}")
                bridge = generate_lore_bridge(
                    previous_ending=_tail_words(segment, 150),
                    next_opening_note=format_concept(next_concept)
                )
                narrative_so_far += "\n\n" + bridge

            explanations[concept.concept_name] = TranscriptConcept(
                concept=concept.concept,
                question="",
                explanation=segment,
                recap=bridge,
                figure_name="Host"
            )
            concept_global_index += 1

        lesson_transcript.sections[section.section_title] = TranscriptSection(
            overview=section_overview,
            explanations=explanations,
            conclusion=''
        )

    logger.info("Generating lore closing passage")
    lesson_transcript.conclusion = generate_lore_close(
        topic=video_plan.simple_title,
        opening_note=opening_note,
        narrative_so_far=_tail_words(narrative_so_far, 500),
        target_words=close_words
    )

    transcript_string = get_lore_transcript_string(lesson_transcript)
    paused_transcript = add_transcript_pauses(transcript_string)
    logger.info("Lore transcript generated.")
    return TranscriptOutput(
        lesson_transcript=transcript_string,
        lesson_transcript_paused=paused_transcript,
        lesson_transcript_breakdown=lesson_transcript,
        supplementary_content=None
    ).model_dump()


# ==================== LESSON TRANSCRIPT (exam-prep Q&A style) ==================================

@with_logging_context(layer=LayerName.TRANSCRIPT)
@exception_handler
def generate_lesson_transcript(output_path: str, output_type: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(f"Generating Iterative Lesson Transcript")
    context = Context(**inputs)
    video_plan = VideoPlan(**load_json_from_s3(context.video_plan_path)['video_plan'])

    narration_params = inputs.get("NARRATION_PARAMS", {})
    if narration_params.get("style") == "lore_sleep":
        return generate_lore_lesson_transcript(context, video_plan, narration_params)

    knowledge_graph = LessonKnowledgeGraph(**load_json_from_s3(context.kg_path))

    logger.info("Generating introduction transcript")
    introduction_transcript = generate_introduction_transcript(context, video_plan)
    logger.debug(f"Introduction transcript: {introduction_transcript}")

    lesson_transcript = TranscriptLesson(
        introduction=introduction_transcript,
        sections={},
        conclusion=''
    )

    for ii, section in enumerate(video_plan.sections):
        if len(video_plan.sections)>1:
            logger.info(f"Generating section overview for section {ii}")
            section_overview = generate_section_overview(context, video_plan, video_plan.sections, ii)
        else:
            section_overview = introduction_transcript
        logger.debug(f"Section overview: {section_overview}")
        logger.info(f"Generating main transcript for section {ii}")
        section_overview, main_transcript = generate_main_transcript(context, knowledge_graph, video_plan, ii, section_overview)

        lesson_transcript.sections[section.section_title] = TranscriptSection(
            overview=section_overview if len(video_plan.sections)>1 else '',
            explanations=main_transcript,
            conclusion=''
        )

        if len(video_plan.sections)==1:
            lesson_transcript.introduction = section_overview
    
    lesson_transcript.conclusion_slide, lesson_transcript.conclusion = generate_lesson_conclusion(context, video_plan)

    logger.info("Generating assessment questions")
    questions = generate_questions(video_plan.sections, lesson_transcript)

    transcript_string = get_transcript_string(lesson_transcript)
    logger.info("Adding pauses to transcript")
    paused_transcript = add_transcript_pauses(transcript_string)
    logger.info("Transcript generated.")

    return TranscriptOutput(
        lesson_transcript=transcript_string,
        lesson_transcript_paused=paused_transcript,
        lesson_transcript_breakdown=lesson_transcript,
        supplementary_content=TranscriptSupplements(questions=questions)
    ).model_dump()


if __name__ == '__main__':
    from core.context import prep_content_gen_input, get_lesson_context
    from config.courses import get_execution_input
    setup_logging(level=logging.DEBUG)
    exec_input    = get_execution_input(
        subject = "AP World History - v6", 
        subsection = "Explain the systems of government employed by Chinese dynasties and how they developed over time."
    )
    context = Context(**prep_content_gen_input(exec_input))

    print(generate_lesson_transcript('', '', context.model_dump())['lesson_transcript'])

    transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path))
    video_plan = VideoPlan(**load_json_from_s3(context.video_plan_path)['video_plan'])
    transcript.supplementary_content.questions = generate_questions(video_plan.sections, transcript.lesson_transcript_breakdown)
    print(transcript.supplementary_content.questions)
    print_json(transcript.model_dump()['supplementary_content']['questions'])
