from core.context import APVideoContext
from core.clients.s3 import does_file_exist, load_json_from_s3
from core.types import LessonContextPack


import csv


def dump_context_to_csv(event, context):
    input_context = APVideoContext(**event.get("ExecutionInput"), **event.get("Input"))
    csv_file_path = event.get("csv_file_path")

    # Load the lesson plan
    lesson_plan = load_json_from_s3(input_context.get_lesson_plan_path())

    # Create a CSV file
    with open(csv_file_path, 'w') as csvfile:
        csv_writer = csv.writer(csvfile)

        # Write header
        csv_writer.writerow(["l1 id", "l1 description", "Context pack"])

        # Write feedbacks
        for unit_title, unit_lesson_plan in lesson_plan.get("Units", {}).items():
            for chapter_title, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
                for section_title, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
                    for subsection_title, subsection_lesson_plan in section_lesson_plan.get("Subsections", {}).items():
                        context = APVideoContext(
                            grade=input_context.grade,
                            subject=input_context.subject,
                            course=input_context.course,
                            curriculum=input_context.curriculum,
                            unit=unit_title,
                            chapter=chapter_title,
                            section=section_title,
                            subsection=subsection_title
                        )
                        context_pack_path = context.context_pack_path
                        if not does_file_exist(context_pack_path):
                            lesson_context_pack = LessonContextPack.from_context(context)
                            context_pack = {
                                'transcript_pack': lesson_context_pack.transcript_pack
                            }
                        else:
                            context_pack = load_json_from_s3(context_pack_path)
                        csv_writer.writerow([subsection_lesson_plan["StandardId"], subsection_title, context_pack['transcript_pack']])

    return {"message": "Feedback CSV file created successfully"}

if __name__ == "__main__":
    event = {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons",
            "grade": "Grade 11",
            "subject": "AP World History - v1",
            "category": "High School: AP World History: Modern"
        },
        "Input": {},
        "csv_file_path": "/tmp/context_data.csv"  # ToDO: instead of using csv, directly use gsheet api
    }
    
    result = dump_context_to_csv(event, None)