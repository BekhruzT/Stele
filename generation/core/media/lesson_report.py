import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
from core.types import (
    Diagram, OverlaysData, TranscriptTiming)
from core.helpers import (
    get_topics_list, llm_call, print_json, split_transcript)
from core.content_analysis import \
    handle_lesson as get_repetition_report
from tqdm import tqdm
from core.context import APVideoContext as Context
from core.context import (get_lesson_context,
                                        prep_content_gen_input)
from core.hash import hash_code
from core.clients.openai import LLM
from core.path import get_key
from core.clients.s3 import (does_file_exist, list_files_in_directory,
                      load_json_from_s3, save_json_to_s3)

TRANSCRIPT_COVERAGE_PROMPT = """
You are an AI assistant tasked with analyzing if a given transcript covers the list of facts given. Your analysis will help determine the accuracy and completeness of information transmission. 

First, carefully read the following transcript, it is the explanation for the concept '{CONCEPT_NAME}':

<transcript>
{TRANSCRIPT}
</transcript>

The transcript is being spoken by {FIGURE}

Now, consider the following list of facts (these are the facts for the current concept that is being explained):

<current_concept_facts>
{FACTS}
</current_concept_facts>

Now, these are the concepts and their explanations that have been explained in the lesson before the current concept:

<previous_explanations>
{PREVIOUS_EXPLANATIONS}
</previous_explanations>

Your task is to analyze how well each fact in current concept is covered in the transcript and whether the transcript adds any details that is out of syllabus of facts. For each fact, you need to determine:

1. Whether the fact was mentioned in the transcript (Yes/No), only binary answer 
2. How thoroughly the information in the fact was explained in the transcript (Fully/Partially/Not at all)
3. A brief justification for your assessment mentioning the relevant parts of the transcript that support your assessment.
4. Whether the transcript adds any details that is out of syllabus (syllabus is current concept facts + previous concept explanations)

After analyzing all facts, identify any significant information or knowledge present in the transcript that was not covered by the given facts.

Follow these steps:

1. For each fact in the list (only see the facts for current concept for this step), analyze if it's covered by following these steps:
   a. Read the fact carefully.
   b. Search for relevant information in the transcript and quote it.
   c. Consider arguments for whether the fact is mentioned (Yes/No) and how thoroughly it was explained (Fully/Partially/Not at all).
   d. Determine if the fact is mentioned (Yes/No). Stricly fill with Yes or No. Any sign of the fact being mentioned in the transcript, even slightly, is Yes.
   e. If mentioned, assess how thoroughly it was explained (Fully/Partially/Not at all).
     - Fully explained here means that all aspects of the fact is covered in the transcript. Transcript does not need to go beyond the information presented in the facts at all.
     - The transcript is expected to elaborate/expand on any fact only as much as the facts say, not anything beyond.
     - All the information that transcript is expected to say is already present in the facts.
     - Eg. "European expansion into the Western Hemisphere generated intense social, religious, political, and economic competition and changes within European societies." is the fact, the transcript is not expected to go in details of what economic competition and changes if that is not part of the fact.
   f. Provide a brief justification for your assessment.
   g. There are certain facts that are marked as (HIGH LEVEL), these are used to close off explanation of several underlying facts. The information in them might be might be scattered across current and previous expalantions. Do check both current and previous explanations for assesing such facts. If the high level picture they are trying to tell is covered somehwere in the transcript, mark them as Fully explained.


2. After analyzing all facts, check if the transcript has added any extra details that were not part of the syllabus (list of facts). Guidlines for doing so:
   - The transcript might refer to earlier knowledge saying something like "as we/you have learned earlier". This is not extra information and is acceptable.
   - The transcript might ask rhetorical questions which are not part of the facts. This is not extra information and is acceptable.
   - The transcript might use some pedagogical examples which is also acceptable.
   - The transcript might use first person perspective to explain the fact. This is acceptable.
   - The transcript might invite students to answer some questions. This is not extra information and is acceptable.
   - The transcript might set context for some fact before explaining it. This is acceptable.
   - The transcript might give analogies and give examples of what something is not. This is acceptable.
   - The transcript might refer to something taught in previous concepts. This is acceptable. It might even combine or make comparisions to stuff already taught in previous concepts. That is fine. Previous concepts are also part of syllabus.
   - If transcript gives some example that is out of syllabus but is something simple that AP students are expected to know/understand, that is acceptable. For example, "A borrowed customs such as simpler cooking methods from B" is acceptable even though facts don't mention anything about cooking. This is not something that will add congitive load or confusion but would rather help the student understand the fact better.

   - Examples of extra information you have to catch:
     - When explaining Reconquista, if the facts don't mention fall of Granada, transcript also should not mention it. If it says "After fall of Granada", that's extra information you have to catch.
     - When talking about story of Columbus reaching some shore with his ships, if the transcript adds names of the ships and the facts don't mention them like if it says "Columbus reached xyz shore with his ships  Nina, Pinta and Santa Maria" if the facts don't have the names of the ships, that's extra information you have to catch.
     - Some extra date that was not part of the facts but transcript said it.
     - When explaining Aztec Innovations, if let's say the facts don't mention Lake Texcoco, and the transcript add details about Lake Texcoco that might confuse the student, that's an extra information you have to catch.
   
   - You have to look for such things that might uncessearily add stuff to remember for the students increasing the cognitive load or might confuse the student.
   - The transcript might definitely use some teaching techniques like giving examples, analogies, setting context, stories etc., or might explain something differently that is okay and acceptable, we are looking for new information that transcript adds that student might think is important and might try add to their memory even when it's not important.
   - Do not add the acceptable extra information (what all is acceptable is mentioned above) to the extra_information field. If you find no extra information (everything is acceptable), return an empty string ("").

3. Compile your analysis into a JSON format as shown in the structure below.
 Here's an example of the JSON structure you should use for your output:

```json
{{
  "fact_coverage": [
    {{
      "fact_number": 1,
      "mentioned": "Yes/No",
      "explained": "Fully/Partially/Not at all",
      "justification": "Brief explanation of your assessment",
      "fact_text": "exact fact text"
    }},
    {{
      "fact_number": 2,
      "mentioned": "Yes/No",
      "explained": "Fully/Partially/Not at all",
      "justification": "Brief explanation of your assessment",
      "fact_text": "exact fact text"
    }}
  ],
  "extra_information": "Summary of any significant information in the transcript that is out of syllabus, if not present, return an empty string ('')."
}}
```
(the fact_coverage array is only for the current concept facts)

Return only the JSON output and nothing else.
"""

def normalize(text:str)->str:
    text = text.replace("(HIGH LEVEL)", "").strip()
    return re.sub(r'\W+', '', text).lower()

def process_coverage_llm_call(concept_name, transcript, facts, figure_name, previous_explanations):
    """Process a single LLM call for fact coverage analysis"""
    _, fact_coverage = llm_call(
        system_prompt='',
        user_prompt=TRANSCRIPT_COVERAGE_PROMPT.format(
            CONCEPT_NAME=concept_name, 
            TRANSCRIPT=transcript, 
            FACTS=json.dumps(facts, indent=2), 
            FIGURE=figure_name, 
            PREVIOUS_EXPLANATIONS=json.dumps(previous_explanations, indent=2)
        ),
        model=LLM.CLAUDE_3_7_SONNET,
        is_json=True,
    )
    return {
        "concept_name": concept_name,
        "fact_coverage": fact_coverage
    }

def qc_lesson_slides_length(context: Context) -> dict:

    overlays = OverlaysData(**load_json_from_s3(context.text_overlays_path))

    point_phrase_mismatch = {}
    for slide in overlays.text_slides:
        id = os.path.basename(slide.src)[:-4]
        max_ratio, phrase, point = max([
            (len(" ".join([p.content for p in point.contents])) / len(" ".join([p.content for p in point.contents])), " ".join([p.phrase for p in point.contents]), " ".join([p.content for p in point.contents]))
            for point in slide.elements
        ])

        if max_ratio>1.2:
            point_phrase_mismatch[id] = {
                "max_ratio": round(max_ratio, 2),
                "point": point, 
                "phrase": phrase
            }
        
    return point_phrase_mismatch

def get_lesson_report(context: Context):

    kg_json = load_json_from_s3(context.kg_path)
    video_plan_json = load_json_from_s3(context.video_plan_path)
    transcript_json = load_json_from_s3(context.transcripts_path)
    overlays_json = load_json_from_s3(context.text_overlays_path)
    clips_json = load_json_from_s3(context.clips_path)
    images_json = load_json_from_s3(context.image_json_path)
    videos_json = load_json_from_s3(context.video_json_path)
    
    # ============VIDEO PLAN COVERAGE============
    # number of facts in the kg
    kg_facts = []
    for node in kg_json["lo_nodes"]:
        kg_facts.append(node["fact_text"])
    if "xu_facts" in kg_json and kg_json["xu_facts"]:
        for node in kg_json["xu_facts"]:
            kg_facts.append(node["fact_text"])

    # number of facts in the video plan
    video_plan_facts = []
    for section in video_plan_json["video_plan"]["sections"]:
        for concept in section["concepts"]:
            for fact in concept["facts"]:
                video_plan_facts.append(fact)
            if concept['cross_unit_facts']:
                for fact in concept['cross_unit_facts']:
                    video_plan_facts.append(fact)
    
    normalized_video_plan_facts = [normalize(fact) for fact in video_plan_facts]
    video_plan_missed_facts = [fact for fact in kg_facts if normalize(fact) not in normalized_video_plan_facts]
    no_of_video_plan_missed_facts = len(video_plan_missed_facts)

    # ============TRANSCRIPT COVERAGE============
    total_facts_in_video_plan = len(video_plan_facts)
    mentioned_in_transcript = 0
    fully_explained = 0
    partially_explained = 0
    not_explained = 0
    out_of_syllabus = {}
    fact_coverages = {}
    
    # Prepare tasks for parallel processing
    previous_explanations = {}
    tasks = []
    for section in video_plan_json["video_plan"]["sections"]:
        for concept in section["concepts"]:
            # Keep the data preparation outside the thread function
            facts_list = []
            for fact in concept["facts"]:
                facts_list.append(fact)
            if concept['cross_unit_facts']:
                for fact in concept['cross_unit_facts']:
                    facts_list.append(fact)
                    
            explanation_transcript = transcript_json["lesson_transcript_breakdown"]["sections"][section["section_title"]]["explanations"][concept["concept_name"]]["explanation"]
            
            # Store concept_name along with what's needed for the LLM call
            tasks.append((concept["concept_name"], explanation_transcript, facts_list, concept["figure_name"], previous_explanations))
            previous_explanations[concept["concept_name"]] = explanation_transcript
    
    # Process LLM calls in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda args: process_coverage_llm_call(*args), tasks))
    
    # Process results
    for result in results:
        concept_name = result["concept_name"]
        fact_coverage = result["fact_coverage"]
        
        if fact_coverage.get("extra_information", "") != "":
            out_of_syllabus[concept_name] = fact_coverage.get("extra_information", "")
        
        for fact in fact_coverage.get("fact_coverage", []):
            if fact.get("mentioned", "") == "Yes":
                mentioned_in_transcript += 1
            if fact.get("explained", "") == "Fully":
                fully_explained += 1
            if fact.get("explained", "") == "Partially":
                partially_explained += 1
            if fact.get("explained", "") == "Not at all":
                not_explained += 1
        
        fact_coverages[concept_name] = fact_coverage
    
    # cleanup fact_coverages
    cleaned_fact_coverages = {}
    for concept, concept_coverage in fact_coverages.items():
        for fact in concept_coverage["fact_coverage"]:
            if not (fact["mentioned"] == "Yes" and fact["explained"] == "Fully"):
                if concept not in cleaned_fact_coverages:
                    cleaned_fact_coverages[concept] = []
                cleaned_fact_coverages[concept].append(fact)
    fact_coverages = cleaned_fact_coverages


    # ============ LESSON STATS ============
    map_included = "Yes" if video_plan_json["video_plan"]["included_map"]!="" else "No"
    length_of_longest_title = len(video_plan_json["video_plan"]["lesson_title"].split())
    section_concept_counts = []
    visuals_count = {}
    teaching_tech_count = {}
    for section in video_plan_json["video_plan"]["sections"]:
        section_concept_counts.append(len(section["concepts"]))
        concept_facts_counts = []
        length_of_longest_title = max(length_of_longest_title, len(section["section_title"].split()))
        for concept in section["concepts"]:

            visual = concept["visual"]["type"]
            if visual == "diagram":
                visual = concept["visual"]["diagram_type"]
            if visual not in visuals_count:
                visuals_count[visual] = 0
            visuals_count[visual] += 1

            for teaching_tech in concept["teaching_techniques"]:
                if teaching_tech["choice"] not in teaching_tech_count:
                    teaching_tech_count[teaching_tech["choice"]] = 0
                teaching_tech_count[teaching_tech["choice"]] += 1

    # ============ REPETITION REPORT ============
    repetition_report = get_repetition_report(context)


    # =============== QC FLAGS =================
    repetition_flag = repetition_report["is_repetitive"]
    out_of_syllabus_flag = len(out_of_syllabus) > 0
    coverage_flag = fully_explained < total_facts_in_video_plan

    # All Diagram generated or not
    text_slides_generated = len([slide for slide in overlays_json["text_slides"] if slide["src"] != ""])
    diagrams_generated = len([slide for slide in overlays_json["diagrams"] if slide["src"] != ""])
    conclusion_generated = 1 if overlays_json["conclusion_slide"]["src"] != "" else 0
    required_diagrams = sum(visuals_count.values()) + len(video_plan_json["video_plan"]["sections"]) + 1 #1 for conclusion
    if len(video_plan_json["video_plan"]["sections"]) > 1:
        required_diagrams += 1  #1 for lesson overview
    diagrams_flag = required_diagrams != (text_slides_generated + diagrams_generated + conclusion_generated)

    # MAP present or not if requied
    map_flag = False
    if map_included == "Yes":
        ids_with_images = [clip['media']['id'] for clip in clips_json['clips'] if clip['media']['type'] == 'IMAGE']
        for image in images_json['images']:
            if image['id'] in ids_with_images and image['type'] != "web":
                map_flag = True
                break
        for video in videos_json['videos']:
            if video['id'] in ids_with_images:
                map_flag = True
                break 
    
    # Overlapping Visuals
    overlapping_visuals_flag = False
    all_visuals = []
    for item in overlays_json['text_slides']:
        all_visuals.append({'start': item['start_time'], 'end': item['end_time']})
    for item in overlays_json['diagrams']:
        # exclude overview diagrams for checking overlaps, the lesson overview and first section overview overlaps in timings but looks perfect
        if item['type']=="lesson_organizer" or (item['type']=="mind_map" and len(item['data']['categories'][0]['points'])==0):
            continue
        all_visuals.append({'start': item['start_time'], 'end': item['end_time']})
    all_visuals.append({'start': overlays_json['conclusion_slide']['start_time'], 'end': overlays_json['conclusion_slide']['end_time']})

    all_visuals.sort(key=lambda x: x['start'])
    for i in range(len(all_visuals) - 1):
        if all_visuals[i]['end'] > all_visuals[i+1]['start']:
            overlapping_visuals_flag = True
            break

        

    return {
        "transcript_coverage": {
            "total_facts_in_video_plan": total_facts_in_video_plan,
            "mentioned_in_transcript": mentioned_in_transcript,
            "fully_explained": fully_explained,
            "partially_explained": partially_explained,
            "not_explained": not_explained,
            "fact_coverages": fact_coverages,
            "out_of_syllabus": out_of_syllabus,
        },
        "repetition_check": repetition_report,
        "overlays": {
            "text_slide_point_phrase_mismatch": qc_lesson_slides_length(context)
        },
        "video_plan_coverage": {
            "no_of_facts_in_kg": len(kg_facts),
            "no_of_facts_in_video_plan": len(video_plan_facts),
            "no_of_video_plan_missed_facts": no_of_video_plan_missed_facts,
            "video_plan_missed_facts": video_plan_missed_facts
        },
        "lesson_stats": {
            "teaching_tech_count": teaching_tech_count,
            "visuals_count": visuals_count,
            "length_of_longest_title": length_of_longest_title,
            "map_included": map_included,
            "section_concept_counts": section_concept_counts
        },
        "qc_flags": {
            "Repetition": repetition_flag,
            "Out of Syllabus": out_of_syllabus_flag,
            "Coverage": coverage_flag,
            "Missing Visual": diagrams_flag,
            "Missing Map": map_flag,
            "Overlapping Visuals": overlapping_visuals_flag
        }
    }

def fetch_lesson_data(execution_input:Dict):
    lesson_datas = {}
    curriculum_data = get_topics_list(execution_input)
    for unit, unit_data in curriculum_data["Units"].items():
        for chapter, chapter_data in unit_data["Chapters"].items():
            for section, subsections in chapter_data["Sections"].items():
                for subsection in subsections:
                    input_dict = {
                        "unit": unit,
                        "chapter": chapter,
                        "section": section,
                        "subsection": subsection
                    }
                    data = {
                        "ExecutionInput": execution_input,
                        "Input": input_dict
                    }
                    lesson_datas[hash_code(get_key([unit, chapter, section, subsection]))] = data
    return lesson_datas

def fetch_generated_lesson_ctx(lesson_datas:Dict):

    shotstack_folder_path = f"{exec_input['curriculum']}/{exec_input['course']}/{exec_input['subject']}/contents/subsection/ShotStack"
    successful_keys = list_files_in_directory(shotstack_folder_path, return_type="basename")
    successful_keys = [os.path.basename(key).split(".")[0] for key in successful_keys if key.endswith(".json")]
    lesson_datas = {k: v for k, v in lesson_datas.items() if k in successful_keys}

    with ThreadPoolExecutor(max_workers=10) as executor:
        contexts_list = list(tqdm(
            executor.map(
                lambda data: Context(**prep_content_gen_input(data)),
                lesson_datas.values()
            ),
            total=len(lesson_datas),
            desc=f"Getting contexts for generated lessons from {exec_input['subject']}:"
        ))
    return contexts_list


if __name__ == "__main__":
    from config.courses import get_execution_input

    # set this to regenerate reports in these folders
    folders_to_check = [
        # "AP US History - vUnit_1",
        # "AP US History - vUnit_1_new",
        # "AP US History - vUnit_2_new",
        # "AP US History - vUnit_3_new",
        "AP US History - vUnit_4_new",
    ]

    # set this to limits the lessons to generate reports for
    lesson_ids_to_check = [
        "d741377b",
        "1c156641",
        "4e9f0ab2",
        "8ac4620f",
        "89be2b0d"
    ]

    lesson_ctxs = []

    print("Fetching contexts to generate reports for...")
    for folder in folders_to_check:
        exec_input = get_execution_input(folder)["ExecutionInput"]
        lesson_datas = fetch_lesson_data(exec_input)
        # comment this out to generate reports for all generated lessons in the folder-------|
        # lesson_datas = {k: v for k, v in lesson_datas.items() if k in lesson_ids_to_check}
        # -----------------------------------------------------------------------------------|
        lesson_ctxs.extend(fetch_generated_lesson_ctx(lesson_datas))

    print(f"Identified {len(lesson_ctxs)} lessons to generate reports for")
    print("Generating lesson reports...")

    def generate_and_save_report(lesson_ctx:Context):
        report = get_lesson_report(lesson_ctx)
        shotstack_json = load_json_from_s3(lesson_ctx.shotstack_json_path)
        shotstack_json["lesson_video"]["lesson_report"] = report
        save_json_to_s3(shotstack_json, lesson_ctx.shotstack_json_path)

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(tqdm(
            executor.map(generate_and_save_report, lesson_ctxs),
            total=len(lesson_ctxs),
            desc=" - Generating lesson reports",
        ))