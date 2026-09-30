import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fuzzywuzzy import fuzz

from core.clients.openai import LLM, ensure_json, llm_complete, system_message, user_message
from core.context import Context
from core.helpers import (LLMCallOutput, exception_handler, extract_tag_content,
                          fuzzy_find_matching_string, llm_call, qc_llm_call)
from core.log import with_logging_context
from core.parsers import str_2_json
from core.types import LayerName, TeachingTechniqueInfo, VideoPlan, Visual
from prompts.video_planner_prompts import (
    FINAL_TOUCHUPS_SYSTEM_PROMPT, FINAL_TOUCHUPS_USER_PROMPT, TEACHING_TECHNIQUE_SYSTEM_PROMPT,
    TEACHING_TECHNIQUE_USER_PROMPT, VIDEO_PLANNER_MISSING_FACTS, VIDEO_PLANNER_SYSTEM_PROMPT,
    VIDEO_PLANNER_USER_PROMPT, VISUAL_ORGANIZER_SYSTEM_PROMPT, VISUAL_ORGANIZER_USER_PROMPT,
    video_planner_history)

logger = logging.getLogger(__name__)

# The planner is told to copy facts verbatim; anything it rephrased past this is treated as dropped.
FACT_MATCH_THRESHOLD = 90


def plan_facts(context: Context) -> List[str]:
    """Every research fact the video's lessons carry, in plan order."""
    return [c.strip() for lesson in context.lessons for c in lesson.get("concepts", []) if c.strip()]


def format_plan_facts(context: Context) -> str:
    return "\n\n".join(
        f"Lesson: {lesson['name']}\n" + "\n".join(f"- {c.strip()}" for c in lesson.get("concepts", []) if c.strip())
        for lesson in context.lessons)


def restore_facts(structure: dict, facts: List[str]) -> Tuple[dict, List[str]]:
    """Put each research fact back verbatim over its closest planned wording; return the ones the plan dropped."""
    planned = [(ii, jj, kk, fact)
               for ii, section in enumerate(structure["sections"])
               for jj, concept in enumerate(section["concepts"])
               for kk, fact in enumerate(concept["facts"])]
    missing = []
    for fact in facts:
        score, ii, jj, kk = max(((fuzz.ratio(fact, text), ii, jj, kk) for ii, jj, kk, text in planned),
                                default=(0, 0, 0, 0))
        if score < FACT_MATCH_THRESHOLD:
            missing.append(fact)
        else:
            structure["sections"][ii]["concepts"][jj]["facts"][kk] = fact
    return structure, missing


def final_touchups(video_plan: VideoPlan) -> VideoPlan:
    messages = [
        system_message(FINAL_TOUCHUPS_SYSTEM_PROMPT),
        user_message(FINAL_TOUCHUPS_USER_PROMPT.format(plan=json.dumps(video_plan.model_dump(), indent=2)))
    ]
    touchup_fields = list(str_2_json(extract_tag_content("json", llm_complete(messages, LLM.CLAUDE_5_SONNET))).values())[0]

    video_plan = video_plan.model_copy(update=touchup_fields['touchup_fields'])
    section_titles = [sec.section_title for sec in video_plan.sections]

    for section_title, v in touchup_fields['sections'].items():
        best_match = fuzzy_find_matching_string(section_title, section_titles)
        idx = next((i for i, d in enumerate(video_plan.sections) if d.section_title == best_match), None)
        video_plan.sections[idx] = video_plan.sections[idx].copy(update=v["touchup_fields"])
    return video_plan


def format_syllabus_grouping(structure: dict, techniques: Optional[dict] = None):
    return "\n\n".join([
        f"Section {ii+1}: {section['section_title']}"
        + "\n"
        + "\n".join([
            f"\tConcept {jj+1}: {concept['concept_name']}"
            + "\n\t\t-"
            + "\n\t\t-".join(concept["facts"])
            + (
                "\n\t\t-Teaching Techniques: \n\t\t\t-"
                + "\n\t\t\t-".join([
                    f"{t['choice']}. {t['suggestion']}"
                    for t in techniques["sections"][ii]["concepts"][jj]["teaching_technique"]
                ])
                if techniques
                and "sections" in techniques
                and len(techniques["sections"]) > ii
                and len(techniques["sections"][ii]["concepts"]) > jj
                and "teaching_technique" in techniques["sections"][ii]["concepts"][jj]
                else ""
            )
            for jj, concept in enumerate(section["concepts"])
        ])
        for ii, section in enumerate(structure["sections"])
    ])


@qc_llm_call("VideoPlan", "SEQUENCING AND GROUPING")
def sequencing_and_grouping(context: Context) -> dict:
    history, structure = llm_call(
        system_prompt="",
        user_prompt=VIDEO_PLANNER_USER_PROMPT.format(title=context.title, facts=format_plan_facts(context)),
        model=LLM.GPT_5,
        history=[system_message(VIDEO_PLANNER_SYSTEM_PROMPT.format(subject=context.subject)), *video_planner_history],
        is_json=True
    )

    structure, missing_facts = restore_facts(structure, plan_facts(context))
    context_message = ""
    if missing_facts:
        logger.error(f"Research facts missing from the Video Plan, running QC: {missing_facts}")
        context_message = VIDEO_PLANNER_MISSING_FACTS.format(missing_facts=json.dumps(missing_facts, indent=2))

    return LLMCallOutput(content=structure, model=LLM.GPT_5, history=history,
                         postprocess=lambda text: ensure_json(text), context=context_message)


@qc_llm_call("VideoPlan", "TEACHING TECHNIQUES")
def plan_teaching_techniques(context: Context, video_plan: VideoPlan) -> dict:
    history, teaching_techniques = llm_call(
        system_prompt=TEACHING_TECHNIQUE_SYSTEM_PROMPT.format(subject=context.subject),
        user_prompt=TEACHING_TECHNIQUE_USER_PROMPT.format(structure=format_syllabus_grouping(video_plan.model_dump())),
        model=LLM.GPT_5,
        is_json=True
    )

    for i, sec in enumerate(video_plan.sections):
        for j, con in enumerate(sec.concepts):
            teaching_techniques["sections"][i]["concepts"][j]["facts"] = con.facts

    return LLMCallOutput(content=teaching_techniques, model=LLM.GPT_5, history=history,
                         postprocess=lambda text: ensure_json(text))


def plan_visual_techniques(context: Context, video_plan: VideoPlan, teaching_techniques: dict,
                           generate_visuals: bool = True) -> VideoPlan:
    """Merge the teaching techniques onto every concept, and unless told otherwise a visual too."""
    if not generate_visuals:
        logger.info("LAYER_PLANNER_VISUAL_TECHNIQUES off: not assigning per-concept visuals")
    visual_organizers = generate_visuals and llm_call(
        system_prompt=VISUAL_ORGANIZER_SYSTEM_PROMPT.format(subject=context.subject),
        user_prompt=VISUAL_ORGANIZER_USER_PROMPT.format(structure=format_syllabus_grouping(video_plan.model_dump(), teaching_techniques)),
        model=LLM.GPT_5,
        is_json=True
    )[1]

    for i, sec in enumerate(video_plan.sections):
        for j, con in enumerate(sec.concepts):
            sec.concepts[j] = con.model_copy(update={
                "teaching_techniques": [TeachingTechniqueInfo(**t) for t in teaching_techniques["sections"][i]["concepts"][j]["teaching_techniques"]],
                **({"visual": Visual(**visual_organizers["sections"][i]["concepts"][j]["visual"])} if generate_visuals else {})
            })

    return video_plan


@with_logging_context(LayerName.PLANNER)
@exception_handler
def generate_lesson_video_plan(output_path: str, output_type: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Stage entry: sequence and group the video's research facts into sections and concepts."""
    logger.info("Generating video plan")
    context = Context(**inputs)
    if not plan_facts(context):
        raise ValueError(f"'{context.title}' has no research concepts in lesson_plan.json")

    structure, _ = restore_facts(sequencing_and_grouping(context), plan_facts(context))
    video_plan = VideoPlan(**structure)

    teaching_techniques = plan_teaching_techniques(context, video_plan)
    video_plan = plan_visual_techniques(context, video_plan, teaching_techniques,
                                        generate_visuals=inputs.get("LAYER_PLANNER_VISUAL_TECHNIQUES", True))
    video_plan = final_touchups(video_plan)

    logger.info("Generated final video plan")
    return {"video_plan": video_plan.model_dump(), "qc_iterations": []}
