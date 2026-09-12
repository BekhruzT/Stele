from ops.quality.chapter_reviewer import chapter_level_review
from ops.authoring.metadata import generate_lesson_metadata
from core.context import Context
from core.path import get_content_path
from core.cost_tracker import init_cost
from core.misc import pk
from core.clients.s3 import does_file_exist, load_json_from_s3, save_json_to_s3
import logging  
from core.logger import Logger
from core.context import APVideoContext

# logger = Logger("APVideosLessonPlanner", logging.DEBUG)
logger = logging.getLogger(__name__)

class APVideosContentPlanner:
    @staticmethod
    def orchestrate_content_plan_generation(event, context):
        input_context = Context(**event.get("ExecutionInput"), **event.get("Input"))

        lesson_plan_path = input_context.get_lesson_plan_path()
        lesson_plan = load_json_from_s3(lesson_plan_path)
        logger.info(f"Successfully loaded lesson plan for course: {input_context.course}, curriculum: {input_context.curriculum}")

        events = []
        for unit_title, unit_lesson_plan in lesson_plan.get("Units", {}).items():
            for chapter_title, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
                for section_title, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
                    for subsection_title, _ in section_lesson_plan.get("Subsections", {}).items():
                        events.append({
                            "unit": unit_title,
                            "chapter": chapter_title,
                            "section": section_title,
                            "subsection": subsection_title
                        })
        init_cost(pk(input_context.course, input_context.curriculum, input_context.subject), pk("cost", "subsection", "content-plan"))
        logger.info(f"Successfully generated events for orchestrating content plan")
        return events

    @staticmethod
    def generate_content_plan(event, context):
        input_context = Context(**event.get("ExecutionInput"), **event.get("Input"))
        content_plan_path = get_content_path(input_context.course, input_context.curriculum, input_context.subject, "subsection", f"content_plan/{input_context.key}.json")

        video_context = APVideoContext(**event.get("ExecutionInput"), **event.get("Input"))
        content_plan_exists = does_file_exist(content_plan_path)
        metadata_exists = does_file_exist(video_context.metadata_path)
        if content_plan_exists and metadata_exists:
            logger.info(
                f"Content Plan and metadata already exists for subsection: {content_plan_path}. Skipping!")
            return True
        
        if not content_plan_exists:
            lesson_plan_path = input_context.get_lesson_plan_path()
            lesson_plan = load_json_from_s3(lesson_plan_path)
            subsection_lesson_plan = input_context.get_subsection_lesson_plan(lesson_plan)
            content_plan = subsection_lesson_plan.get("Concepts", {}) # type: ignore
            save_json_to_s3(content_plan, content_plan_path)
        if not metadata_exists:
            generate_lesson_metadata(video_context)
        return True


    @staticmethod
    def aggregate_content_plan(event, context): 
        # the old one first takes care of dumping the content plan for all subsections into the final lesson plan
        # here we run chapter level review of metadata and fix if any issues are found
        chapter_level_review(event, context)
