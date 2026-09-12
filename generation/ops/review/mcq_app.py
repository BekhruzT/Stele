import os
import streamlit as st
from typing import Dict, List, Optional
from pydantic import BaseModel
import json
from core.types import (
    TranscriptOutput, MCQ, MCQOption, Context, VideoPlan)
from stages.transcript import generate_questions
from core.helpers import get_topics_list
from core.context import prep_content_gen_input
from core.clients.s3 import load_json_from_s3, does_file_exist

@st.cache_data
def fetch_mcqs(context):
    context = Context(**context)
    if not does_file_exist(context.transcripts_path):
        st.error("Transcript file not found!")
        return
    raw_data = load_json_from_s3(context.transcripts_path)
    transcript_output = TranscriptOutput(**raw_data)
    if not transcript_output.supplementary_content or not transcript_output.supplementary_content.questions:
        st.write("No MCQs found in this transcript.")
        return
    questions_data = transcript_output.supplementary_content.questions

    return questions_data

def render_landing_page(execution_input: dict):
    st.title("Select Topic")
    curriculum_data = get_topics_list(execution_input)
    units = list(curriculum_data["Units"].keys())
    st.subheader("Select Unit")
    selected_unit = st.selectbox("Select Unit", options=units, key='unit_select')
    if selected_unit:
        chapters = list(curriculum_data["Units"][selected_unit]["Chapters"].keys())
        st.subheader("Select Chapter")
        selected_chapter = st.selectbox("Select Chapter", options=chapters, key='chapter_select')
        if selected_chapter:
            sections = list(curriculum_data["Units"][selected_unit]["Chapters"][selected_chapter]["Sections"].keys())
            st.subheader("Select Section")
            selected_section = st.selectbox("Select Section", options=sections, key='section_select')
            if selected_section:
                subsections = curriculum_data["Units"][selected_unit]["Chapters"][selected_chapter]["Sections"][selected_section]
                st.subheader("Select Subsection - L1")
                for idx, subsection in enumerate(subsections):
                    cols = st.columns([9,1])
                    with cols[0]:
                        st.write(subsection)
                    with cols[1]:
                        if st.button("✏️", key=f"generate_{idx}"):
                            input_dict = {
                                "unit": selected_unit,
                                "chapter": selected_chapter,
                                "section": selected_section,
                                "subsection": subsection
                            }
                            data = {
                                "ExecutionInput": execution_input,
                                "Input": input_dict
                            }
                            context = prep_content_gen_input(data)
                            st.session_state['context'] = context
                            st.session_state['start_mcqs'] = True
                            st.session_state['current_section_index'] = 0
                            # Initialize the user selections with empty dictionaries
                            st.session_state['user_selections'] = {}
                            st.session_state['question_answered'] = {}
                            st.rerun()
                    st.markdown('---')

def render_mcqs_page(questions_data: Dict[str, Dict[str, List[MCQ]]]):
    all_sections = list(questions_data.keys())
    if 'current_section_index' not in st.session_state:
        st.session_state['current_section_index'] = 0
    current_section_index = st.session_state['current_section_index']
    if current_section_index >= len(all_sections):
        st.write("No further sections available.")
        return
    current_section = all_sections[current_section_index]
    st.title(f"MCQs for Section: {current_section}")
    concepts_dict = questions_data[current_section]
    
    # Initialize user selections dict if not exists
    if 'user_selections' not in st.session_state:
        st.session_state['user_selections'] = {}
    
    if 'question_answered' not in st.session_state:
        st.session_state['question_answered'] = {}
    
    for concept, mcqs_for_that_concept in concepts_dict.items():
        if len(mcqs_for_that_concept) > 0:
            transcript_str = mcqs_for_that_concept[0].transcript
            if transcript_str:
                st.markdown(f"**Transcript**: {transcript_str}")
        for mcq_index, mcq in enumerate(mcqs_for_that_concept):
            st.markdown("---")
            question_key = f"{current_section}_{concept}_q_{mcq_index}"
            st.markdown(f"**{mcq.question}**")
            
            # Initialize this question's state if needed
            if question_key not in st.session_state['question_answered']:
                st.session_state['question_answered'][question_key] = False
            
            # Process the user interactions with checkboxes
            for opt in mcq.answer_options:
                option_id = opt.id
                checkbox_key = f"{question_key}_{option_id}"
                
                # Initialize selection state for this option if needed
                if checkbox_key not in st.session_state['user_selections']:
                    st.session_state['user_selections'][checkbox_key] = False
                
                # Set up columns for layout
                cols = st.columns([0.5, 9.5])
                
                with cols[0]:
                    # Use the checkbox with the stored state and update the state on change
                    checkbox_value = st.checkbox(
                        "Option", label_visibility="collapsed",
                        value=st.session_state['user_selections'][checkbox_key],
                        key=checkbox_key,
                        on_change=lambda key=checkbox_key, qkey=question_key: handle_checkbox_change(key, qkey)
                    )
                
                with cols[1]:
                    st.write(opt.answer)
                    
                    # Show explanation if the question has been answered
                    if st.session_state['question_answered'][question_key]:
                        color = "green" if opt.correct else "red"
                        st.markdown(
                            f"<div style='border-left: 4px solid {color}; padding-left: 10px; margin: 5px 0;'>"
                            f"<em style='color:{color};'>{opt.explanation}</em>"
                            f"</div>",
                            unsafe_allow_html=True
                        )
        st.markdown("---")
    
    if st.button("Next Section"):
        st.session_state['current_section_index'] += 1
        st.rerun()

def handle_checkbox_change(checkbox_key, question_key):
    # Update the selection state for this checkbox
    st.session_state['user_selections'][checkbox_key] = not st.session_state['user_selections'][checkbox_key]
    
    # Mark the question as answered if any option is selected
    if st.session_state['user_selections'][checkbox_key]:
        st.session_state['question_answered'][question_key] = True

def main():
    execution_input = {
        "curriculum": "college_board",
        "course": "AP World History: Video Lessons 2",
        "grade": "Grade 11",
        "subject": "AP World History - vUnit_8_new",
        "category": "High School: AP World History: Modern"
    }
    if 'start_mcqs' in st.session_state and st.session_state['start_mcqs']:
        context = st.session_state['context']
        context = Context(**context)
        if not does_file_exist(context.transcripts_path):
            st.error("Transcript file not found!")
            return
        
        # Use the cached function to fetch MCQs
        mcqs = fetch_mcqs(context.model_dump())
        render_mcqs_page(mcqs)
    else:
        render_landing_page(execution_input)

if __name__ == "__main__":
    main()