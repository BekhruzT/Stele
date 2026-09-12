from core.context import Context
from core.cost_tracker import init_cost
from core.guidelines import fetch_guidelines
from core.misc import pk
from core.path import get_lesson_plan_content_path, get_lesson_plan_path
from core.clients.s3 import does_file_exist, list_files_in_directory, load_json_from_s3, save_json_to_s3
import logging  
from core.logger import Logger

# logger = Logger("APVideosLessonPlanner", logging.DEBUG)
logger = logging.getLogger(__name__)

class APVideosLessonPlanner:
    @staticmethod
    def orchestrate_lesson_plan_generation(event, context):
        logger.info(f"Invoked with input: {event}")

        input_context = Context(**event.get("ExecutionInput"), **event.get("Input"))

        guidelines = fetch_guidelines(input_context.course, input_context.curriculum, input_context.subject)
        logger.info(f"Fetched {len(guidelines)} guidelines for course: {input_context.course}, curriculum: {input_context.curriculum}")

        unit_field = "unit"
        chapter_field = "chapter"

        units = {}
        for guideline in guidelines:
            unit = guideline[unit_field]
            chapter = guideline[chapter_field]
            units.setdefault(unit, [])
            units[unit].append(chapter)

        outputs = []
        for unit, chapters in units.items():
            for chapter in set(chapters):
                outputs.append({"unit": unit, "chapter": chapter})

        logger.info(f"Found {len(outputs)} chapters for course: {input_context.course}, curriculum: {input_context.curriculum}")

        init_cost(pk(input_context.course, input_context.curriculum, input_context.subject), pk("cost", "lesson_plan", "clustering"))

        return outputs

    @staticmethod
    def generate_lesson_plan(event, context):
        input_context = Context(**event.get("ExecutionInput"), **event.get("Input"))

        enhanced_data_path = get_lesson_plan_content_path(input_context.course, input_context.curriculum, input_context.subject, "ap-video-data",
                                                          f"{input_context.unit}_{input_context.chapter}.json")

        if does_file_exist(enhanced_data_path):
            logger.info(
                f"Lesson Plan Enhancer already exists for : {enhanced_data_path}. Skipping!")
            return True
        
        logger.info(f"Generating lesson plan for subject: {input_context.subject}, unit: {input_context.unit}, chapter: {input_context.chapter}")

        # Fetch guidelines for the specific course, curriculum, and subject
        guidelines = fetch_guidelines(input_context.course, input_context.curriculum, input_context.subject)

        # Filter guidelines for the current chapter
        chapter_guidelines = next(g for g in guidelines if g.get("chapter") == input_context.chapter and g.get("unit") == input_context.unit)["concepts"]

        any_l3s_defined = any([g.get("Standard Description (L3)", "") for g in chapter_guidelines])
        # Process guidelines to create sections and subsections
        sections = {}
        for guideline in chapter_guidelines:
            cluster = guideline.get("Cluster", "Uncategorized")
            l1 = guideline.get("Standard Description (L1)", "Uncategorized")
            l3 = guideline.get("Standard Description (L3)", "Uncategorized")
            l4 = guideline.get("Standard Description Plus", "Uncategorized")
            concept = guideline.get("Concept", "")

            if cluster not in sections:
                sections[cluster] = {}

            if l1 not in sections[cluster]:
                sections[cluster][l1] = {}
                sections[cluster][l1]['DomainId'] = guideline.get("DomainId", "")
                sections[cluster][l1]['ClusterId'] = guideline.get("ClusterId", "")
                sections[cluster][l1]['StandardId'] = guideline.get("StandardId", "")

            if "key_concepts" not in sections[cluster][l1]:
                sections[cluster][l1]["key_concepts"] = {}

            if any_l3s_defined:
                if l3 not in sections[cluster][l1]["key_concepts"]:
                    sections[cluster][l1]["key_concepts"][l3] = {}
                if l4 not in sections[cluster][l1]["key_concepts"][l3]:
                    sections[cluster][l1]["key_concepts"][l3][l4] = []
                sections[cluster][l1]["key_concepts"][l3][l4].append(concept)
            else:
                if l4 not in sections[cluster][l1]["key_concepts"]:
                    sections[cluster][l1]["key_concepts"][l4] = []
                sections[cluster][l1]["key_concepts"][l4].append(concept)

            # Store unique misconceptions
            if "misconceptions" not in sections[cluster][l1]:
                sections[cluster][l1]["misconceptions"] = set()

            for key, value in guideline.items():
                if key.startswith("Common Misconception") and value:
                    sections[cluster][l1]["misconceptions"].add(value)


            if "boundary_notes" not in sections[cluster][l1]:
                sections[cluster][l1]["boundary_notes"] = set()

            for key, value in guideline.items():
                if key.startswith("BoundaryNotes") and value:
                    sections[cluster][l1]["boundary_notes"].add(value)


        # Create the enhanced data structure
        enhanced_data = {
            "Units": {
                input_context.unit: {
                    "Chapters": {
                        input_context.chapter: {
                            "Sections": {
                                section_title: {
                                    "Subsections": {
                                        subsection_title: {
                                            "Concepts": subsection_data["key_concepts"],
                                            "Misconceptions": list(subsection_data["misconceptions"]),
                                            "BoundaryNotes": list(subsection_data["boundary_notes"]),
                                            "DomainId": subsection_data["DomainId"],
                                            "ClusterId": subsection_data["ClusterId"],
                                            "StandardId": subsection_data["StandardId"]
                                        } for subsection_title, subsection_data in section_data.items()
                                    }
                                } for section_title, section_data in sections.items()
                            }
                        }
                    }
                }
            }
        }

        # Save the enhanced data
        
        save_json_to_s3(enhanced_data, enhanced_data_path)

        logger.info(f"Successfully generated and saved enhanced lesson plan data for unit: {input_context.unit}, chapter: {input_context.chapter}")

        return enhanced_data

    @staticmethod
    def aggregate_ap_video_lesson_plan(event, context):


        input_context = Context(**event.get("ExecutionInput"), **event.get("Input"))

        files = list_files_in_directory(f"{input_context.curriculum}/{input_context.course}/{input_context.subject}/lesson-plan/ap-video-data")
        aggregated_data = {
            "Units": {}
        }

        for file in files:
            if file.endswith('.json'):
                data = load_json_from_s3(file)
                for unit, unit_data in data.get("Units", {}).items():
                    if unit not in aggregated_data["Units"]:
                        aggregated_data["Units"][unit] = {"Chapters": {}}
                    for chapter, chapter_data in unit_data.get("Chapters", {}).items():
                        if chapter not in aggregated_data["Units"][unit]["Chapters"]:
                            aggregated_data["Units"][unit]["Chapters"][chapter] = {"Sections": {}}
                        for section, section_data in chapter_data.get("Sections", {}).items():
                            if section not in aggregated_data["Units"][unit]["Chapters"][chapter]["Sections"]:
                                aggregated_data["Units"][unit]["Chapters"][chapter]["Sections"][section] = {"Subsections": {}}
                            for subsection, subsection_data in section_data.get("Subsections", {}).items():
                                if subsection not in aggregated_data["Units"][unit]["Chapters"][chapter]["Sections"][section]["Subsections"]:
                                    aggregated_data["Units"][unit]["Chapters"][chapter]["Sections"][section]["Subsections"][subsection] = {
                                        "Concepts": {},
                                        "Misconceptions": subsection_data.get("Misconceptions", []),
                                        "BoundaryNotes": subsection_data.get("BoundaryNotes", []),
                                        "DomainId": subsection_data.get("DomainId", ""),
                                        "ClusterId": subsection_data.get("ClusterId", ""),
                                        "StandardId": subsection_data.get("StandardId", "")
                                    }
                                for concept_key, concept_value in subsection_data.get("Concepts", {}).items():
                                    aggregated_data["Units"][unit]["Chapters"][chapter]["Sections"][section]["Subsections"][subsection]["Concepts"][concept_key] = concept_value

        aggregated_data_path = get_lesson_plan_path(input_context.course, input_context.curriculum, input_context.subject)
        save_json_to_s3(aggregated_data, aggregated_data_path)