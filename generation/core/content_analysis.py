import ast
import json
from typing import List

from core.types import (
    MCQ, Concept, LessonKnowledgeGraph, OverlaysData, TranscriptLesson,
    TranscriptOutput, TranscriptTiming, VideoPlan)
from core.helpers import \
    llm_call
from fuzzywuzzy import fuzz
from core.context import APVideoContext as Context
from core.context import (get_lesson_context,
                                        prep_content_gen_input)
from core.clients.openai import LLM
from core.clients.s3 import load_json_from_s3

REPETITION_SYSTEM_PROMPT = """You are tasked with analyzing a transcript of a video lesson in history to identify instances of significant repetition that could potentially frustrate students. Your goal is to maintain the quality and effectiveness of the educational content. 

Please follow these steps to complete the analysis:

1. Carefully read through the entire transcript.

2. As you read, identify instances where there seems to be a recurring theme, repeating examples, or explanations.

3. Analyze these instances to determine which repetitions are acceptable (serving as reminders or reinforcing learning) versus those that are excessive and might frustrate students.

4. Pay special attention to the following guidelines when identifying significant repetition:
   - Slight repetition is acceptable when defining relationships or drawing parallels with past content, but it should be just enough to remind, not re-explain already taught concepts.
   - Repetition becomes problematic when a concept mostly reiterates previously explained information without adding substantial new insights.
   - Focus on repetition that would likely frustrate students by making them review material they've already grasped.

5. Note that repetition is allowed and even encouraged in the following cases:
   - Any repetition by the HOST figure, as it reinforces learning.
   - Repetition when drawing parallels with previously learned facts.

6. Use a scratchpad to think through your analysis. In your scratchpad, you can list out potential instances of repetition and evaluate each one based on the guidelines provided.

7. After completing your analysis, compile your findings inside the <findings> rag into a Python list format as follows:
<findings>
   [
      "<Identify the repeating detail with quotes. Specify the original place it's being explained, and then where it's being reintroduced with excessive repetition>"
   ]
</findings>

Remember, your goal is to identify repetition that goes beyond reinforcing key points and instead risks disengaging students due to excessive reiteration of already understood material.

<scratchpad>
Use this space to list and evaluate potential instances of repetition. Consider each instance carefully, determining whether it's necessary for learning reinforcement or if it's excessive and potentially frustrating for students.
</scratchpad>

Your final output should be a Python list containing only the instances of significant repetition that meet the criteria described above. Each item in the list should clearly identify the repeating detail with quotes, specify where it was originally explained, and then where it was excessively repeated. Do not include your scratchpad notes in the final output."""

REPETITION_USER_PROMPT = """Here is the transcript:

<transcript>
{transcript}
</transcript>"""

def get_transcript_string(lesson_transcript: TranscriptLesson) -> str:
    transcript = f""
    for ii, (section_title, section) in enumerate(lesson_transcript.sections.items()):
        transcript += f"\n\n# Section: {section_title}"
        for jj, (concept_title, concept) in enumerate(section.explanations.items()):
            transcript += f"\n\n\t## Concept: {concept_title}"
            if jj == 0:
                transcript += f"\n\n[Host]: {concept.question}\n\n[{concept.figure_name}]: {concept.explanation}"
            else:
                transcript += f"\n\n{concept.question}\n\n[{concept.figure_name}]: {concept.explanation}"
    return transcript


def add_facts_ids_to_vp(context: Context, similarity_threshold: int = 85) -> dict:
    kg = LessonKnowledgeGraph(**load_json_from_s3(context.kg_path))
    video_plan = VideoPlan(**load_json_from_s3(context.video_plan_path)['video_plan'])

    for ii, section in enumerate(video_plan.sections):
        for jj, concept in enumerate(section.concepts):
            for kk, fact in enumerate(concept.facts):
                # print(max([fuzz.ratio(fact, node.fact_text) for node in (kg.lo_nodes + (kg.xu_facts or []))]))
                try:
                    video_plan.sections[ii].concepts[jj].facts[kk] = next(f"{node.id}) {fact}" for node in (kg.lo_nodes + (kg.xu_facts or [])) if fuzz.ratio(fact, node.fact_text) >= similarity_threshold )
                except:
                    video_plan.sections[ii].concepts[jj].facts[kk] = fact


    output = {
        section.section_title: {
            concept.concept_name: concept.facts 
            for concept in section.concepts
        }
        for section in video_plan.sections
    }
    return output

def find_repetition_risks(context: Context) -> List[str]:
    facts_with_id = add_facts_ids_to_vp(context)
    risks = [f"{section_title} => {concept_title}" 
    for section_title, concepts in facts_with_id.items()
    for concept_title, facts in concepts.items()
    if all(fact.startswith(("KC", "RP")) for fact in facts)]

    high_risk_facts = {}
    for risk in risks:
        section_title, concept_title = risk.split(" => ")
        high_risk_facts[concept_title] = {'facts': facts_with_id[section_title][concept_title]}

    return high_risk_facts, risks

def handle_lesson(context: Context):
    transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path)).lesson_transcript_breakdown
    transcript_str = get_transcript_string(transcript)
    # high_risk_facts, risks = find_repetition_risks(context)
    # if not risks:
    #     return dict(
    #         is_repetitive=False,
    #         evaluation="No pure KC or RP concepts"
    #     )

    history, repetitions = llm_call(
        system_prompt=REPETITION_SYSTEM_PROMPT,
        user_prompt=REPETITION_USER_PROMPT.format(transcript=transcript_str),
        model=LLM.CLAUDE_5_OPUS,
        tag="findings"
    )
    
    repetitions = ast.literal_eval(repetitions)

    output = dict(
        is_repetitive=bool(repetitions),
        evaluation=repetitions,
        # concepts=high_risk_facts
    )


    return output

if __name__ == "__main__":
    context = {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons 2",
            "grade": "Grade 11",
            "subject": "AP World History - vUnit_1",
            "category": "High School: AP World History: Modern"
        },
        "Input": get_lesson_context('Explain the causes and effects of environmental changes in the period from 1900 to present.')
    }

    lesson_plan = load_json_from_s3('college_board/AP World History: Video Lessons 2/AP World History - v2/lesson_plan.json')
    for unit_title, unit in lesson_plan["Units"].items():
        for chapter_title, chapter_details in unit["Chapters"].items():
            if chapter_title not in ['The Global Tapestry']:
                continue
            for section_title, section_details in chapter_details["Sections"].items():
                for subsection_title in section_details["Subsections"].keys():
                    context["Input"] = dict(
                        unit=unit_title,
                        chapter=chapter_title,
                        section=section_title,
                        subsection=subsection_title
                    )
                    lesson_context = Context(**prep_content_gen_input(context))

                    evals_json = json.load(open('./evals.json', 'r'))
                    if evals_json.get(lesson_context.chapter, {}).get(lesson_context.section, {}).get(lesson_context.subsection, None) is not None:
                        continue
                    evals_json.setdefault(lesson_context.chapter, {}).setdefault(lesson_context.section, {}).setdefault(lesson_context.subsection, [])

                    lesson_eval = handle_lesson(lesson_context)

                    evals_json[lesson_context.chapter][lesson_context.section][lesson_context.subsection] = lesson_eval['evaluation']
                    json.dump(evals_json, open('./evals.json', 'w'), indent=4)
