import csv
import os
from core.parsers import str_2_json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Tuple, Any, Union
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pydantic import BaseModel, Field, validator, root_validator
from core.clients.openai import LLM, llm_complete, user_message, system_message
from core.types import LessonMetadata, KeyConcept
from core.helpers import print_json, extract_tag_content, cache_to_json
from core.context import APVideoContext
from core.clients.s3 import does_file_exist, get_last_modified_time, load_json_from_s3, list_files_in_directory, save_json_to_s3
from prompts.utility_prompts import CLASSIFY_KEY_CONCEPT_CHANGE_TYPE, CLASSIFY_PHRASE_CHANGE_TYPE, CREATE_KEY_PHRASE_SYSTEM_PROMPT, UPDATE_KEY_PHRASE_SYSTEM_PROMPT, EDIT_KEY_PHRASE_USER_PROMPT, EDIT_KEY_CONCEPT_USER_PROMPT, UPDATE_KEY_CONCEPT_SYSTEM_PROMPT
from ops.feedback.curate_transcripts import process_lessons
from core.clients.sheets import get_google_creds, upload_csv_to_gsheet, get_dataframe_from_sheet, fetch_all_comments, find_cell_coordinates, to_excel_coordinates, note_over_cell, save_dicts_to_csv, color_cell
import json
import html
from core.path import get_key
from core.hash import hash_code
import pandas as pd
from enum import Enum
import gspread
import string


class ChangeType(Enum):
    CREATE = "Create"
    UPDATE = "Update"
    DELETE = "Delete"
    NONLOCAL = "NonLocal"
    NOCHANGE = "NoChange"
    
    @classmethod
    def _missing_(cls, value): # case insensitive match
        if not isinstance(value, str):
            return None
        value_lower = value.lower()
        for member in cls:
            if member.value.lower() == value_lower:
                return member
        return None 

class SubsectionContext(BaseModel):
    unit: str
    chapter: str
    section: str
    subsection: str
    key: str = None

    @root_validator(pre=True)
    def set_key(cls, values):
        unit, chapter, section, subsection = (
            values.get('unit', 'Unit'),
            values['chapter'],
            values['section'],
            values['subsection']
        )
        values['key'] = hash_code(get_key([unit, chapter, section, subsection]))
        return values

class Keyphrase(BaseModel):
    phrase: str
    edited_phrase: Optional[str] = ""
    was_edited: Optional[bool] = False
    feedback: Optional[str] = ""
    change_type: Optional[str] = None
    final: Optional[str] = ""

class KeyConcept(BaseModel):
    title: str
    learning_objectives: List[str]
    key_phrases: List[Keyphrase] = Field(default_factory=list)
    edited_title: Optional[str] = ""
    was_edited: Optional[bool] = False
    feedback: Optional[str] = ""
    change_type: Optional[str] = None
    final: Optional[str] = None

    @validator('key_phrases', pre=True, each_item=True)
    def convert_keyphrases(cls, v):
        if isinstance(v, str):
            return Keyphrase(phrase=v)
        return v

class LessonMetadata(BaseModel):
    context: SubsectionContext
    lesson_title: str
    boundaries_and_purpose: str = ''
    perspective_guidance: str = ''
    key_concepts: List[KeyConcept]
    status: str = 'Awaiting Review'

units_by_subject = {
    'AP Biology': 'Biology',
    'AP US History': "American History",
    "AP World History": "World History"
}

def get_latest_version(files, base_name):
    latest_file = max(filter(lambda f: f.startswith(f"{base_name} - v"), files), default = None)
    return latest_file or (f"{base_name}.json" if f"{base_name}.json" in files else None)

def next_version(filename: str)->str:
    base, ext = filename.split('.')
    if ' - v' in base:
        base, version = base.rsplit(' - v', 1)
        next_version = int(version) + 1
    else:
        next_version = 1
    return f"{base} - v{next_version}.{ext}"

def classify_key_concept_change_requested(key_concept: KeyConcept) -> ChangeType:
    return ChangeType.NOCHANGE
    key_concept_dict = {
        'title': key_concept.title,
        'key_phrases': [phrase.phrase for phrase in key_concept.key_phrases]
    }
    messages = [
        system_message(CLASSIFY_KEY_CONCEPT_CHANGE_TYPE),
        user_message(f"<comment>\n{key_concept.feedback}\n</comment>\n\n<key_concept>\n{json.dumps(key_concept_dict, indent=2)}\n</key_concept>")
    ] 
    response = llm_complete(messages, model=LLM.ANTHROPIC_CLAUDE_3_5_SONNET)
    return ChangeType(extract_tag_content('classification', response))

def classify_change_requested(comment: str, key_phrase: str) -> ChangeType:
    messages = [
        system_message(CLASSIFY_PHRASE_CHANGE_TYPE),
        user_message(f"<comment>\n{comment}\n</comment>\n\n<key_concept>\n{key_phrase}\n</key_concept>")
    ] 
    response = llm_complete(messages, model=LLM.ANTHROPIC_CLAUDE_3_5_SONNET)
    return ChangeType(extract_tag_content('classification', response))

def update_key_concept(lesson_metadata: LessonMetadata, key_concept: KeyConcept) -> KeyConcept:
    return key_concept
    metadata = [{
        'title': section.title,
        'key_phrases': [p.edited_phrase for p in section.key_phrases]
    } for section in lesson_metadata.key_concepts]
    messages = [
        system_message(UPDATE_KEY_CONCEPT_SYSTEM_PROMPT.format(
            subsection_title=lesson_metadata.lesson_title, 
            metadata=json.dumps(metadata, indent=2)
        )),
        user_message(EDIT_KEY_CONCEPT_USER_PROMPT.format(
            feedback = key_concept.feedback, key_concept={'title': key_concept.title, 'key_phrases': [p.edited_phrase for p in key_concept.key_phrases]}
        ))
    ] 
    response = llm_complete(messages, model=LLM.ANTHROPIC_CLAUDE_3_5_SONNET)
    response = str_2_json(extract_tag_content('updated_key_concepts', response))

    empty_phrase = Keyphrase(phrase='').dict()
    key_concept.final = response['title']
    key_concept.key_phrases = [
        Keyphrase(
            **{
                **(key_concept.key_phrases[ii].dict() if ii < len(key_concept.key_phrases) else empty_phrase),
                'final': final,
                'feedback': f'Section feedback was: {key_concept.feedback}',
                'was_edited': final != (key_concept.key_phrases[ii].edited_phrase if ii < len(key_concept.key_phrases) else ''),
            }
        ) for ii, final in enumerate(response['key_phrases'])
    ]
    return key_concept

def create_key_concept(lesson_metadata: LessonMetadata, key_concept: KeyConcept) -> KeyConcept:
    pass

def update_key_phrase(key_concept: KeyConcept, keyphrase: Keyphrase) -> str:
    messages = [
        system_message(UPDATE_KEY_PHRASE_SYSTEM_PROMPT.format(
            section_title=key_concept.title, 
            section_phrases=json.dumps([p.edited_phrase for p in key_concept.key_phrases], indent=2)
        )),
        user_message(EDIT_KEY_PHRASE_USER_PROMPT.format(
            feedback = keyphrase.feedback, key_phrase=keyphrase.edited_phrase
        ))
    ] 
    response = llm_complete(messages, model=LLM.ANTHROPIC_CLAUDE_3_5_SONNET)
    return extract_tag_content('updated_key_phrase', response)

def create_key_phrase(key_concept: KeyConcept, keyphrase: Keyphrase) -> str:
    # return -1, keyphrase.edited_phrase
    messages = [
        system_message(CREATE_KEY_PHRASE_SYSTEM_PROMPT.format(
            section_title=key_concept.title, 
            section_phrases=json.dumps([p.edited_phrase for p in key_concept.key_phrases], indent=2)
        )),
        user_message(EDIT_KEY_PHRASE_USER_PROMPT.format(
            feedback = keyphrase.feedback, key_phrase=keyphrase.edited_phrase
        ))
    ]
    response = llm_complete(messages, model=LLM.ANTHROPIC_CLAUDE_3_5_SONNET)
    response_json = str_2_json(extract_tag_content('new_key_phrase', response))
    return -1 if response_json['placement'].lower()=='before' else 1, response_json['key_phrase']

@cache_to_json(LessonMetadata)
def get_cleaned_metadata_from_sheet(context: APVideoContext, sheet_id: str, sheet_name: str) -> Dict[str, LessonMetadata]:
    df = get_dataframe_from_sheet(sheet_id, sheet_name)
    lesson_metadata_list = {}
    for index, row in df.iterrows():
        lesson_title = str(row.get('Lesson-Title', '')).strip()
        
        context_object = SubsectionContext(
            unit=units_by_subject[context.subject.split(' -')[0]],
            chapter= str(row.get('Chapter', row.get('Domain', ''))).strip(),
            section=str(row.get('Section', row.get('Cluster', ''))).strip(),
            subsection=str(row.get('Subsection', row.get('Standard', ''))).strip()
        )
        if not context_object.chapter or not context_object.section or not context_object.subsection:
            continue

        key_concepts = []
        for i in range(1, 17):
            section_title_column = f'Section-Title-{i}'
            section_title = str(row.get(section_title_column, '')).strip()
            if not section_title:
                continue

            key_phrases = []
            for j in range(1, 17):
                key_phrase_column = f'Key-Phrase-{i}-{j}'
                key_phrase = str(row.get(key_phrase_column, '')).strip()

                if key_phrase:
                    key_phrase_object = Keyphrase(phrase=key_phrase)
                    key_phrases.append(key_phrase_object)

            if not key_phrases:
                continue

            key_concepts.append(KeyConcept(
                title=section_title,
                learning_objectives=[],
                key_phrases=key_phrases
            ))

        if not key_concepts:
            continue

        # Create LessonMetadata object
        lesson_metadata = LessonMetadata(
            context=context_object,
            lesson_title=lesson_title,
            boundaries_and_purpose='',  # Assuming not provided
            perspective_guidance='',    # Assuming not provided
            key_concepts=key_concepts,
            status=row.get('Status', 'Awaiting Review')
        )

        lesson_metadata_list[lesson_metadata.context.key] = lesson_metadata
    return lesson_metadata_list

@cache_to_json(LessonMetadata)
def process_lessons(context: APVideoContext) -> Dict[str, LessonMetadata]:
    lesson_plan = load_json_from_s3(context.get_lesson_plan_path())

    lesson_metadata = {}
    metadata_base_path = f"{context.curriculum}/{context.course}/{context.subject}/contents/subsection/lesson_metadata"

    metadata_files = list_files_in_directory(f'{metadata_base_path}/', 'file')
    for unit_title, unit_lesson_plan in lesson_plan.get("Units", {}).items():
        for chapter_title, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
            # if chapter_title not in ['The Global Tapestry']:
            #     continue
            for section_title, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
                for subsection_title, subsection_lesson_plan in section_lesson_plan.get("Subsections", {}).items():
                    ids = {k:v for k,v in subsection_lesson_plan.items() if k in ['DomainId', 'ClusterId', 'StandardId']}
                    subsection_context = SubsectionContext(unit=unit_title, chapter=chapter_title, section=section_title, subsection=subsection_title)
                    latest_metadata_file = get_latest_version(metadata_files, subsection_context.key)
                    print(f"Latest Metadata File for Topic: {subsection_title[:40]} => {latest_metadata_file}")
                    if latest_metadata_file is None:
                        continue
                    metadata_path = f"{metadata_base_path}/{latest_metadata_file}"
                    lesson_metadata[subsection_context.key] = LessonMetadata(
                        context=subsection_context,
                        ids = ids,
                        **load_json_from_s3(metadata_path)['lesson_metadata']
                    )
    return lesson_metadata

@cache_to_json(LessonMetadata)
def read_sheet_edits(metadata: Dict[str, LessonMetadata], edited_metadata: Dict[str, LessonMetadata]) -> Dict[str, LessonMetadata]:
    for key, original_lm in metadata.items():
        edited_lm = edited_metadata.get(key, None)
        original_lm.status = edited_lm.status if edited_lm is not None else original_lm.status
               
        for ii, original_kc in enumerate(original_lm.key_concepts):
            original_kc.edited_title = edited_lm.key_concepts[ii].title if edited_lm is not None else original_kc.title
            original_kc.was_edited = original_kc.title != original_kc.edited_title
            
            if edited_lm is not None:
                num_kp_original, num_kp_edited = len(original_kc.key_phrases), len(edited_lm.key_concepts[ii].key_phrases)
                if num_kp_original < num_kp_edited:
                    for _ in range(num_kp_edited - num_kp_original):
                        original_kc.key_phrases.append(Keyphrase(phrase=''))
                elif num_kp_original > num_kp_edited:
                    original_kc.key_phrases = original_kc.key_phrases[:num_kp_edited]
            
            for jj, original_kp in enumerate(original_kc.key_phrases):
                original_kp.edited_phrase = edited_lm.key_concepts[ii].key_phrases[jj].phrase if edited_lm is not None else original_kp.phrase
                original_kp.was_edited = original_kp.phrase != original_kp.edited_phrase
    return metadata

@cache_to_json(LessonMetadata)
def read_in_cell_comments(metadata: Dict[str, LessonMetadata], comments: List[Dict]) -> Dict[str, LessonMetadata]:
    cell_content_to_comment = {}
    for comment in comments:
        quoted_content = comment.get('quotedFileContent', {}).get('value', '')
        # Unescape HTML entities in the cell content
        unescaped_content = html.unescape(quoted_content).strip()
        # Get the comment content
        comment_content = comment.get('htmlContent', '').strip()
        if unescaped_content:
            # If multiple comments exist for the same cell content, concatenate them
            if unescaped_content in cell_content_to_comment:
                cell_content_to_comment[unescaped_content] += f"\n{comment_content}"
            else:
                cell_content_to_comment[unescaped_content] = comment_content

    # Keep track of which comments have been matched
    matched_comments = set()
    # print_json(cell_content_to_comment)
    # Now, for each KeyConcept and KeyPhrase in metadata, update the feedback if there's a matching comment
    for key, lesson in metadata.items():
        for key_concept in lesson.key_concepts:
            # Unescape the edited_title to match the unescaped cell content
            unescaped_edited_title = html.unescape(key_concept.title).strip()
            # Check if there's a matching comment
            if unescaped_edited_title in cell_content_to_comment:
                key_concept.feedback = cell_content_to_comment[unescaped_edited_title]
                key_concept.change_type = classify_key_concept_change_requested(key_concept).value
                # Mark this comment as matched
                matched_comments.add(unescaped_edited_title)
            for key_phrase in key_concept.key_phrases:
                # Unescape the edited_phrase to match the unescaped cell content
                unescaped_edited_phrase = html.unescape(key_phrase.edited_phrase).strip()

                # Check if there's a matching comment
                if unescaped_edited_phrase in cell_content_to_comment:
                    key_phrase.feedback = cell_content_to_comment[unescaped_edited_phrase]
                    key_phrase.change_type = classify_change_requested(key_phrase.feedback, key_phrase.edited_phrase).value
                    matched_comments.add(unescaped_edited_phrase)
                    print(f"Adding edited feedback: {key_phrase.feedback}")
            for key_phrase in key_concept.key_phrases:
                # Unescape the edited_phrase to match the unescaped cell content
                unescaped_origin_phrase = html.unescape(key_phrase.phrase).strip()
                unescaped_edited_phrase = html.unescape(key_phrase.edited_phrase).strip()
                # Check if there's a matching comment
                if (unescaped_origin_phrase in cell_content_to_comment) and (unescaped_origin_phrase not in matched_comments):
                    key_phrase.feedback = cell_content_to_comment[unescaped_origin_phrase]
                    key_phrase.change_type = classify_change_requested(key_phrase.feedback, key_phrase.edited_phrase).value
                    matched_comments.add(unescaped_origin_phrase)
                    print(f"Adding original feedback: {key_phrase.feedback}.")
                # If there's no match, leave the feedback as is (empty or existing value)

    # Identify comments that were not matched to any content
    unmatched_comments = set(cell_content_to_comment.keys()) - matched_comments

    # Report unmatched comments
    for unmatched_content in unmatched_comments:
        comment_text = cell_content_to_comment[unmatched_content]
        print(f"Warning: Comment '{comment_text}' on cell content '{unmatched_content}' could not be assigned to any content.")
    return metadata

@cache_to_json(LessonMetadata)
def process_keyphrases(metadata: Dict[str, LessonMetadata]) -> Dict[str, LessonMetadata]:
    for key, lesson in metadata.items():
        new_key_concepts = []
        for key_concept in lesson.key_concepts:
            if key_concept.change_type == 'Delete':
                key_concept.final = key_concept.edited_title or key_concept.title
                # key_concept.final = ""
                # key_concept.key_phrases = []
            elif key_concept.change_type == 'Create':
                key_concept.final = key_concept.edited_title or key_concept.title
                # key_concept = update_key_concept(lesson, key_concept)
                # is_before, new_key_concept = create_key_concept(lesson, key_concept)
                # key_concept = [new_key_concept, key_concept] if is_before else [key_concept, new_key_concept]
            elif key_concept.change_type == 'Update':
                key_concept.final = key_concept.edited_title or key_concept.title
                # key_concept = update_key_concept(lesson, key_concept)
            else:
                key_concept.final = key_concept.edited_title or key_concept.title
                # Process key phrases as before
                key_phrases = key_concept.key_phrases
                new_key_phrases = []
                for key_phrase in key_phrases:
                    if key_phrase.change_type == 'Delete':
                        key_phrase.final = ''
                    elif key_phrase.change_type == 'Create':
                        insert_where, final_phrase = create_key_phrase(key_concept, key_phrase)
                        new_kp = Keyphrase(phrase='', was_edited=True, feedback=f"Created based on feedback: '{key_phrase.feedback}'",
                                            final=final_phrase, change_type='Create')
                        key_phrase.final = key_phrase.edited_phrase
                        key_phrase = [new_kp, key_phrase] if insert_where == -1 else [key_phrase, new_kp]
                    elif key_phrase.change_type == 'Update':
                        key_phrase.final = update_key_phrase(key_concept, key_phrase)
                    else:
                        key_phrase.final = key_phrase.edited_phrase
                    if isinstance(key_phrase, list):
                        new_key_phrases.extend(key_phrase)
                    else:
                        new_key_phrases.append(key_phrase)
                key_concept.key_phrases = new_key_phrases
            new_key_concepts.append(key_concept)
        lesson.key_concepts = new_key_concepts

    return metadata

def upload_lesson_metadata_to_sheet(metadata: Dict[str, LessonMetadata], spreadsheet_id: str, sheet_name: str):
    max_key_phrases = 16
    max_key_concepts = 16
    # Prepare data with dynamic headers
    sheet_data = []
    n_headers = 5
    for ii, (key, data) in enumerate(metadata.items()):
        row = {
            'Status': data.status,
            'Chapter': data.context.chapter,
            'Section': data.context.section,
            'Subsection': data.context.subsection,
            'Lesson-Title': data.lesson_title
        }

        for jj in range(max_key_concepts):
            if jj < len(data.key_concepts):
                concept = data.key_concepts[jj]
                row[f'Section-Title-{jj+1}'] = concept.final or concept.title
                if concept.change_type is not None:
                    col_ = 5 + jj*max_key_phrases + jj # Adjust column index for concept titles
                    row_ = ii + 2
                    print(f"{col_}{row_} For key concept: {concept.title}")
                    note_over_cell(spreadsheet_id, f"Feedback: {concept.feedback}", sheet_name, col_, row_)
                    color = 'red' if concept.change_type == 'Delete' else 'blue' if concept.change_type == 'Update' else 'green' if concept.change_type == 'Create' else ''
                    if color:
                        color_cell(spreadsheet_id, sheet_name, col_, row_, color, 0.7)

                key_phrases = concept.key_phrases
                phrase_index = 1

                for kk in range(max_key_phrases):
                    if kk < len(key_phrases):
                        phrase = key_phrases[kk]
                        row[f'Key-Phrase-{jj+1}-{kk+1}'] = phrase.final or phrase.phrase
                        if phrase.change_type is not None:
                            col_ = 6 + jj*max_key_phrases + kk + jj
                            row_ = ii + 2
                            print(f"{col_}{row_} For key phrase: {phrase.final}")
                            note_over_cell(spreadsheet_id, f"Original Phrase: {phrase.phrase}\nFeedback: {phrase.feedback}", sheet_name, col_, row_)
                            color = 'red' if phrase.change_type == 'Delete' else 'blue' if phrase.change_type == 'Update' else 'green' if phrase.change_type == 'Create' else 'yellow' if phrase.change_type == 'NonLocal' else ''
                            if color:
                                color_cell(spreadsheet_id, sheet_name, col_, row_, color, 0.7)
                    else:
                        row[f'Key-Phrase-{jj+1}-{kk+1}'] = ''
            else:
                row[f'Section-Title-{jj+1}'] = ''
                for kk in range(max_key_phrases):
                    row[f'Key-Phrase-{jj+1}-{kk+1}'] = ''

        sheet_data.append(row)

    save_dicts_to_csv(sheet_data, '/tmp/tmp.csv')
    upload_csv_to_gsheet('/tmp/tmp.csv', spreadsheet_id, sheet_name)
    return sheet_data

def upload_edited_metadata_to_s3(context: APVideoContext, metadata: Dict[str, LessonMetadata], edited_metadata: Dict[str, LessonMetadata], version: Optional[int] = None):
    metadata_base_path = f"{context.curriculum}/{context.course}/{context.subject}/contents/subsection/lesson_metadata"
    metadata_files = list_files_in_directory(f'{metadata_base_path}/', 'file')
 
    for key, edited_meta in edited_metadata.items():
        original_meta = metadata.get(key)
        if original_meta is None:
            print(f"No original metadata found for key: {key}, skipping.")
            continue  # Skip if there is no matching original metadata

        edited_meta.boundaries_and_purpose = original_meta.boundaries_and_purpose
        edited_meta.perspective_guidance = original_meta.perspective_guidance

        for ii, (key_concept, key_concept_edited) in enumerate(zip(original_meta.key_concepts, edited_meta.key_concepts)):
            edited_meta.key_concepts[ii].learning_objectives = key_concept.learning_objectives
        lesson_metadata_cleaned = {
            k: v if k != 'key_concepts' else [
                {
                    kk: vv if kk != 'key_phrases' else [
                        key_phrase['final'] if key_phrase['final'] else key_phrase['edited_phrase'] if key_phrase['edited_phrase'] else key_phrase['phrase']
                        for key_phrase in vv
                    ]
                    for kk, vv in key_concept.items()
                    if kk not in {'edited_title', 'was_edited', 'feedback', 'change_type', 'final'}
                }
                for key_concept in v
            ]
            for k, v in edited_meta.model_dump().items() if k != 'context'
        }
        metadata_json = {"lesson_metadata": lesson_metadata_cleaned}
        
        if version is None:
            latest_metadata_file = get_latest_version(metadata_files, key)
            new_file_version = next_version(latest_metadata_file)
        else:
            new_file_version = f"{key} - v{version}.json"
        metadata_s3_path = f"{metadata_base_path}/{new_file_version}"

        save_json_to_s3(metadata_json, metadata_s3_path)
        print(f"Uploaded edited metadata for key: {key} to {metadata_s3_path}")

def main(event):
    input_context = APVideoContext(**event.get("ExecutionInput"), **event.get("Input"))
    spreadsheet_id, sheet_name = event['sheet_id'], event['sheet_name']
    
    lesson_metadata_sheet = get_cleaned_metadata_from_sheet(input_context, spreadsheet_id, sheet_name)
    lesson_metadata = process_lessons(input_context)

    lesson_metadata = read_sheet_edits(lesson_metadata, lesson_metadata_sheet)
    comments = fetch_all_comments(spreadsheet_id, start_date=event['start_time'])
    lesson_metadata = read_in_cell_comments(lesson_metadata, comments)
    lesson_metadata = process_keyphrases(lesson_metadata)
    upload_lesson_metadata_to_sheet(lesson_metadata, spreadsheet_id, "Metadata - v...")
    # upload_edited_metadata_to_s3(input_context, lesson_metadata, lesson_metadata_sheet, 1)

if __name__ == "__main__":
    event = {
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP Biology: Video Lessons",
            "grade": "Grade 11",
            "subject": "AP Biology",
            "category": "Biology"
        },
        "Input": {},
        "sheet_id": "1etkGvcq7kuaBW5rVEvH2SeCJ-6MWK9m_REOn6glZlFE",
        'sheet_name': 'Metadata - v2',
        'start_time': '2024-11-05T13:00:00'
    }
    main(event)