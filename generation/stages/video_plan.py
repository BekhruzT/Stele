import json
import logging
import re
from typing import Any, Dict, List, Tuple, Optional

from core.types import (
    ConclusionParts, FactRelationship, FactRelationshipPair,
    FactRelationshipType, Feedback, GenerateTranscriptOutput, KeyConcept, TeachingTechniqueInfo, Visual,
    LayerName, LessonContextPack, LessonKnowledgeGraph, LessonMetadata, TeachingTechnique,
    VideoPlan)
from core.log import (
    setup_logging, with_logging_context)
from core.helpers import (
    exception_handler, extract_tag_content, print_json, llm_call, fuzzy_find_matching_string, LLMCallOutput, qc_llm_call)
from core.stage_constants import \
    NUMBER_OF_QC_ITERATIONS, get_unit_from_chapter
from prompts.video_planner_prompts import (
    FINAL_TOUCHUPS_SYSTEM_PROMPT, FINAL_TOUCHUPS_USER_PROMPT,
    get_historical_figures_prompt,
    get_video_plan_qc_prompt, VIDEO_PLANNER_SYSTEM_PROMPT, VIDEO_PLANNER_USER_PROMPT, video_planner_history, FINAL_TOUCHUPS_SYSTEM_PROMPT, FINAL_TOUCHUPS_USER_PROMPT, TEACHING_TECHNIQUE_USER_PROMPT, TEACHING_TECHNIQUE_SYSTEM_PROMPT, VISUAL_ORGANIZER_SYSTEM_PROMPT, VISUAL_ORGANIZER_USER_PROMPT)
from core.parsers import str_2_json
from core.context import APVideoContext as Context
from core.context import prep_content_gen_input, get_lesson_context
from core.logger import Logger
from core.clients.openai import (LLM, chat_complete, llm_complete, system_message,
                          user_message, ensure_json)
from core.clients.s3 import load_json_from_s3, save_json_to_s3
from core.clients.images import find_lesson_map_from_db

logger = logging.getLogger(__name__)

def process_edges(edges_to_process) -> List[FactRelationshipPair]:
    relationship_pairs = []
    if not edges_to_process:
        return relationship_pairs
    # Map of KGEdge types to FactRelationshipType
    relationship_type_map = {
        "causes": FactRelationshipType.CAUSES,
        "details": FactRelationshipType.DETAILS,
        "enables": FactRelationshipType.ENABLES,
        "influences": FactRelationshipType.INFLUENCES,
        "exemplifies": FactRelationshipType.EXEMPLIFIES,
        "compares": FactRelationshipType.COMPARES
    }
    for edge in edges_to_process:
        # Only convert edges where we can map the relationship type
        if edge.type.lower() in relationship_type_map:
            fact_rel = FactRelationshipPair(
                source_fact=edge.source_statement,
                target_fact=edge.target_statement,
                relationship=FactRelationship(
                    type=relationship_type_map[edge.type.lower()],
                    description=edge.explanation
                )
            )
            relationship_pairs.append(fact_rel)
        else:
            raise ValueError(f'unknown relationship type: {edge.type}')
    return relationship_pairs

def parse_fact_relationships(kg: LessonKnowledgeGraph) -> Dict[str, Any]:
    """Convert KGEdge objects to FactRelationshipPair objects.
    Maps KGEdge relationship types to FactRelationshipType."""
    
    
    
    fact_relationships = process_edges(kg.lo_edges)
    intra_unit_relationships = process_edges(kg.iu_edges)
    
    
    
    
    return {"fact_relationships": [fact_rel.model_dump() for fact_rel in fact_relationships],
            "intra_unit_relationships": [rel.model_dump() for rel in intra_unit_relationships]}

def get_historical_figures(context: Context, video_plan: Dict[str, Any]) -> Dict[str, Any]:
    added_instructions = "\n\n### Constraints\n- Avoid mystical or highly religious figures, such as Jesus Christ, Muhammad, and Buddha."
    if get_unit_from_chapter(context.subject, context.chapter) == "1900-Present CE":
        added_instructions =  "\n- Avoid controversial and notorious historical figures responsible for major tragedies, such as Hitler, Stalin, Pol Pot, Hideki Tojo, Mao Zedong, Fidel Castro, and Osama bin Laden. Avoid such atrocious figures. They must not be picked as the historic figures, as they will repel students."
    messages = [
        user_message(get_historical_figures_prompt(video_plan.model_dump()) + added_instructions)
    ]
    return str_2_json(chat_complete(messages, model=LLM.GPT_5) or '')

def final_touchups(context: Context, video_plan: VideoPlan) -> VideoPlan:
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

    video_plan.included_map = find_lesson_map_from_db(context.subject, context.chapter, context.subsection).get("description", '')
    return video_plan

def format_syllabus_grouping(knowledge_graph: LessonKnowledgeGraph, structure: dict, techniques: Optional[dict] = None):
    return "\n\n".join([
        f"Section {ii+1}: {section['section_title']}"
        + "\n"
        + "\n".join([
            f"\tConcept {jj+1}: {concept['concept_name']}"
            + "\n\t\t-"
            + "\n\t\t-".join([fact+" (DEFINITION)" if knowledge_graph.find_fact(fact).is_definition==True else fact for fact in concept["facts"]])
            # Optionally add teaching techniques from b
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
def sequencing_and_grouping(context: Context, kg: LessonKnowledgeGraph) -> dict:
    facts, l3_facts = kg.format_lo_nodes()
    relationships = kg.format_relationships()
    xu_facts = kg.format_xu_facts()

    history, structure = llm_call(
        system_prompt="",
        user_prompt=VIDEO_PLANNER_USER_PROMPT.format(title=context.subsection, facts=f"{facts}\n\n{xu_facts}", l3_facts=l3_facts, relationships=relationships),
        model=LLM.GPT_5,
        history=[system_message(VIDEO_PLANNER_SYSTEM_PROMPT.format(subject=context.subject)), *video_planner_history],
        is_json=True
    )

    context_message = ""

    structure, missing_facts = kg.correct_kg_facts(structure)
    redundant_facts = kg.find_redundant_facts(structure)

    if missing_facts:
        logger.error(f"Couldn't find KG fact in Video Plan, running QC: {missing_facts}")
        context_message = (
            "Some required facts are missing from the plan. "
            "Please request they be added according to best practices for sequencing and grouping. "
            f"The missing facts are:\n{json.dumps(missing_facts, indent=2)}"
        )

    # if redundant_facts:
    #     context_message = (
    #         "Some included facts do not match the original syllabus. They may have been incorrectly rephrased or added unnecessarily. "
    #         "Please suggest removing these facts and reorganizing the remaining facts if necessary, to ensure continued compliance with sequencing and grouping guidelines."
    #         f"The redundant facts are:\n{json.dumps(redundant_facts, indent=2)}"
    #     )
    
    return LLMCallOutput(content=structure, model=LLM.GPT_5, history=history, 
                         postprocess = lambda text: ensure_json(text), context=context_message)

@qc_llm_call("VideoPlan", "TEACHING TECHNIQUES")
def plan_teaching_techniques(context: Context, knowledge_graph: LessonKnowledgeGraph, video_plan: VideoPlan) -> VideoPlan:
    # Is missing both facts and relationships at qc end.

    history, teaching_techniques = llm_call(
        system_prompt=TEACHING_TECHNIQUE_SYSTEM_PROMPT.format(subject=context.subject),
        user_prompt=TEACHING_TECHNIQUE_USER_PROMPT.format(structure=format_syllabus_grouping(knowledge_graph, video_plan.model_dump())),
        model=LLM.GPT_5,
        is_json=True
    )


    [
        teaching_techniques["sections"][i]["concepts"][j].update({
            "facts": con.facts,
            "relationships": [rel.model_dump() for rel_types in video_plan.get_prior_relationships(con) for rel in rel_types]
        })
        for i, sec in enumerate(video_plan.sections)
        for j, con in enumerate(sec.concepts)
    ]

    return LLMCallOutput(content=teaching_techniques, model=LLM.GPT_5, history=history, 
                         postprocess = lambda text: ensure_json(text))

# @qc_llm_call("VideoPlan", "VISUAL TECHNIQUES")
def plan_visual_techniques(context: Context, knowledge_graph: LessonKnowledgeGraph, video_plan: VideoPlan, teaching_techniques: dict, generate_visuals: bool = True) -> VideoPlan:
    """Merge the teaching techniques onto every concept, and unless told otherwise a visual too."""
    if not generate_visuals:
        logger.info("LAYER_PLANNER_VISUAL_TECHNIQUES off: not assigning per-concept visuals")
    visual_organizers = generate_visuals and llm_call(
        system_prompt=VISUAL_ORGANIZER_SYSTEM_PROMPT.format(subject=context.subject),
        user_prompt=VISUAL_ORGANIZER_USER_PROMPT.format(structure=format_syllabus_grouping(knowledge_graph, video_plan.model_dump(), teaching_techniques)),
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
    logger.info("Generating video plan")
    context = Context(**inputs)
    KGinput = LessonKnowledgeGraph(**load_json_from_s3(context.kg_path))
    
    feedback_list: List[Feedback] = []
    video_plan = None

    structure = sequencing_and_grouping(context, KGinput)
    structure, _ = KGinput.correct_kg_facts(structure)
    video_plan = VideoPlan(**structure, **parse_fact_relationships(KGinput))

    teaching_techniques = plan_teaching_techniques(context, KGinput, video_plan)
    video_plan = plan_visual_techniques(context, KGinput, video_plan, teaching_techniques,
                                        generate_visuals=inputs.get("LAYER_PLANNER_VISUAL_TECHNIQUES", True))

    # Third call: Get historical figures for each section
    logger.info("Getting historical figures")
    historical_figures = get_historical_figures(context, video_plan)
    logger.info("Got historical figures")   


    # Add historical figures to each section and concepts
    for section in video_plan.sections:
        section_title = section.section_title
        if section_title in historical_figures["historical_figures"]:
            # Only store figure names for the section
            section.historical_figures = [
                figure["name"] 
                for figure in historical_figures["historical_figures"][section_title]
            ]
            # Create a mapping of concept names to their assigned figure names
            concept_to_figure = {}
            for figure in historical_figures["historical_figures"][section_title]:
                for assigned_concept in figure.get("assigned_concepts", []):
                    concept_to_figure[assigned_concept["concept_name"]] = figure["name"]
            # Add figure assignments to each concept (name only)
            for concept in section.concepts:
                if concept.concept_name in concept_to_figure:
                    concept.figure_name = concept_to_figure[concept.concept_name]

    video_plan = final_touchups(context, video_plan)
    
    logger.info(f"Generated final video plan")
    return {
        "video_plan": video_plan.model_dump(),
        "qc_iterations": [feedback.model_dump() for feedback in feedback_list]
    }

if __name__ == '__main__':
    setup_logging(level=logging.DEBUG)
    from config.courses import get_execution_input
    exec_input    = get_execution_input(
        subject = "AP World History - vUnit_9_new", 
        subsection = "Explain how the development of new technologies changed the world from 1900 to present."
    )
    context = Context(**prep_content_gen_input(exec_input))
    print_json(generate_lesson_video_plan('', '', context.model_dump()))
    asda
    path = f"college_board/AP World History: Video Lessons 2/AP World History - v7/contents/subsection/Video Plan/{context.key}.json"
    video_plan = VideoPlan(**load_json_from_s3(path)['video_plan']).model_dump()

    final_touchups = final_touchups(video_plan)

    print_json(final_touchups)
    # video_plan = {
    #     "video_plan": VideoPlan(**final_touchups(video_plan['video_plan'])).model_dump(),
    #     "qc_iterations": video_plan['qc_iterations']
    # }
    # save_json_to_s3(video_plan, path)

    # video_plan = generate_lesson_video_plan('', '', context.model_dump())
    # #save to file
    # with open('video_plan.json', 'w') as f:
        # json.dump(video_plan, f, indent=2)
    