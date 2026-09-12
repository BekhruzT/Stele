import os
from pathlib import Path

from core.hash import hash_code, hash_image_description


def get_temp_dir():
    return "/tmp"


def get_local_dir(course, curriculum, subject):
    return f"/tmp/{curriculum}/{course}/{subject}"


def get_local_image_dir(course, curriculum, subject):
    return os.path.join(get_local_dir(course, curriculum, subject), "images")


def get_lesson_plan_path(course, curriculum, subject):
    return f"{curriculum}/{course}/{subject}/lesson_plan.json"


def get_lesson_plan_prompt_path(course, curriculum, subject, output_type, filename):
    return f"{curriculum}/{course}/{subject}/lesson-plan/prompts/{output_type}/{filename}"


def get_lesson_plan_content_path(course, curriculum, subject, output_type, file_name):
    return f"{curriculum}/{course}/{subject}/lesson-plan/{output_type}/{file_name}"


def get_content_path(course, curriculum, subject, granularity, file_name):
    if Path(file_name).suffix == "":
        file_name = file_name + ".txt"

    return f"{curriculum}/{course}/{subject}/contents/{granularity}/{file_name}"


def get_content_prompt_path(course, curriculum, subject, granularity, file_name):
    if Path(file_name).suffix == "":
        file_name = file_name + ".txt"

    return f"{curriculum}/{course}/{subject}/prompts/{granularity}/{file_name}"


def get_image_dir(course, curriculum, subject):
    return f"{curriculum}/{course}/{subject}/images"


def get_image_details_path(course, curriculum, subject):
    return f"{curriculum}/{course}/{subject}/image_details.json"


def get_pdf_path(course, curriculum, subject, file_name):
    return f"{curriculum}/{course}/{subject}/pdfs/{file_name}"


def get_dir(course, curriculum, subject):
    return f"{curriculum}/{course}/{subject}"


def get_key(titles):
    return "-".join(titles)


def get_guidelines_path(course, curriculum, subject):
    return os.path.join(get_dir(course, curriculum, subject), "guidelines.json")


def get_full_guidelines_path():
    return "static/guidelines/default.json"


def get_image_name(image_description):
    hashed_image_description = hash_image_description(image_description)
    image_name = f"{hashed_image_description}.png"
    return image_name


def get_image_path(course, curriculum, subject, image_description):
    return os.path.join(get_image_dir(course, curriculum, subject), get_image_name(image_description))


def get_local_image_path(course, curriculum, subject, image_description):
    image_name = get_image_name(image_description)
    return os.path.join(get_local_image_dir(course, curriculum, subject), image_name)


def get_analysis_dir(request_id):
    return os.path.join("analysis", request_id)


def get_index_persist_dir(request_id, chapter):
    return os.path.join(get_analysis_dir(request_id), chapter, "storage")


def get_analysis_result_path(request_id, chapter, filename):
    return os.path.join(get_analysis_dir(request_id), chapter, filename)


def get_fixed_content_path(path, prefix=None):
    dirname = os.path.dirname(path)
    basename = os.path.basename(path)
    return os.path.join(dirname, f"fixed-{basename}") if prefix is None else os.path.join(dirname, f"{prefix}-fixed-{basename}")
