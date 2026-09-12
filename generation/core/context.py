import json
import os
import uuid
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Union

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, ConfigDict, Field, root_validator
from core.hash import hash_code
from core.lesson_plan import (get_chapter_lesson_plan,
                               get_section_lesson_plan,
                               get_subsection_lesson_plan,
                               get_unit_lesson_plan)
from core.path import (get_content_path, get_content_prompt_path, get_key,
                        get_lesson_plan_path)
from core.clients.s3 import (create_presigned_url, does_file_exist, download,
                      load_json_from_s3, upload_file_to_s3)


class Context(BaseModel):
    grade: str = None
    subject: str = None
    course: str = None
    curriculum: str = None
    category: str = None
    unit: str = None
    chapter: str = None
    section: str = None
    subsection: str = None
    concepts: Optional[Dict[str, Any] ]= None
    section_concepts: Optional[List[Any]] = None

    aliases: ClassVar[Dict[str, List[str]]] = {
        'grade': ['grade', 'GRADE'],
        'subject': ['subject', 'SUBJECT'],
        'course': ['course', 'COURSE'],
        'curriculum': ['curriculum', 'CURRICULUM'],
        'category': ['category', 'CATEGORY'],
        'unit': ['unit', 'UNIT_TITLE', 'unit_title'],
        'chapter': ['chapter', 'CHAPTER_TITLE', 'chapter_title'],
        'section': ['section', 'SECTION_TITLE', 'section_title'],
        'subsection': ['subsection', 'SUBSECTION_TITLE', 'subsection_title'],
        'concepts': ['concepts'],
        'section_concepts': ['section_concepts'],
    }

    @root_validator(pre=True)
    def assign_aliases(cls, values):
        new_values = {}
        for field_name, aliases in cls.aliases.items():
            for alias in aliases:
                if alias in values:
                    new_values[field_name] = values.pop(alias)
                    break 
        new_values.update(values)
        return new_values

    model_config = ConfigDict(
        populate_by_name=True
    )

    @property
    def lesson_plan(self):
        content_plan = load_json_from_s3(f"{self.curriculum}/{self.course}/{self.subject}/lesson_plan.json")
        content_plan = get_subsection_lesson_plan(
            self.unit, self.chapter, self.section, self.subsection, content_plan)
        return content_plan

    @property
    def key(self):
        return hash_code(get_key([self.unit, self.chapter, self.section, self.subsection]))

    @property
    def base_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/"

    @property
    def media_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/media/{self.key}/"

    @property
    def resources_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/resources/"

    def get_lesson_plan_path(self):
        return get_lesson_plan_path(self.course, self.curriculum, self.subject)

    def get_unit_lesson_plan(self, lesson_plan_data):
        return get_unit_lesson_plan(self.unit, lesson_plan_data)

    def get_chapter_lesson_plan(self, lesson_plan_data):
        return get_chapter_lesson_plan(self.unit, self.chapter, lesson_plan_data)

    def get_section_lesson_plan(self, lesson_plan_data):
        return get_section_lesson_plan(self.unit, self.chapter, self.section, lesson_plan_data)

    def get_subsection_lesson_plan(self, lesson_plan_data):
        return get_subsection_lesson_plan(
            self.unit, self.chapter, self.section, self.subsection, lesson_plan_data)

    @root_validator(pre=True)
    def load_content_plan(cls, values):
        if 'UNIT_LESSON_PLAN' in values and 'CHAPTER_TITLE' in values:
            unit_lesson_plan = json.loads(values['UNIT_LESSON_PLAN'])
            subsections = unit_lesson_plan['Chapters'].get(
                values['CHAPTER_TITLE'],
                {})['Sections'].get(
                values['SECTION_TITLE'],
                {})['Subsections']
            values['content_plan'] = json.loads(values.get('SUBSECTION_CONCEPTS', {}))
            values['concepts'] = {} #values['content_plan']
            values['section_concepts'] = []
        return values


class EMathContext(Context):
    @property
    def lesson_transcript_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Math Video Lesson/{self.key}.json"

    @property
    def review_problem_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Math Practice Section/{self.key}.json"

    @property
    def solutions_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Math Solution Key/{self.key}.json"

    @property
    def animations_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Math Animated Diagram/{self.key}.json"

    def wolfram_answer_path(self, problem):
        key = hash_code(get_key(problem.split()))
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Math Practice Section/Wolfram Answers/{self.key}-{key}.json"


class APVideoContext(Context):

    @property
    def content_plan_path(self):
        base = f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/content_plan/"
        if does_file_exist(base + f"{self.key}-edited.json"):
            # print("Using edited content_plan")
            return base + f"{self.key}-edited.json"
        else:
            # print("Using original content_plan")
            return base + f"{self.key}.json"

    @property
    def content_plan(self):
        content_plan_path = self.content_plan_path
        if not does_file_exist(content_plan_path):
            raise FileNotFoundError(f"File does not exist: {content_plan_path}")
        content_plan = load_json_from_s3(content_plan_path)
        return content_plan

    @property
    def subsection_contents_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Detailed content/{self.key}.json"

    def get_subsection_contents(self):
        contents = load_json_from_s3(self.subsection_contents_path)
        return contents['essay']

    @property
    def kg_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Knowledge Graph/{self.key}.json"
    
    @property
    def video_plan_path(self):
        base = f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Video Plan/"
        if does_file_exist(base + f"{self.key}-edited.json"):
            # print("Using edited transcript")
            return base + f"{self.key}-edited.json"
        else:
            # print("Using original transcript")
            return base + f"{self.key}.json"
        
    @property
    def transcripts_path(self):
        base = f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Video Transcript/"
        if does_file_exist(base + f"{self.key}-edited.json"):
            # print("Using edited transcript")
            return base + f"{self.key}-edited.json"
        else:
            # print("Using original transcript")
            return base + f"{self.key}.json"
        # return 

    @property
    def clips_path(self):
        base = f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Scenes Breakdown/"
        if does_file_exist(base + f"{self.key}-edited.json"):
            # print("Using edited clips")
            return base + f"{self.key}-edited.json"
        else:
            # print("Using original clips")
            return base + f"{self.key}.json"
    
    @property
    def avatar_assets_path(self):
        base = f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Avatar Clips/"
        if does_file_exist(base + f"{self.key}-edited.json"):
            # print("Using edited avatar assets")
            return base + f"{self.key}-edited.json"
        else:
            # print("Using original avatar assets")
            return base + f"{self.key}.json"
        
    @property
    def text_overlays_path(self):
        base = f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Text Overlays/"
        if does_file_exist(base + f"{self.key}-edited.json"):
            # print("Using edited text overlays ")
            return base + f"{self.key}-edited.json"
        else:
            # print("Using original text overlays ")
            return base + f"{self.key}.json"
        
    @property
    def metadata_path(self):
        base = f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/lesson_metadata"
        latest_file = f"{self.key}.json"

        version = 1
        while True:
            if does_file_exist(f"{base}/{self.key} - v{version}.json"):
                latest_file = f"{self.key} - v{version}.json"
                version += 1
            else:
                break

        return f"{base}/{latest_file}"

    @property
    def image_json_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Image Gen Clips/{self.key}.json"

    @property
    def video_json_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/Video Gen Clips/{self.key}.json"

    @property
    def shotstack_json_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/ShotStack/{self.key}.json"

    @property
    def context_pack_path(self):
        return f"{self.curriculum}/{self.course}/{self.subject}/contents/subsection/context_pack/{self.key}.json"


def update_src(html_string: str, root_s3_path: str = 'TEKS/Mathematics/Grade 5 Maths/') -> str:
    soup = BeautifulSoup(html_string, 'html.parser')
    for tag in soup.find_all(['img', 'audio', 'video']):
        if tag.has_attr('src'):
            subfolder = 'resources/' if (tag.name ==
                                         'img' and 'static-' in tag['src']) else 'images/' if tag.name == 'img' else 'media/'
            s3_path = root_s3_path + subfolder + os.path.basename(tag['src'])
            if not does_file_exist(s3_path):
                print(f"File does not exist: {s3_path}")
            else:
                presigned_url = create_presigned_url(s3_path)
                tag['src'] = presigned_url
    return str(soup)


def render_template(
        data: dict, template_path: str = './book/chapter/section/subsection/video/slides.html', root_s3_path: str = None,
        save: str = None) -> str:
    env = Environment(loader=FileSystemLoader('./templates'))
    env.globals['uuid4'] = uuid.uuid4
    html = env.get_template(template_path).render(**data)
    html_with_presigned_urls = update_src(html, root_s3_path)

    if save:
        with open(save, "w") as file:
            file.write(html_with_presigned_urls)

    return html_with_presigned_urls


def prep_content_gen_input(event: dict) -> dict:
    input = Context(**event.get("ExecutionInput"), **event.get("Input"))
    lesson_plan_path = input.get_lesson_plan_path()
    lesson_plan_data = load_json_from_s3(lesson_plan_path)

    unit_lesson_plan = input.get_unit_lesson_plan(lesson_plan_data)
    chapter_lesson_plan = input.get_chapter_lesson_plan(lesson_plan_data)
    section_lesson_plan = input.get_section_lesson_plan(lesson_plan_data)
    subsection_lesson_plan = input.get_subsection_lesson_plan(lesson_plan_data)
    placeholder_values = {
        "GRADE": input.grade,
        "SUBJECT": input.subject,
        "COURSE": input.course,
        "CURRICULUM": input.curriculum,
        "CATEGORY": input.category,
        "UNIT_TITLE": input.unit,
        "CHAPTER_TITLE": input.chapter,
        "SECTION_TITLE": input.section,
        "SUBSECTION_TITLE": input.subsection,
        "UNIT_LESSON_PLAN": json.dumps(unit_lesson_plan, indent=4),
        "UNIT_OBJECTIVE": unit_lesson_plan.get("Objective", ""),
        "CHAPTER_LESSON_PLAN": json.dumps(chapter_lesson_plan, indent=4),
        "CHAPTER_OBJECTIVE": chapter_lesson_plan.get("Objective", ""),
        "SECTION_LESSON_PLAN": json.dumps(section_lesson_plan, indent=4),
        "SECTION_OBJECTIVE": section_lesson_plan.get("Objective", ""),
        "SUBSECTION_OBJECTIVE": subsection_lesson_plan.get("Objective", ""),
        "SUBSECTION_CONCEPTS": json.dumps(subsection_lesson_plan.get("ContentPlan", []), indent=4),
        "SUBSECTION_CONTENT": "json.dumps(content, indent=4)",
        "THINKING_SKILL": subsection_lesson_plan.get("Thinking Skill", "")
    }
    return placeholder_values

def get_lesson_context(subsection: str, subject: str = "AP World History", chapter: Optional[str] = None,  section: Optional[str] = None):
    subject = subject.split('-')[0].strip()
    if subject=="AP US History":
        lesson_plan = load_json_from_s3('college_board/AP US History: Video Lessons/AP US History - v0/lesson_plan.json')
    else:
        lesson_plan = load_json_from_s3('college_board/AP World History: Video Lessons 2/AP World History - v2/lesson_plan.json')
    for unit_title, unit in lesson_plan["Units"].items():
        for chapter_title, chapter_details in unit["Chapters"].items():
            if chapter and chapter_title != chapter:
                continue
            for section_title, section_details in chapter_details["Sections"].items():
                if section and section_title != section:
                    continue
                for subsection_title in section_details["Subsections"].keys():
                    if subsection_title == subsection:
                        return dict(
                            unit=unit_title,
                            chapter=chapter_title,
                            section=section_title,
                            subsection=subsection_title
                        )