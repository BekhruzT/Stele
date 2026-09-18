import asyncio
import datetime
import gc
import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple, Union

import requests
import streamlit as st
from core.types import (
    Clip, ImageDetails, ImagesMetadata, LayerName, LessonContextPack, Media,
    OverlaysData, TitleOverlayType, TranscriptTiming, VideoMetadata)
from core.media.clip_timings import \
    match_snippet_timings
from core.log import (
    ContextAwareThreadPoolExecutor, LoggingContext, setup_logging,
    with_logging_context)
from core.helpers import (
    construct_phrases, exception_handler, extract_tag_content, get_topics_list,
    print_json)
from stages.avatar_clips import \
    generate_avatar_assets
from stages.scenes_breakdown import \
    generate_clips
from stages.image_clips import (
    generate_all_images, regenerate_image, set_best_image_qc_choice)
from stages.local_render import \
    render_lesson as generate_lesson_video
from stages.text_overlays import \
    generate_text_overlays
from stages.transcript import generate_lesson_transcript
from stages.video_clips import (
    generate_all_videos, process_generate_ai_video)
from core.clients.images import GeneratedImageTypes
from streamlit.runtime import Runtime
from streamlit.runtime.app_session import AppSession
from streamlit.runtime.scriptrunner import (add_script_run_ctx,
                                            get_script_run_ctx)
from core.context import APVideoContext as Context
from core.clients.s3 import (copy_s3_object, create_presigned_url, does_file_exist,
                      download, load_json_from_s3, read_content_from_s3,
                      save_json_to_s3, upload_file_to_s3)


def initialize_logger():
    if 'logger_initialized' not in st.session_state:
        setup_logging(cloudwatch=True)
        st.session_state.logger_initialized = True
    return logging.getLogger(__name__)

logger = initialize_logger()

class BaseLayer(ABC):
    def __init__(self, context: Context):
        self.context = context

    @abstractmethod
    def get_inputs(self) -> dict:
        """
        Fetches input data for the layer.

        Returns:
            Dict[str, str]: Dictionary where keys are headers and values are textbox contents.
        """
        pass

    @abstractmethod
    def display(self):
        """
        Displays the UI components for the layer.
        """
        pass

    @abstractmethod
    def process(self, edited_texts: dict):
        """
        Processes the edited texts from the layer.

        Args:
            edited_texts (dict): Edited texts from the textboxes.
        """
        pass


@with_logging_context(layer=LayerName.INPUTS)
class InputValidationLayer(BaseLayer):
    def get_inputs(self) -> Dict[str, Dict[str, Union[str, List[str]]]]:
        content_plan = self.context.content_plan
        lesson_context_pack = LessonContextPack.from_context(self.context)
        return {
            'content_plan': content_plan,
            'transcript_pack': lesson_context_pack.transcript_pack
        }

    def display(self):
        st.header('Validate Concept Definition')

        inputs = self.get_inputs()
        if st.session_state.get('auto_next'):
            time.sleep(5)
            st.session_state.current_layer += 1
            st.rerun()


        self.edited_texts = {}

        # Display transcript_pack text box
        st.subheader("Transcript Pack")
        transcript_pack = st.text_area(
            label="Special notes for transcript generation:",
            value=inputs['transcript_pack'],
            height=150,
            key="transcript_pack"
        )

        for l3_header, l4_dict in inputs['content_plan'].items():
            st.write(f'<p style="font-weight:bold;margin-bottom:1em;font-size: 1.2em;">L3: {l3_header}</p>', unsafe_allow_html=True)
            self.edited_texts[l3_header] = {}

            for l4_idx, (l4_header, learning_objectives) in enumerate(l4_dict.items()):
                l4_key = f"l4_{l3_header}_{l4_idx}"

                st.write('<p style="margin-bottom:0rem;font-size: 1.2em;">L4 Objective</p>', unsafe_allow_html=True)

                edited_l4_header = st.text_input(
                    label="L4 Objective",
                    value=l4_header,
                    key=l4_key,
                    label_visibility="collapsed"
                )

                indent_col, content_col = st.columns([0.01, 0.99])
                with content_col:
                    st.write('<p style="font-size:1.1em;margin-bottom:0rem;">Learning Objectives</p>', unsafe_allow_html=True)

                    learning_objectives_text = "\n".join(learning_objectives)
                    lo_key = f"lo_{l3_header}_{l4_idx}"
                    edited_lo_text = st.text_area(
                        label="Learning Objectives",
                        value=learning_objectives_text,
                        key=lo_key,
                        label_visibility="collapsed"
                    )
                self.edited_texts[l3_header][edited_l4_header] = edited_lo_text

        if st.button('Next'):
            self.process(self.edited_texts, transcript_pack)
            st.session_state.current_layer += 1
            st.rerun()

    def process(self, edited_texts: Dict[str, Dict[str, str]], transcript_pack: str):
        new_concepts = {}

        for l3_header, l4_dict in edited_texts.items():
            new_l4_dict = {}
            for l4_header, edited_lo_text in l4_dict.items():
                learning_objectives = [
                    lo.strip() for lo in edited_lo_text.strip().split('\n') if lo.strip()
                ]
                if l4_header and learning_objectives:
                    new_l4_dict[l4_header] = learning_objectives
            new_concepts[l3_header] = new_l4_dict
        
        save_json_to_s3(new_concepts, self.context.base_path + f"contents/subsection/content_plan/{self.context.key}-edited.json")

        # Update transcript_pack
        if not does_file_exist(self.context.context_pack_path):
            context_pack = {
                'transcript_pack': transcript_pack
            }
            save_json_to_s3(context_pack, self.context.context_pack_path)
        else:
            # Load existing context pack
            existing_context_pack = load_json_from_s3(self.context.context_pack_path)
            
            # Update only the transcript_pack field
            existing_context_pack['transcript_pack'] = transcript_pack
            # Save the updated context pack back to S3
            save_json_to_s3(existing_context_pack, self.context.context_pack_path)


@with_logging_context(layer=LayerName.TRANSCRIPT)
class TranscriptValidationLayer(BaseLayer):
    @st.cache_data
    def get_inputs(_self) -> dict:
        # Load or generate transcript in the new schema: Dict[str, TranscriptObject]
        if does_file_exist(_self.context.transcripts_path):
            logger.info(f"TranscriptValidationLayer: Transcript found. LOADING: {_self.context.transcripts_path}")
            transcript = load_json_from_s3(_self.context.transcripts_path)
        else:
            logger.info(f"TranscriptValidationLayer: No transcript found. GENERATING: {_self.context.transcripts_path}")
            transcript = generate_lesson_transcript('', '', _self.context.dict())
            save_json_to_s3(transcript, _self.context.transcripts_path)
        return transcript  # Dict[str, TranscriptObject.dict()]

    def display(self):
        st.header('Validate Transcript')

        transcript = self.get_inputs()['lesson_transcript']
        # If auto_next is ON, skip after a short delay
        if st.session_state.get('auto_next'):
            time.sleep(5)
            st.session_state.current_layer += 1
            st.rerun()

        self.edited_transcript = {}
        # Display each concept set separately
        for key, obj in transcript.items():
            print(key)
            st.write(f"**Concept**: {obj.get('concept','')}")
            question = st.text_area("Question from Host", value=obj.get("question", ""), key=f"question_{key}")
            explanation = st.text_area("Explanation by Confucius", value=obj.get("explanation", ""), key=f"explanation_{key}")
            recap = st.text_area("Recap from Host", value=obj.get("recap", ""), key=f"recap_{key}")
            st.write("---")

            self.edited_transcript[key] = {
                "concept": obj.get("concept", ""),
                "question": question,
                "explanation": explanation,
                "recap": recap,
                # Preserve figure_name if present
                "figure_name": obj.get("figure_name", "")
            }

        if st.button('Next'):
            self.process(self.edited_transcript)
            st.session_state.current_layer += 1
            st.rerun()

    def process(self, edited_transcript: dict):
        # Save updated transcript in the same schema
        path = os.path.dirname(self.context.transcripts_path) + f"/{self.context.key}-edited.json"
        save_json_to_s3({"lesson_transcript": edited_transcript}, path)


@with_logging_context(layer=LayerName.CLIPS)
class ClipsValidationLayer(BaseLayer):
    @st.cache_data
    def get_inputs(_self) -> List[Clip]:

        if does_file_exist(_self.context.clips_path):
            logger.info("ClipsValidationLayer: Clips found. LOADING!")
            clips = load_json_from_s3(_self.context.clips_path)
        else:
            logger.info("ClipsValidationLayer: No clips found. GENERATING!")
            clips = generate_clips('', '', _self.context.dict())
            save_json_to_s3(clips, _self.context.clips_path)
        return clips['clips']

    def display(self):
        st.header('Validate Clip Definitions')

        clips = self.get_inputs()
        if st.session_state.get('auto_next'):
            time.sleep(5)
            st.session_state.current_layer += 1
            st.rerun()

        edited_clips = []

        for idx, clip in enumerate(clips):
            clip = Clip(**clip)
            st.subheader(f"Clip {idx + 1}")
            cols = st.columns([1, 1, 1])

            with cols[0]:
                clip_text = st.text_area(
                    label='Transcript Snippet',
                    value=clip.text,
                    key=f'snippet_{idx}',
                    height=150
                )

            with cols[1]:
                img_prompt = st.text_area(
                    label='Image Prompt',
                    value=clip.media.img_prompt,
                    key=f'img_prompt_{idx}',
                    height=150
                )

            with cols[2]:
                video_prompt = st.text_area(
                    label='Video Prompt',
                    value=clip.media.video_prompt or '',
                    key=f'video_prompt_{idx}',
                    height=150
                )

            if st.button('✓', key=f'process_button_{idx}'):
                self.approve_clip(clip, idx)

            edited_clip = Clip(
                text=clip_text,
                media=Media(
                    type='VIDEO' if video_prompt else clip.media.type,
                    description=clip.media.description,
                    img_prompt=img_prompt,
                    video_prompt=video_prompt if video_prompt else None
                ),
                start_time=clip.start_time,
                end_time=clip.end_time,
                range=clip.range
            )
            edited_clips.append(edited_clip)

            st.markdown("---")

        if st.button('Next'):
            self.process(edited_clips)
            st.session_state.current_layer += 1
            st.rerun()

    def process(self, edited_clips: List[Clip]) -> None:
        timings = TranscriptTiming(timings=load_json_from_s3(self.context.avatar_assets_path)['lesson_timings'])
        original_clips = [Clip(**clip) for clip in load_json_from_s3(self.context.clips_path)['clips']]

        for ii, (edited_clip, original_clip) in enumerate(zip(edited_clips, original_clips)):
            if edited_clip.text != original_clip.text and edited_clip.text.strip():
                edited_clips[ii] = match_snippet_timings(timings, edited_clip)
                logger.info(f"Found clip text mismatch.\nOld: '{original_clip.text}' - Time = {original_clip.duration}s.\nNew: '{edited_clips[ii].text}' - Time = {edited_clips[ii].duration}s")
                if ii == len(edited_clips) - 1: # Add extra 2 seconds to last clip if it was edited
                    edited_clips[ii].duration += 2 
                    edited_clips[ii].end_time += 2

        edited_clips = {"clips": [clip.dict() for clip in edited_clips if clip.text.strip()]}
        save_json_to_s3(edited_clips,
                        os.path.dirname(self.context.clips_path) + f"/{self.context.key}-edited.json")
        time.sleep(2)

    def approve_clip(self, clip: Clip, idx: int):
        clip_text = st.session_state.get(f'snippet_{idx}')
        img_prompt = st.session_state.get(f'img_prompt_{idx}')
        video_prompt = st.session_state.get(f'video_prompt_{idx}')

        clip.media.img_prompt = img_prompt
        clip.media.video_prompt = video_prompt if video_prompt else None

        # threading.Thread(target=, args=(self.context, clip.media)).start()

@with_logging_context(layer=LayerName.OVERLAYS)
class OverlayValidationLayer(BaseLayer):
    def __init__(self, context: Context):
        super().__init__(context)
        self.emoji_dict = {1: '1️⃣', 2: '2️⃣', 3: '3️⃣', 4: '4️⃣', 5: '5️⃣', 6: '6️⃣', 7: '7️⃣', 8: '8️⃣', 9: '9️⃣', 10: '🔟'}

    @st.cache_data
    def get_inputs(_self) -> OverlaysData:

        # Generate avatar assets if not found
        if does_file_exist(_self.context.avatar_assets_path):
            logger.info("OverlayValidationLayer: Avatar Assets file found. LOADING!")
            avatar_assets_json = load_json_from_s3(_self.context.avatar_assets_path)
        else:
            logger.info("OverlayValidationLayer: Generating Avatar Assets")
            avatar_assets_json = generate_avatar_assets('', '', _self.context.dict())
            save_json_to_s3(avatar_assets_json, _self.context.avatar_assets_path)

        # Generate overlays if not found
        if does_file_exist(_self.context.text_overlays_path):
            logger.info("OverlayValidationLayer: Overlays found. LOADING!")
            overlays = load_json_from_s3(_self.context.text_overlays_path)
        else:
            logger.info("OverlayValidationLayer: No overlays found. GENERATING!")
            overlays = generate_text_overlays('', '', _self.context.dict())
            save_json_to_s3(overlays, _self.context.text_overlays_path)
        return overlays

    def display(self):
        st.header('Validate Text Overlays')

        overlays = OverlaysData(**self.get_inputs())
        if st.session_state.get('auto_next'):
            time.sleep(5)
            st.session_state.current_layer += 1
            st.rerun()
        transcript_timings = TranscriptTiming(timings=load_json_from_s3(self.context.avatar_assets_path)['lesson_timings'])
        transcript_words = [item.text for item in transcript_timings.timings]
        transcript = ' '.join(transcript_words)

        tagged_transcript = self.tag_transcript_with_overlays(transcript, transcript_words, overlays)

        st.subheader("Overlay Positions")
        st.text_area(label="Voiceover transcript", value=tagged_transcript, height=400)

        st.subheader("Overlay Content")

         # Add custom CSS to increase tab label size
        st.markdown("""
        <style>
        .stTabs [data-baseweb="tab-list"] button p {
            font-size: 24px;
            padding: 0 5px;
        }
        </style>
        """, unsafe_allow_html=True)

        # Create tabs for overlays
        overlay_tabs = st.tabs(['Title 📘', 'Topics 🚩', 'Key Phrases ⭐️', 'Conclusion 📜'])

        with overlay_tabs[0]:
            title = [i for i in overlays.titleOverlays if i.canvas_type == CanvasType.TITLE][0]
            st.text_input(
                label="Title",
                value=title.text_overlays[0].text,
                key='title',
                label_visibility="collapsed"
            )

        with overlay_tabs[1]:
            for (i, overlay) in enumerate([i for i in overlays.titleOverlays if i.canvas_type == CanvasType.TOPIC_INTRO]):
                col1, col2 = st.columns([1, 20])
                with col1:
                    st.write(f"<p style='font-size: 24px; margin: 0; text-align: right;'>{i+1}</p>", unsafe_allow_html=True)
                with col2:
                    st.text_input(
                        label=f"Topic Intro {i+1}",
                        value=overlay.text_overlays[0].text,
                        key=f'topic_intro_{i}',
                        label_visibility="collapsed"
                    )
        with overlay_tabs[2]:
            for (i, key_phrase) in enumerate(overlays.key_phrases):
                col1, col2 = st.columns([1, 20])
                with col1:
                    st.write(f"<p style='font-size: 24px; margin: 0; text-align: right;'>{i+1}</p>", unsafe_allow_html=True)
                with col2:
                    st.text_input(
                        label=f"Key Phrase {i+1}",
                        value=key_phrase.phrase,
                        key=f'key_phrase_{i}',
                        label_visibility="collapsed"
                    )
        with overlay_tabs[3]:
            for (i, bullet_point) in enumerate(overlays.bullet_slide[0].bullet_points):
                col1, col2 = st.columns([1, 20])
                with col1:
                    st.write(f"<p style='font-size: 24px; margin: 0;'>{self.emoji_dict[i+1]}</p>", unsafe_allow_html=True)
                with col2:
                    st.text_input(
                        label=f"Bullet Point {i+1}",
                        value=bullet_point.text,
                        key=f'bullet_point_{i}',
                        label_visibility="collapsed"
                    )
        st.markdown("---")
        if st.button('Next'):
            self.process({})
            st.session_state.current_layer += 1
            st.rerun()

    def tag_transcript_with_overlays(self, transcript, transcript_words, overlays: OverlaysData):
        tagged_transcript = transcript

        # tagging topic intro overlays
        for (i, overlay) in enumerate(overlays.title_overlays):
            tagged_transcript = self.insert_tags(
                tagged_transcript,
                transcript_words,
                start_index=overlay.start_index,
                end_index=overlay.end_index,
                start_tag=f'<🚩{i}>' if overlay.type == TitleOverlayType.SECTION_TITLE else '<📘>',
                end_tag=f'</🚩{i}>' if overlay.type == TitleOverlayType.SECTION_TITLE else '</📘>'
            )
        
        # tagging key phrases overlays
        for (i, key_phrase) in enumerate(overlays.key_phrases):
            tagged_transcript = self.insert_tags(
                tagged_transcript,
                transcript_words,
                start_index=key_phrase.start_index,
                end_index=key_phrase.end_index,
                start_tag=f'<⭐️{i+1}>',
                end_tag=f'</⭐️{i+1}>'
            )

        # tagging conclusion overlays
        for (i, conclusion) in enumerate(overlays.bullet_slide):
            tagged_transcript = self.insert_tags(
                tagged_transcript,
                transcript_words,
                start_index=conclusion.start_index,
                end_index=conclusion.end_index-1,
                start_tag='<📜>',
                end_tag='</📜>'
            )
            for (j, bullet_point) in enumerate(conclusion.bullet_points):
                start_ind = bullet_point.start_index
                end_ind = min(start_ind + 10, len(transcript_words))
                tagged_transcript = self.insert_tags(
                    tagged_transcript,
                    transcript_words,
                    start_index=start_ind,
                    end_index=end_ind,
                    start_tag=self.emoji_dict[j+1],
                    end_tag=''
                )

        return tagged_transcript
    
    def insert_tags(self, transcript, transcript_words, start_index, end_index, start_tag, end_tag):
        text_to_tag = ' '.join(transcript_words[start_index:end_index+1])        
        escaped_text = re.escape(text_to_tag) # Escape special characters in text_to_tag to avoid regex issues
        tagged_text = f"{start_tag}{text_to_tag}{end_tag}"
        return re.sub(escaped_text, tagged_text, transcript, count=1)

    def process(self, _):
        # TODO: Any edits made in the ui to be processed and json to be updated in s3
        pass

@with_logging_context(layer=LayerName.IMAGES)
class ImagesValidationLayer(BaseLayer):
    def __init__(self, context: Context):
        super().__init__(context)
        self.images_metadata_dict = {}
        self.clip_placeholders = {}
        self.clips = []
        self.regeneration_status = {}

        # Initialize variables for the Streamlit session and loop
        self.session_id = None
        self.streamlit_session = None
        self.streamlit_loop = None

    def setup_streamlit_session(self):
        # Get the session_id for the current running script 
        try:
            ctx = get_script_run_ctx()
            self.session_id = ctx.session_id
            logger.info(f"Session ID: {self.session_id}")
        except Exception as e:
            logger.error("Could not get browser session id")
            raise e

        file_path = './.streamlit/secrets.toml'
        if not os.path.exists(file_path):
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w') as file:
                pass

        # Get the main event loop
        loops = []
        for obj in gc.get_objects():
            loops.append(obj)
        main_thread = next((t for t in threading.enumerate() if t.name == 'MainThread'), None)
        if main_thread is None:
            raise Exception("No main thread")
        main_loop = next((lp for lp in loops if getattr(lp, '_thread_id', None) == main_thread.ident), None)

        if main_loop is None:
            raise Exception("No event loop on 'MainThread'")
        self.streamlit_loop = main_loop


        # Get the Streamlit session
        runtime: Runtime = Runtime.instance()
        self.streamlit_session = next((
            s.session
            for s in runtime._session_mgr.list_sessions()
            if s.session.id == self.session_id
        ), None)
        if self.streamlit_session is None:
            raise Exception(f"Streamlit session not found for {self.session_id}")

    def notify_rerun(self):
        if self.streamlit_loop and self.streamlit_session:
            def notify():
                self.streamlit_session._handle_rerun_script_request()
            self.streamlit_loop.call_soon_threadsafe(notify)
        else:
            logger.error("Streamlit session or loop not found, cannot trigger rerun")

    @st.cache_data       
    def get_inputs(_self) -> List[Tuple[int, Clip, ImagesMetadata]]:
        logger.info(f"ImageValidation Layer: FETCHING IMAGE INPUTS")
        if does_file_exist(_self.context.image_json_path):
            logger.info("ImageValidation Layer: Images found. LOADING!")
            generated_images = load_json_from_s3(_self.context.image_json_path)
        else:
            logger.info("ImageValidation Layer: No images found. GENERATING!")
            generated_images = generate_all_images('', '', _self.context.dict())
            save_json_to_s3(generated_images, _self.context.image_json_path)

        _self.clips = [Clip(**clip) for clip in load_json_from_s3(_self.context.clips_path)['clips']]
        inputs = []
        for idx, clip in enumerate(_self.clips):
            image_hash = clip.media.id
            s3_images_folder = _self.context.media_path + f"images/{image_hash}/"
            images_metadata_json = load_json_from_s3(s3_images_folder + f"{image_hash}.json")
            inputs.append((idx, clip.dict(), images_metadata_json))
        logger.info("ImageValidation Layer: ALL IMAGES FETCHED")
        return inputs

    def display(self):
        # Set up the Streamlit session and loop
        self.setup_streamlit_session()
        logger.info("Running ImagesValidationLayer Display")
        st.header('Validate Images')

        inputs = self.get_inputs()
        if st.session_state.get('auto_next'):
            time.sleep(5)
            st.session_state.current_layer += 1
            st.rerun()

        self.images_metadata_dict = {}
        self.clip_placeholders = {}
        self.clips = []

        for idx, (clip_idx, clip, images_metadata) in enumerate(inputs):
            images_metadata = ImagesMetadata(**images_metadata)
            clip = Clip(**clip)
            self.clips.append(clip)

            self.images_metadata_dict[clip_idx] = images_metadata

            placeholder = st.empty()
            self.clip_placeholders[clip_idx] = placeholder

            self.render_clip(clip_idx, clip, images_metadata, placeholder)

        if st.button('Next'):
            self.process(inputs)
            st.session_state.current_layer += 1
            st.rerun()

    def render_clip(self, clip_idx: int, clip: Clip, images_metadata: ImagesMetadata, placeholder):
        with placeholder.container():
            st.subheader(f"Clip {clip_idx + 1}")

            cols = st.columns([1, 4])
            with cols[0]:
                # Image Type selection
                image_type_options = [e.value for e in GeneratedImageTypes]
                selected_image_type_value = images_metadata.type.value if isinstance(
                        images_metadata.type, GeneratedImageTypes) else images_metadata.type
                image_type = st.selectbox(label='Image Type', options=image_type_options, index=image_type_options.index(
                        selected_image_type_value) if selected_image_type_value in image_type_options else 0, key=f'image_type_{clip_idx}')

            with cols[1]:
                # Image Prompt
                if image_type not in [GeneratedImageTypes.UPLOAD.value, GeneratedImageTypes.URL.value]:
                    prompt_text = st.text_area(
                        label='Image Prompt',
                        value=images_metadata.prompt,
                        key=f'prompt_{clip_idx}'
                    )
                
                # File Upload
                if image_type == GeneratedImageTypes.UPLOAD.value:
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        uploaded_file = st.file_uploader("Upload an image", type=["png", "jpg", "jpeg"], key=f"file_uploader_{clip_idx}")
                    with col2:
                        if uploaded_file is not None:
                            if st.button("Add this image", key=f"process_file_{clip_idx}"):
                                self.handle_image_upload(clip_idx, uploaded_file, None)

                # URL Input
                elif image_type == GeneratedImageTypes.URL.value:
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        image_url = st.text_input(label="Enter image URL", key=f"url_input_{clip_idx}")
                    with col2:
                        if image_url:
                            if st.button("Add this image", key=f"process_url_{clip_idx}"):
                                self.handle_image_upload(clip_idx, None, image_url)

            # Display current image(s)
            images = images_metadata.image
            num_images = len(images)
            cols_per_row = 4
            num_rows = -(-num_images // cols_per_row)  # Ceiling division

            for row_idx in range(num_rows):
                cols = st.columns(cols_per_row)
                for col_idx in range(cols_per_row):
                    img_idx = row_idx * cols_per_row + col_idx
                    if img_idx < num_images:
                        image_details = images[img_idx]
                        try:
                            with cols[col_idx]:
                                local_path = f'/tmp/{os.path.basename(image_details.src)}'
                                if not os.path.exists(local_path):
                                    download(image_details.src, local_path)
                                st.image(local_path, use_column_width=True, caption=f"Image {img_idx + 1}")
                        except:
                            continue
                    else:
                        cols[col_idx].empty()

            if images_metadata.human_choice is not None:
                default_index = images_metadata.human_choice + 1  # +1 because of the 'None' option at index 0
            elif images_metadata.qc_choice is not None:
                default_index = images_metadata.qc_choice + 1
            else:
                default_index = 0

            st.selectbox(
                label='Select preferred image:',
                options=[None] + list(range(num_images)),
                index=default_index,
                format_func=lambda x: f"Image {x + 1}" if x is not None else "None",
                key=f'select_{clip_idx}',
                on_change=self.make_update_human_image_choice(clip_idx)
            )

            button_cols = st.columns([5, 1, 1])
            with button_cols[1]:
                if st.button('🔄', key=f'regenerate_{clip_idx}'):
                    current_prompt = st.session_state.get(f'prompt_{clip_idx}', images_metadata.prompt)
                    current_image_type = st.session_state.get(f'image_type_{clip_idx}', images_metadata.type.value)
                    self.regenerate_image(clip_idx, clip, images_metadata, current_prompt, current_image_type)
            with button_cols[2]:
                if st.button('✅', key=f'approve_{clip_idx}'):
                    self.approve_image(clip_idx)

            st.markdown("---")

    def update_clip(self, clip_idx: int, images_metadata: ImagesMetadata) -> None:
        logger.info(f"Updating image metadata for clip {clip_idx}")
        self.images_metadata_dict[clip_idx] = images_metadata
        self.notify_rerun()

    def make_update_human_image_choice(self, clip_idx):
        def update_human_image_choice():
            selected_image_idx = st.session_state[f'select_{clip_idx}']
            images_metadata = self.images_metadata_dict[clip_idx]
            # Only update if the choice has changed
            if images_metadata.human_choice == selected_image_idx:
                return
            images_metadata.human_choice = selected_image_idx
            logger.info(f"Updating {images_metadata.id} image's choice. New choice Image: {selected_image_idx}")

            image_hash = images_metadata.id
            s3_images_folder = self.context.media_path + f"images/{image_hash}/"
            save_json_to_s3(images_metadata.dict(), s3_images_folder + f"{image_hash}.json")
            st.success(f"Updated human image choice for Clip {clip_idx + 1}")
        return update_human_image_choice

    def regenerate_image(self, clip_idx: int, clip: Clip, images_metadata: ImagesMetadata, prompt_text: str, image_type: str):
        logger.info(f"Regenerating Image {images_metadata.id}")

        images_metadata.prompt = prompt_text
        images_metadata.type = GeneratedImageTypes(image_type)

        def thread_function():
            new_images_metadata = regenerate_image(
                self.context, clip_idx, images_metadata)
            self.update_clip(clip_idx, new_images_metadata)

        thread = threading.Thread(target=thread_function)
        add_script_run_ctx(thread)
        thread.start()

    def approve_image(self, clip_idx: int):
        return
        selected_image_idx = st.session_state.selected_images.get(clip_idx)
        if selected_image_idx is not None:
            st.write(f"Approving Clip {clip_idx + 1} with selected image {selected_image_idx + 1}")
            images_metadata = self.images_metadata_dict[clip_idx]
            images_metadata.qc_choice = selected_image_idx

            image_hash = images_metadata.id
            s3_images_folder = self.context.media_path + f"images/{self.context.key}/{image_hash}/"
            save_json_to_s3(images_metadata.dict(), s3_images_folder + f"{image_hash}.json")

            st.success(f"Clip {clip_idx + 1} approved")
        else:
            st.error(f"No image selected for Clip {clip_idx + 1}")

    def process(self, inputs: List[Tuple[int, Clip, ImagesMetadata]]):
        def worker(item):
            idx, (clip_idx, clip, images_metadata) = item
            images_metadata = ImagesMetadata(**images_metadata)
            clip = Clip(**clip)
            if images_metadata.human_choice is None and images_metadata.qc_choice is None:
                logger.info(f"Running QC for clip {clip_idx+1}")
                images_metadata = set_best_image_qc_choice(images_metadata)
                image_hash = images_metadata.id
                s3_images_folder = self.context.media_path + f"images/{self.context.key}/{image_hash}/"
                save_json_to_s3(images_metadata.dict(), s3_images_folder + f"{image_hash}.json")

        with ContextAwareThreadPoolExecutor(max_workers=6) as executor:
            executor.map(worker, enumerate(inputs))

    def handle_image_upload(self, clip_idx: int, uploaded_file, image_url: str):
        logger.info(f"Handling image upload for Clip {clip_idx + 1}...")
        images_metadata = self.images_metadata_dict[clip_idx]
        image_hash = images_metadata.id
        s3_images_folder = self.context.media_path + f"images/{image_hash}/"
        local_path = f'/tmp/{image_hash}.png'
        
        if uploaded_file is not None:
            with open(local_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
        elif image_url:
            response = requests.get(image_url)
            with open(local_path, "wb") as f:
                f.write(response.content)
        else:
            return

        s3_file_path = s3_images_folder + os.path.basename(local_path)
        upload_file_to_s3(local_path, s3_file_path)

        # Update images_metadata
        new_image_details = ImageDetails(src=s3_file_path)
        images_metadata.type = GeneratedImageTypes.UPLOAD if uploaded_file is not None else GeneratedImageTypes.URL
        images_metadata.image = [new_image_details]
        images_metadata.human_choice = 0
        images_metadata.qc_choice = None

        # Save updated metadata
        save_json_to_s3(images_metadata.dict(), s3_images_folder + f"{image_hash}.json")
        logger.info(f"Image uploaded successfully for Clip {clip_idx + 1}")

        st.success(f"Image uploaded successfully for Clip {clip_idx + 1}")
        st.rerun()
 

@with_logging_context(layer=LayerName.VIDEOS)
class VideoValidationLayer(BaseLayer):
    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self.session_id = None
        self.streamlit_session = None
        self.streamlit_loop = None
        self.video_metadata_dict = {}
        self.clip_placeholders = {}
        self.clips = []
        self.regeneration_status = {}
        self.inputs = self.get_inputs()

    def setup_streamlit_session(self):
        # Get the session_id for the current running script 
        try:
            ctx = get_script_run_ctx()
            self.session_id = ctx.session_id
            logger.info(f"Session ID: {self.session_id}")
        except Exception as e:
            logger.error("Could not get browser session id")
            raise e

        file_path = './.streamlit/secrets.toml'
        if not os.path.exists(file_path):
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w') as file:
                pass

        # Get the main event loop
        loops = []
        for obj in gc.get_objects():
            loops.append(obj)
        main_thread = next((t for t in threading.enumerate() if t.name == 'MainThread'), None)
        if main_thread is None:
            raise Exception("No main thread")
        main_loop = next((lp for lp in loops if getattr(lp, '_thread_id', None) == main_thread.ident), None)

        if main_loop is None:
            raise Exception("No event loop on 'MainThread'")
        self.streamlit_loop = main_loop

        # Get the Streamlit session
        runtime: Runtime = Runtime.instance()
        self.streamlit_session = next((
            s.session
            for s in runtime._session_mgr.list_sessions()
            if s.session.id == self.session_id
        ), None)
        if self.streamlit_session is None:
            raise Exception(f"Streamlit session not found for {self.session_id}")

    def notify_rerun(self, clip_idx: int, video_metadata: VideoMetadata):
        if self.streamlit_loop and self.streamlit_session:
            def notify():
                self.streamlit_session._handle_rerun_script_request()
            self.streamlit_loop.call_soon_threadsafe(notify)
        else:
            logger.error("Streamlit session or loop not found, cannot trigger rerun")

    @st.cache_data       
    def get_inputs(_self) -> List[Tuple[int, Clip, VideoMetadata]]:
        logger.info("GETTING VIDEO GENERATION INPUTS")
        if does_file_exist(_self.context.video_json_path):
            logger.info("Videos ValidationLayer: Clips found. LOADING!")
            generated_videos = load_json_from_s3(_self.context.video_json_path)
        else:
            logger.info("Videos ValidationLayer: No clips found. GENERATING!")
            generated_videos = generate_all_videos('', '', _self.context.dict())
            save_json_to_s3(generated_videos, _self.context.video_json_path)

        clips = [Clip(**clip) for clip in load_json_from_s3(_self.context.clips_path)['clips']]
        inputs = []
        for idx, clip in enumerate(clips):
            if clip.media.type == 'VIDEO':
                s3_videos_folder = _self.context.media_path + f"videos/{clip.media.id}/"
                video_metadata_json = load_json_from_s3(s3_videos_folder + f"{clip.media.id}.json")
                inputs.append((idx, clip.dict(), video_metadata_json))
        logger.info("VIDEO GENERATION INPUTS FETCHED")
        return inputs

    def display(self):
        logger.info("DISPLAYING VIDEO GENERATION INPUTS")
        # Set up the Streamlit session and loop
        self.setup_streamlit_session()
        st.header('Validate Videos')

        inputs = self.get_inputs()
        if st.session_state.get('auto_next'):
            time.sleep(5)
            st.session_state.current_layer += 1
            st.rerun()

        if not inputs:
            st.write("No video clips to validate.")
            if st.button('Next'):
                st.session_state.current_layer += 1
                st.rerun()
            return

        # Initialize data structures
        self.video_metadata_dict = {}
        self.clip_placeholders = {}
        self.clips = []
        self.regeneration_status = {}

        for idx, (clip_idx, clip, video_metadata) in enumerate(inputs):
            video_metadata = VideoMetadata(**video_metadata)
            clip = Clip(**clip)
            self.clips.append(clip)

            self.video_metadata_dict[clip_idx] = video_metadata

            placeholder = st.empty()
            self.clip_placeholders[clip_idx] = placeholder

            self.render_clip(clip_idx, clip, video_metadata, placeholder)

        if st.button('Next'):
            self.process(inputs)
            st.session_state.current_layer += 1
            st.rerun()

    def render_clip(self, clip_idx: int, clip: Clip, video_metadata: VideoMetadata, placeholder):
        with placeholder.container():
            st.subheader(f"Clip {clip_idx + 1}")

            prompt = video_metadata.videos[-1].prompt or ''
            prompt_text = st.text_area(
                label='Video Prompt',
                value=prompt,
                key=f'prompt_{clip_idx}'
            )

            base_image_metadata = ImagesMetadata(**load_json_from_s3(self.context.media_path+ f"images/{clip.media.id}/{clip.media.id}.json"))
            base_image_s3_path = base_image_metadata.get_best_image().src
            local_image_path = f"/tmp/{os.path.basename(base_image_s3_path)}"
            if not os.path.exists(local_image_path):
                download(base_image_s3_path, local_image_path)

            if video_metadata.videos:
                latest_video = video_metadata.videos[-1]
                local_video_path = f"/tmp/{os.path.basename(latest_video.src)}"
                if not os.path.exists(local_video_path):
                    download(latest_video.src, local_video_path)
            else:
                st.error(f"No videos found for Clip {clip_idx + 1}")
                return

            cols = st.columns(2)
            with cols[0]:
                st.image(local_image_path, use_column_width=True)
            with cols[1]:
                st.video(local_video_path)

            button_cols = st.columns([9, 1])  # Adjust the widths as needed
            with button_cols[1]:
                if st.button('🔄', key=f'regenerate_{clip_idx}'):
                    current_prompt_text = st.session_state.get(f'prompt_{clip_idx}', prompt)
                    self.regenerate_video(clip_idx, clip, current_prompt_text)

            st.markdown("---")

    def regenerate_video(self, clip_idx: int, clip: Clip, prompt_text: str):
        logger.info(f"Regenerating Video for Clip {clip_idx + 1}")
        clip.media.video_prompt = prompt_text
        clips_data = load_json_from_s3(self.context.clips_path)
        clips_list = clips_data['clips']

        for idx, c in enumerate(clips_list):
            if c['media']['id'] == clip.media.id:
                clips_list[idx]['media']['video_prompt'] = prompt_text
                break
        
        save_json_to_s3(clips_data, self.context.clips_path)

        def thread_function():
            # Regenerate the video
            video_metadata = process_generate_ai_video(self.context, clip.media, prompt_text)

            logger.info(self.inputs[clip_idx][2]['videos'][-1]['src'])
            self.update_clip(clip_idx, video_metadata)

        thread = threading.Thread(target=thread_function)
        add_script_run_ctx(thread)
        thread.start()

    def update_clip(self, clip_idx: int, video_metadata: VideoMetadata) -> None:
        logger.info(f"Updating video metadata for clip {clip_idx}")
        self.video_metadata_dict[clip_idx] = video_metadata
        self.regeneration_status[clip_idx] = False
        self.get_inputs.clear()
        self.notify_rerun(clip_idx, video_metadata)

    def process(self, inputs: List[Tuple[int, Clip, VideoMetadata]]):
        return

@with_logging_context(layer=LayerName.RENDER)
class LocalRenderLayer(BaseLayer):
    @st.cache_data
    def get_inputs(_self):
        if does_file_exist(_self.context.lesson_video_path):
            logger.info(f"LocalRenderLayer: render found. LOADING: {_self.context.lesson_video_path}")
            render_json = load_json_from_s3(_self.context.lesson_video_path)
        else:
            logger.info("LocalRenderLayer: rendering the lesson video")
            render_json = generate_lesson_video('', '', _self.context.dict())
            save_json_to_s3(render_json, _self.context.lesson_video_path)

        s3_path = render_json['lesson_video']['src']
        public_url = render_json['lesson_video']['output_data']['url']
        local_path = f'/tmp/{os.path.basename(s3_path)}'
        download(s3_path, local_path)
        return local_path, public_url

    def display(self):
        st.header('Local Render')

        video_url, public_url = self.get_inputs()
        
        if video_url:
            st.video(video_url)
        else:
            st.error("Failed to retrieve the rendered video.")
        
        st.markdown(f"**Video URL:** [{public_url}]({public_url.replace(' ', '%20')})")

        if st.button('Finish'):
            self.process(video_url)
            st.session_state.current_layer = 1
            st.success("Pipeline completed!")
            st.rerun()

    def process(self, video_url: str):
        # Reset pipeline
        st.session_state['start_pipeline'] = False
        st.success("Pipeline completed!")
        st.experimental_rerun()


if 'current_layer' not in st.session_state:
    st.session_state.current_layer = 1


pipeline_layers = [
    'Validate Concept Definition',
    'Validate Transcript',
    'Validate Text Overlays',
    'Validate Clip Definitions',
    'Validate Images',
    'Validate Videos',
    'Local Render'
]

def get_clickable_layers(context: Context):
    return {
        'Validate Concept Definition': True,
        'Validate Transcript': does_file_exist(context.transcripts_path),
        'Validate Text Overlays': does_file_exist(context.text_overlays_path),
        'Validate Clip Definitions': does_file_exist(context.clips_path),
        'Validate Images': does_file_exist(context.image_json_path),
        'Validate Videos': does_file_exist(context.video_json_path),
        'Local Render': does_file_exist(context.lesson_video_path)
    }

def main(context: Context):
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title('Pipeline UI')
    with col2:
        st.toggle("Auto-next", value=False, key="auto_next")

    render_navigation_bar(context)  # pass context here

    layer_classes = {
        1: InputValidationLayer,
        2: TranscriptValidationLayer,
        3: OverlayValidationLayer,
        4: ClipsValidationLayer,
        5: ImagesValidationLayer,
        6: VideoValidationLayer,
        7: LocalRenderLayer
    }

    current_layer_class = layer_classes.get(st.session_state.current_layer)
    if current_layer_class:
        layer_instance = current_layer_class(context)
        layer_instance.display()
    else:
        st.error("Invalid layer.")

def render_navigation_bar(context):
    """
    Renders the navigation bar with pipeline layers, highlighting the current layer.
    """
    clickable_layers = get_clickable_layers(context)
    cols = st.columns(len(pipeline_layers))
    for idx, (col, layer) in enumerate(zip(cols, pipeline_layers)):
        layer_number = idx + 1
        is_current_layer = (layer_number == st.session_state.current_layer)
        is_clickable = clickable_layers.get(layer, False)
        if is_current_layer:
            col.markdown(f"<div style='color: green; font-weight: bold;'>{layer}</div>", unsafe_allow_html=True)
        elif is_clickable:
            if col.button(layer, key=f'nav_button_{layer_number}'):
                st.session_state.current_layer = layer_number
                st.rerun()
        else:
            # Render non-clickable layer in dark gray
            col.markdown(f"<div style='color: darkgray;'>{layer}</div>", unsafe_allow_html=True)


def render_landing_page(execution_input):
    st.title("Select Topic")

    curriculum_data = get_topics_list(execution_input)

    units = list(curriculum_data["Units"].keys())
    st.subheader("Select Unit")
    selected_unit = st.selectbox(label="Select Unit", options=units, key='unit_select', label_visibility='collapsed')

    if selected_unit:
        chapters = list(curriculum_data["Units"][selected_unit]["Chapters"].keys())
        st.subheader("Select Chapter")
        selected_chapter = st.selectbox(label="Select Chapter", options=chapters, key='chapter_select', label_visibility='collapsed')

        if selected_chapter:
            sections = list(curriculum_data["Units"][selected_unit]["Chapters"][selected_chapter]["Sections"].keys())
            st.subheader("Select Section")
            selected_section = st.selectbox(label="Select Section", options=sections, key='section_select', label_visibility='collapsed')

            if selected_section:
                subsections = curriculum_data["Units"][selected_unit]["Chapters"][selected_chapter]["Sections"][selected_section]
                st.subheader("Select Subsection - L1")
                for idx, subsection in enumerate(subsections):
                    cols = st.columns([9,1])

                    with cols[0]:
                        st.write(subsection)

                    with cols[1]:
                        if st.button("✏️", key=f"generate_{idx}"):
                            selected_subsection = subsection
                            input_dict = {
                                "unit": selected_unit,
                                "chapter": selected_chapter,
                                "section": selected_section,
                                "subsection": selected_subsection
                            }

                            data = {
                                "ExecutionInput": execution_input,
                                "Input": input_dict
                            }
                            from core.context import \
                                prep_content_gen_input
                            context = prep_content_gen_input(data)

                            st.session_state['context'] = context
                            st.session_state['start_pipeline'] = True
                            st.session_state['current_layer'] = 1
                            st.rerun()

                    st.markdown('---')  


if __name__ == '__main__':
    from core.context import prep_content_gen_input
    execution_input = {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons 2",
            "grade": "Grade 11",
            "subject": "AP World History - v0",
            "category": "High School: AP World History: Modern"
        }
    if 'start_pipeline' in st.session_state and st.session_state['start_pipeline']:
        context = Context(**st.session_state['context'])
        with LoggingContext(lesson_id=context.key):
            main(context)
    else:
        render_landing_page(execution_input)
