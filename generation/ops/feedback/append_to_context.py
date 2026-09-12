import csv
from core.types import LessonContextPack
from core.context import APVideoContext
from core.clients.s3 import does_file_exist, load_json_from_s3, save_json_to_s3

def append_feedback_to_context(event, context):
    input_context = APVideoContext(**event.get("ExecutionInput"), **event.get("Input"))
    csv_file_path = event.get("csv_file_path")
    
    # Load the lesson plan
    lesson_plan = load_json_from_s3(input_context.get_lesson_plan_path())
    
    # Read CSV file
    with open(csv_file_path, 'r') as csvfile:
        csv_reader = csv.reader(csvfile)
        csv_data = list(csv_reader)
    
    # Process each subsection
    for unit_title, unit_lesson_plan in lesson_plan.get("Units", {}).items():
        for chapter_title, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
            for section_title, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
                for subsection_title, _ in section_lesson_plan.get("Subsections", {}).items():
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
                    
                    # Find matching rows in CSV, assumes first column is subsection title and second column is feedback
                    matching_rows = [row[1] for row in csv_data if row[0] == subsection_title]
                    
                    if matching_rows:
                        # Load context pack
                        context_pack_path = context.context_pack_path
                        if not does_file_exist(context.context_pack_path):
                            lesson_context_pack = LessonContextPack.from_context(context)
                            context_pack = {
                                'transcript_pack': lesson_context_pack.transcript_pack
                            }
                        else:
                            context_pack = load_json_from_s3(context_pack_path)
                        
                        # Concatenate feedback and append to context
                        feedback = "\n-".join(matching_rows)
                        context_pack['transcript_pack'] += f"\n-{feedback}"
                        
                        # Save updated context pack
                        save_json_to_s3(context_pack, context_pack_path)
                        
                        print(f"Updated context pack for: {context.key}")
                    else:
                        print(f"No feedback found for: {context.subsection}")
    
    return {"message": "Feedback appended to context packs successfully"}

f"""
This script is utilised to append feedback to the context packs of lessons that have been reviewed and approved.
The initial feedback is auto categorized and generated in the analyze_sme_comments.py script.
Note that you should always manually check the feedback before running this script.
"""
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
    
    result = append_feedback_to_context(event, None)
