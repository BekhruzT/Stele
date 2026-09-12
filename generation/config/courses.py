"""The courses this pipeline builds, and the execution input each one starts from.

Replaces utils/config.py from the textbook tree. Two things are deliberately gone:
load_configuration and the 11-entry CONFIGS table it read, which bound courses to output
parsers, post processors and the textbook generator. This pipeline has one config
(config/stages.json) and one dispatch map (run.py), so the indirection had nothing to do.
"""

from typing import Optional

# Only the two AP video courses. The textbook tree carried nine more here, for maths and
# science courses that never had a video pipeline.
data_list = [
    {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons 2",
            "grade": "Grade 11",
            "subject": "AP World History",
            "category": "High School: AP World History: Modern",
        },
        "Input": {},
    },
    {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP US History: Video Lessons",
            "grade": "Grade 11",
            "subject": "AP US History",
            "category": "High School: AP US History",
        },
        "Input": {},
    },
]

# Keyed by name rather than by index into data_list, so paring the list cannot silently
# repoint a subject at the wrong course.
BY_SUBJECT = {entry["ExecutionInput"]["subject"]: entry for entry in data_list}


def get_execution_input(subject: str, subsection: Optional[str] = None,
                        chapter: Optional[str] = None, section: Optional[str] = None):
    """The execution input for a subject, optionally narrowed to one lesson.

    `subject` may carry a version suffix, as in "AP US History - v2"; the part before the
    hyphen selects the course and the whole string becomes the S3 prefix.
    """
    base_subject = subject.split('-')[0].strip()
    execution_input = BY_SUBJECT[base_subject]
    # ponytail: mutates the shared data_list entry in place, so two calls with different
    # subjects fight over one dict. Harmless while run.py builds one execution input per
    # process; the fix is to deepcopy the entry before writing the subject onto it.
    execution_input["ExecutionInput"]["subject"] = subject

    if subsection is not None:
        from core.context import get_lesson_context
        execution_input["Input"] = get_lesson_context(
            subsection, base_subject, chapter=chapter, section=section)
    return execution_input
