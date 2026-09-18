import inspect
import json
import logging
import os
import re
import traceback
from concurrent.futures import (ProcessPoolExecutor, ThreadPoolExecutor,
                                as_completed)
from typing import Any, Dict, List, Optional, Tuple, Union

from core.types import (
    BaseDiagram, ConclusionBulletPoint, ConclusionSlideNew, Diagram,
    DiagramType, Feedback, KeyConcept, LayerName, LessonMetadata, MindMap,
    OverlaysData, QuestionOverlay, TextSlide, TextSlideElement,
    TextSlideElementType, TextSlidePhrase, TitleOverlay, TitleOverlayType,
    TranscriptConcept, TranscriptLesson, TranscriptOutput, TranscriptSection,
    TranscriptTiming, TreeDiagram, VennDiagram, VideoPlan, VisualType)
from core.media.clip_timings import (
    identify_word_index_in_transcript, match_segment_timings)
from core.log import (
    ContextAwareThreadPoolExecutor, setup_logging, with_logging_context)
from core.helpers import (
    concurrency_slots, exception_handler, extract_tag_content, llm_call,
    llm_call_with_qc, print_json, sanitize_path, split_speaker_dialogue,
    split_transcript)
from core.stage_constants import \
    VALID_FA_ICONS
from core.media.html_to_video import (
    generate_video_asset_from_html, render_conclusion_slides_template,
    render_diagram_template, render_text_slide_template)
from prompts.overlay_prompts import (
    DIAGRAM_CONFIGS, DIAGRAM_QC_REQUIREMENTS, DIAGRAM_TIMINGS_SYSTEM_PROMPT,
    DIAGRAM_TIMINGS_USER_PROMPT, LESSON_ORGANIZER_CONTENT_SYSTEM,
    LESSON_ORGANIZER_CONTENT_USER, LESSON_ORGANIZER_IDENTIFIER_SYSTEM,
    LESSON_ORGANIZER_IDENTIFIER_USER, SECTION_ORGANIZER_CONTENT_SYSTEM,
    SECTION_ORGANIZER_CONTENT_USER, SECTION_ORGANIZER_IDENTIFIER_SYSTEM,
    SECTION_ORGANIZER_IDENTIFIER_USER, TEXT_SLIDE_CONTENT_SYSTEM,
    TEXT_SLIDE_CONTENT_USER, TEXT_SLIDE_QC_REQUIREMENTS,
    TEXT_SLIDE_TIMINGS_SYSTEM_PROMPT, TEXT_SLIDE_TIMINGS_USER_PROMPT,
    TOPIC_TRANSITION_SYSTEM, TOPIC_TRANSITION_USER,
    get_diagram_content_system_prompt, get_diagram_content_user_prompt,
    text_slide_content_examples, text_slides_timings_examples)
from pydantic import BaseModel
from core.context import APVideoContext as Context
from core.context import get_lesson_context
from core.clients.openai import (LLM, assistant_message, ensure_json, llm_complete,
                          system_message, user_message)
from core.clients.s3 import load_json_from_s3, upload_file_to_s3

logger = logging.getLogger(__name__)


def review_timings(data: Any, label: str = "Check Timings") -> Any:
    """A human-review gate: dump the timings, wait for someone to edit the file, read it back.

    Off unless REVIEW_TIMINGS is set, and it has to be, because as written it cannot survive a
    real run. Both call sites execute inside ContextAwareThreadPoolExecutor(max_workers=4) and
    shared one fixed path, so four threads raced on ./point_timings.json and then all blocked
    on a single stdin. Any non-interactive run hung there forever.

    Skipping returns the data untouched instead of writing a file nobody will edit, so there
    is no path to race on. Callers re-parse the result exactly as before, which keeps the
    enabled and disabled paths identical apart from the pause. Only sane with max_workers=1.
    """
    if not os.getenv("REVIEW_TIMINGS"):
        return data

    path = './point_timings.json'
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=4, sort_keys=False)
    input(f"{label} in {path}, then press Enter")
    with open(path, encoding='utf-8') as handle:
        edited = json.load(handle)
    os.remove(path)
    return edited


models = {
    DiagramType.MIND_MAP.value: MindMap,
    DiagramType.TREE.value: TreeDiagram,
    DiagramType.VENN_DIAGRAM.value: VennDiagram
}

get_diagram_model = lambda model: inspect.getsource(BaseDiagram).split('def')[0] + '\n' + inspect.getsource(model).split('def')[0]


#=======================================GENERATE TEXT OVERLAYS==========================================

@with_logging_context(layer=LayerName.OVERLAYS)
@exception_handler
@concurrency_slots(slots=2, lock_name="OVERLAY_GEN_LOCK")
def generate_text_overlays(output_path: str, output_type: str, inputs: dict):
    logger.info("Generating Overlays")
    context = Context(**inputs)
    # get the transcript from s3
    transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path))
    video_plan = VideoPlan(**load_json_from_s3(context.video_plan_path)['video_plan'])
    # get the transcript timings from s3
    transcript_timings = TranscriptTiming(timings=load_json_from_s3(context.avatar_assets_path)['lesson_timings'])

    video_split_times  = identify_video_split_times(transcript, transcript_timings) 

    question_timings = identify_question_timings(transcript, transcript_timings)

    # create lesson title overlays
    lesson_title_overlay = create_lesson_title_overlay(video_plan.simple_title)
    
    # create section title overlays [Handling section titles in section overview diagram for now]
    # section_title_overlays = create_transition_canvases(transcript_timings, transcript, video_plan)

    # create text slides
    if inputs.get("LAYER_TEXT_SLIDES", True):
        text_slides = create_text_slides(context, video_plan, transcript, transcript_timings)
    else:
        logger.info("LAYER_TEXT_SLIDES off: no per-concept text slides")
        text_slides = []

    # create diagrams; each kind has its own flag, per-concept and overview being separate layers
    diagrams = create_diagrams(context, video_plan, transcript, transcript_timings, video_split_times,
                               include_concept_diagrams=inputs.get("LAYER_INFOGRAPHICS", True),
                               include_overviews=inputs.get("LAYER_OVERVIEW_DIAGRAMS", True))

    # create the conclusion slide
    if inputs.get("LAYER_CONCLUSION_SLIDE", True):
        conclusion_slide = create_conclusion_slide(context, transcript, transcript_timings)
    else:
        logger.info("LAYER_CONCLUSION_SLIDE off: no conclusion slide")
        conclusion_slide = None

    # Create OverlaysData object combining all overlays
    text_overlays_data = OverlaysData(
        title_overlays=[lesson_title_overlay],
        text_slides=text_slides,
        diagrams=diagrams,
        conclusion_slide=conclusion_slide,
        video_splits=video_split_times,
        questions=question_timings
    )

    return text_overlays_data.model_dump()


#=======================================VIDEO SPLIT TIMES and QUESTION TIMINGS==========================================

def identify_video_split_times(transcript: TranscriptOutput, transcript_timings: TranscriptTiming)->Dict[str, float]:
    
    _, intro_end = match_segment_timings(transcript_timings, " ".join(transcript.lesson_transcript_breakdown.introduction.split()[-10:]))
    split_times = {
        "Introduction": transcript_timings.timings[intro_end].end_time,
        "Conclusion": transcript_timings.timings[-1].end_time
    }

    for section_name, section in transcript.lesson_transcript_breakdown.sections.items():
        last_words_in_section = list(section.explanations.values())[-1].recap
        _, end_index = match_segment_timings(transcript_timings, last_words_in_section)
        split_times[f"Section: {section_name}"] = transcript_timings.timings[end_index].end_time

    return dict(sorted(split_times.items(), key=lambda x: x[1]))  

def identify_question_timings(transcript: TranscriptOutput, transcript_timings: TranscriptTiming)->Dict[str, Dict[str, QuestionOverlay]]:
    questions = {}
    for section_title, section_questions in transcript.supplementary_content.questions.items():
        questions[section_title] = {}
        for concept_name, concept_questions in section_questions.items():
            explanation = transcript.lesson_transcript_breakdown.sections[section_title].explanations[concept_name].explanation
            _, end_index = match_segment_timings(transcript_timings, " ".join(explanation.split()[-15:]))
            trigger_word = transcript_timings.timings[end_index]
            questions[section_title][concept_name] = QuestionOverlay(
                time=trigger_word.start_time + 1, # Assumes a 2 second pause is there
                questions= concept_questions
            )
    # print_json({s: {k: mcqs.model_dump() for k, mcqs in sc.items()} for s, sc in questions.items()})
    return questions

#=======================================LESSON TITLE OVERLAY==========================================

def create_lesson_title_overlay(title: str) -> TitleOverlay:
    logger.info("Creating Lessong Title Overlay")

    title_overlay = TitleOverlay(
        type=TitleOverlayType.LESSON_TITLE,
        text=title,
        start_index=0,
        end_index=len(title.split())-1,
        start_time=0,
        end_time=5
    )
    return title_overlay


#=======================================SECTION TITLE OVERLAYS==========================================

def create_transition_canvases(transcript_timings: TranscriptTiming, transcript: TranscriptOutput, plan: VideoPlan) -> List[TitleOverlay]:
    logger.info("Creating Topic Transition Canvases")

    section_overlays = []
    
    # Process each section from transcript directly
    for section_title, section_content in transcript.lesson_transcript_breakdown.sections.items():
        section_overview = section_content.overview
        if not section_overview:
            logger.warning(f"No overview found for section: {section_title}")
            continue

        # Get transition data for this section
        transition = determine_section_transition(section_title, section_overview)
        
        try:
            # Try to match the trigger phrase in transcript
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    sentence_start, sentence_end = match_segment_timings(transcript_timings, transition['trigger_sentence'])
                    sentence_timings = TranscriptTiming(timings=transcript_timings.timings[sentence_start:sentence_end+1])
                    phrase_start, phrase_end = match_segment_timings(sentence_timings, transition['trigger_phrase'])
                    start_index = sentence_start + phrase_start
                    end_index = sentence_start + phrase_end
                    break
                except ValueError as e:
                    if attempt < max_retries:
                        # Ask LLM to try again with a different phrase
                        logger.warning(f"Attempt {attempt + 1}: Failed to match phrase for section {section_title}. Retrying...")
                        transition = determine_section_transition(
                            section_title, 
                            section_overview,
                            error_message=f"The previously suggested phrase could not be exactly found in the transcript. Error: {str(e)}"
                        )
                    else:
                        # Fall back to using the start of the overview
                        logger.warning(f"All attempts failed for section {section_title}. Falling back to overview start...")
                        start_index = 0
                        end_index = start_index + 10  # Roughly 4 seconds of speech
            
            duration = max(min(len(section_title.split()), 8), 4)  # min 4 seconds, max 8 seconds
                       
            # Create Section Title overlay
            topic_overlay = TitleOverlay(
                type=TitleOverlayType.SECTION_TITLE,
                text=section_title,
                start_index=start_index,
                end_index=end_index,
                start_time=transcript_timings.timings[start_index].start_time,
                end_time=transcript_timings.timings[start_index].start_time + duration
            )
            section_overlays.append(topic_overlay)
            
        except Exception as e:
            logger.error(f"Error processing section {section_title}: {str(e)}")
            continue

    return section_overlays

def determine_section_transition(section_title: str, overview: str, error_message: str = "") -> dict:
    """Helper function to determine transition data for a single section"""
    retry_prompt = f"\n\nPrevious attempt failed: {error_message}\nPlease try again with a phrase that appears exactly in the overview." if error_message else ""
    
    messages = [
        system_message(TOPIC_TRANSITION_SYSTEM),
        user_message(TOPIC_TRANSITION_USER.format(
            section_title=section_title,
            overview=overview
        ) + retry_prompt)
    ]
    transition_data = llm_complete(messages, model=LLM.CLAUDE_5_SONNET)
    return ensure_json(transition_data or '{}')


#======================================TEXT SLIDE OVERLAYS==========================================

def get_text_slide_concepts(video_plan: VideoPlan, transcript_json: TranscriptOutput) -> List[Dict[str, Any]]:
    
    # Step 1: Extract concepts that need text slides
    logger.info("Extracting concepts that need text slides")
    text_slide_concepts = []
    for section in video_plan.sections:
        for concept in section.concepts:
            # visual is unset when the planner's visual pass was skipped for this video type
            if concept.visual and concept.visual.type == VisualType.TEXT_SLIDE:
                # Create a copy of the concept and add section title for context
                concept_data = concept.model_dump(mode='json')
                concept_data['section_title'] = section.section_title
                text_slide_concepts.append(concept_data)
    logger.info(f"Found {len(text_slide_concepts)} concepts requiring text slides")
    

    # Step 2: Extract transcript data for each text slide concept
    logger.info("Extracting transcript data for each text slide concept")
    transcript_breakdown = transcript_json.lesson_transcript_breakdown
    for concept_data in text_slide_concepts:
        concept_name = concept_data['concept_name']
        # Search through all sections to find matching concept
        for section_name, section_content in transcript_breakdown.sections.items():
            if concept_name in section_content.explanations:
                concept_data['concept_transcript'] = section_content.explanations[concept_name]
                break
        else:
            logger.warning(f"Could not find transcript data for concept: {concept_name}")
    logger.info("Finished extracting transcript data for each concept")
    # remove concepts that don't have transcript data
    text_slide_concepts_filtered = []
    for concept_data in text_slide_concepts:
        if 'concept_transcript' in concept_data:
            concept_data['concept_transcript'] = concept_data['concept_transcript'].model_dump(mode='json')
            text_slide_concepts_filtered.append(concept_data)
    text_slide_concepts = text_slide_concepts_filtered

    return text_slide_concepts

def normalize(text:str)->str:
        return re.sub(r'\W+', '', text).lower()

def phrase_split_to_content_split(content: str, phrases: Tuple[str, str]) -> Tuple[str, str]:
    _, response = llm_call(
        system_prompt = "",
        user_prompt = f"The spoken phrase has been split into two parts:\n<part1>{phrases[0]}</part1>\n<part2>{phrases[1]}</part2>\n\nSplit the written content accordingly: <content>{content}</content>. Split it into two parts and return each inside tags <content1> and <content2> respectively. <content2> can never start with punctuation mark, punctuation at the split point should appear in <content1>.",
        model=LLM.CLAUDE_5_SONNET
    )
    return extract_tag_content("content1", response), extract_tag_content("content2", response)

def split_slide_points_at_visual(slide: TextSlide, phrases: Tuple[str, str]):
    print(phrases)
    print_json(slide.model_dump(), phrases[0])
    visual_subphrase = normalize(" ".join(phrases[0].split(" ")[-3:]) + " ".join(phrases[1].split(" ")[:3]))
    bullet_ii, phrase_jj = next(
        ((ii, jj)
        for ii, bullet in enumerate(slide.elements)
        for jj, phrase in enumerate(bullet.contents)
        if normalize(visual_subphrase) in normalize(phrase.phrase)),
        (None, None)  # Default value if not found
    )

    if bullet_ii is not None and phrase_jj is not None:
        part1 = " ".join(phrases[0].split(" ")[-3:])
        norm_phrase = normalize(slide.elements[bullet_ii].contents[phrase_jj].phrase)
        split_idx = norm_phrase.find(normalize(part1)) + len(normalize(part1))
        char_count = 0
        for i, char in enumerate(slide.elements[bullet_ii].contents[phrase_jj].phrase):
            if normalize(char):
                char_count += 1
            if char_count == split_idx:
                sub_phrase_1, sub_phrase_2 = slide.elements[bullet_ii].contents[phrase_jj].phrase[:i+1], slide.elements[bullet_ii].contents[phrase_jj].phrase[i+1:].lstrip(" ;:,.!?")
                sub_content_1, sub_content_2 = phrase_split_to_content_split(slide.elements[bullet_ii].contents[phrase_jj].content, (sub_phrase_1, sub_phrase_2))
                
                slide.elements[bullet_ii].contents[phrase_jj:phrase_jj+1] = [TextSlidePhrase(content=sub_content_1, phrase=sub_phrase_1), TextSlidePhrase(content=sub_content_2, phrase=sub_phrase_2)]

                print(f"For phrases: {sub_phrase_1} || {sub_phrase_2}\nFound Split: {sub_content_1} || {sub_content_2}")
                break                
    return slide
            
def slides_timings_identifier(slide: TextSlide, point_matches: dict, transcript: str, transcript_timings: TranscriptTiming, slide_start_time: Optional[float] = None) -> Tuple[List[str], TextSlide]:
    def safe_match_segment_timings(transcript_timings: TranscriptTiming, segment_text: str, unmatched_phrases: List[str]):
        try:
            start_index, end_index = match_segment_timings(transcript_timings, segment_text)
            return unmatched_phrases, (start_index, end_index)
        except:
            unmatched_phrases.append(segment_text)
            return unmatched_phrases, (-1, -1)

    failed_matches, (slide_start_index, _) = safe_match_segment_timings(transcript_timings, point_matches['slide_start'], [])
    _, slide_end_index   = match_segment_timings(transcript_timings, ' '.join(transcript.split()[-10:]))
    
    for ii, bullet in enumerate(slide.elements):
        for jj, phrase in enumerate(bullet.contents):
            slide.elements[ii].contents[jj].phrase = next(point['phrase'] for point in point_matches['matches'] if point['point'] == phrase.content)

    # FOR EVERY visual check if visual and appearance of point overlaps. If overlap found, split the point appearance into 2 at the visual appearance point
    if slide.visuals is not None:
        for visual in slide.visuals:
            phrases = visual.phrase
            if isinstance(phrases, tuple):
                print(f"Searching for bullet overlapping with phrase: {phrases}")
                slide = split_slide_points_at_visual(slide, phrases)

    slide = TextSlide(**review_timings(slide.model_dump()))

    for ii, bullet in enumerate(slide.elements):
        bullet_timings = TranscriptTiming(timings=transcript_timings.timings)

        for jj, phrase in enumerate(bullet.contents):            
            # print(phrase.phrase, bullet_timings)
            
            failed_matches, (point_start_index, point_end_index) = safe_match_segment_timings(bullet_timings, phrase.phrase, failed_matches)
            point_start_time = bullet_timings.timings[point_start_index].start_time
            point_end_time = bullet_timings.timings[point_end_index].end_time

            if point_end_time-point_start_time > 0.5: # in case there is a pause after final word 
                point_end_time = bullet_timings.timings[point_end_index].start_time + 0.35
            
            slide.elements[ii].contents[jj].phrase = phrase.phrase
            slide.elements[ii].contents[jj].start_time = point_start_time
            slide.elements[ii].contents[jj].start_duration = point_end_time - point_start_time
            
            bullet_start_index = point_end_index
            bullet_timings = TranscriptTiming(timings=bullet_timings.timings[bullet_start_index:])
            print(point_start_time, phrase.phrase)


    slide.start_time = transcript_timings.timings[slide_start_index].start_time if slide_start_time is None else min(slide_start_time, transcript_timings.timings[slide_start_index].start_time)
    print(slide.start_time)

    slide.end_time   = transcript_timings.timings[slide_end_index + 1 if slide_end_index + 1 < len(transcript_timings.timings) else slide_end_index].end_time

    for ii, bullet in enumerate(slide.elements):
        for jj, phrase in enumerate(bullet.contents): 
            slide.elements[ii].contents[jj].start_time -= slide.start_time
            

    logger.debug(f"Slide: {slide.title} will show between {slide.start_time}-{slide.end_time}s")
    slide.src = ''

    return failed_matches, slide


def text_slide_from_content(slide_content: dict) -> TextSlide:
    """Turn the content LLM's {title, points} into the TextSlide the timing pass expects.

    This conversion was missing entirely: slide_content went straight into
    slides_timings_identifier, which immediately reads slide.elements and so died on a dict.
    One element per point, each holding one phrase whose content is the point verbatim --
    that is the shape the timing pass relies on, since it matches point_matches entries by
    comparing them to phrase.content.

    Indices and times are placeholders; slides_timings_identifier fills them in from the
    speech clock. Built fresh per call because that function mutates what it is given, and
    the retry path runs it a second time with corrected matches.
    """
    return TextSlide(
        title=slide_content['title'],
        start_index=0, end_index=0, start_time=0, end_time=0,
        elements=[
            TextSlideElement(type=TextSlideElementType.TEXT,
                             contents=[TextSlidePhrase(content=point)])
            for point in slide_content['points']
        ],
    )


def process_text_slide_concept(concept_data, transcript_timings):
    try:
        concept_transcript = concept_data['concept_transcript']

        # Determining text slide content with QC
        _, slide_content = llm_call_with_qc(
            history=[
                system_message(TEXT_SLIDE_CONTENT_SYSTEM.format(figure_name=concept_data.get('figure_name', ''))),
                *text_slide_content_examples
            ],
            system_prompt='',
            user_prompt=TEXT_SLIDE_CONTENT_USER.format(
                concept=json.dumps({k:v for k,v in concept_data.items() if v and k in ['concept_name', 'concept', 'facts', 'cross_unit_facts']}, indent=2), 
                transcript=concept_transcript['explanation']
            ),
            qc_requirements=TEXT_SLIDE_QC_REQUIREMENTS.format(
                concept=json.dumps({k:v for k,v in concept_data.items() if k in ['concept_name', 'concept', 'facts', 'cross_unit_facts']}, indent=2),
                transcript=concept_transcript['explanation'],
                figure_name=concept_data.get('figure_name', '')
            ),
            model=LLM.CLAUDE_5_OPUS, is_json=True, tag='answer', type_of_content="text slide content"
        )

        # Determining text slide timings
        history, point_matches = llm_call(
            system_prompt="",
            user_prompt=TEXT_SLIDE_TIMINGS_USER_PROMPT.format(
                points=json.dumps(slide_content["points"], indent=2),
                transcript=concept_transcript['explanation']
            ),
            model=LLM.CLAUDE_5_OPUS,
            history=[system_message(TEXT_SLIDE_TIMINGS_SYSTEM_PROMPT), *text_slides_timings_examples],
            is_json=True
        )
        failed_matches, text_slide = slides_timings_identifier(text_slide_from_content(slide_content), point_matches, concept_transcript['explanation'], transcript_timings)
        if failed_matches:
            _, point_matches = llm_call(
                system_prompt='',
                user_prompt=f"Some identified phrases did not exactly match the text in the transcript. Remember, each identified phrase must match a substring in the transcript exactly. You may need to slightly adjust these mismatches to align with the transcript verbatim. If the match was completely incorrect, try to identify the closest semantic match in the transcript.\n<unmatched_phrases>\n{failed_matches}\n</unmatched_phrases>\nPlease correct only these phrases, leaving the rest of the JSON as it is. Without asking any further questions, return the best JSON you can.",
                model=LLM.CLAUDE_5_SONNET,
                history=history,
                tag='answer',
                is_json=True
            )
            _, text_slide = slides_timings_identifier(text_slide_from_content(slide_content), point_matches, concept_transcript['explanation'], transcript_timings)
            
        return text_slide
    except Exception as e:
        logger.error(f"Error processing text slide for concept {concept_data['concept_name']}: {str(e)}.\n{traceback.format_exc()}")
        raise

def get_text_slide_content(text_slide_concepts: List[Dict[str, Any]], transcript_timings: TranscriptTiming) -> List[TextSlide]:
    # Step 3: Determining the text slide contents and fill TextSlide objects
    logger.info(f"Determining content for {len(text_slide_concepts)} text slides")
    text_slides = []

    
    # Process concepts in parallel using ContextAwareThreadPoolExecutor
    with ContextAwareThreadPoolExecutor(max_workers=4) as executor:
        # Submit all concept processing tasks
        # transcript_timings has to be passed, not closed over: process_text_slide_concept is
        # module-level, so the name was free there and raised NameError on every concept.
        future_to_concept = {executor.submit(process_text_slide_concept, concept_data, transcript_timings): concept_data for concept_data in text_slide_concepts}
        
        # Collect results as they complete
        completed = 0
        for future in as_completed(future_to_concept):
            concept_data = future_to_concept[future]
            try:
                text_slide = future.result()
                text_slides.append(text_slide)
                completed += 1
                logger.info(f"[{completed}/{len(future_to_concept)}] Successfully generated text slide content for concept: {concept_data['concept_name']}")
            except Exception as e:
                logger.error(f"Failed to process text slide for concept {concept_data['concept_name']}: {str(e)}")
                raise  # Re-raise the exception to handle it at a higher level

    
    logger.info(f"Created content for {len(text_slides)} text slides")

    return text_slides

def render_text_slides(context: Context, text_slides: List[TextSlide]) -> List[TextSlide]:
    # Step 4: Render the text slides and fill the src field of the TextSlide objects in parallel
    logger.info(f"Starting parallel rendering of {len(text_slides)} text slides")
    with ProcessPoolExecutor(max_workers=4) as executor:
        # Submit all rendering tasks
        future_to_slide = {executor.submit(render_text_slide_template, context, text_slide): text_slide for text_slide in text_slides}
        # Process results as they complete
        completed = 0
        for future in as_completed(future_to_slide):
            text_slide = future_to_slide[future]
            try:
                text_slide.src = future.result()
                completed += 1
                logger.info(f"[{completed}/{len(future_to_slide)}] Successfully rendered text slide: {text_slide.title}")
            except Exception as e:
                logger.error(f"Failed to render text slide {text_slide.title}: {str(e)}\n{traceback.format_exc()}")
                raise
                
    logger.info(f"Finished parallel rendering of text slides")
    return text_slides

def create_text_slides(context: Context, video_plan: VideoPlan, transcript_json: TranscriptOutput, transcript_timings: TranscriptTiming) -> List[TextSlide]:                
    logger.info("Creating Text Slides")

    text_slide_concepts = get_text_slide_concepts(video_plan, transcript_json)
    if len(text_slide_concepts) == 0:
        logger.info("No text slides to create")
        return []

    text_slides = get_text_slide_content(text_slide_concepts, transcript_timings)

    text_slides = render_text_slides(context, text_slides)

    return text_slides


#======================================DIAGRAM OVERLAYS=============================================


def get_diagram_concepts(video_plan: VideoPlan, transcript_json: TranscriptOutput) -> List[Dict[str, Any]]:

    # STEP 1: Extract concepts that need diagrams
    logger.info("Extracting concepts that need diagrams")
    diagram_concepts = []
    for section in video_plan.sections:
        for concept in section.concepts:
            # visual is unset when the planner's visual pass was skipped for this video type
            if concept.visual and concept.visual.type == VisualType.DIAGRAM:
                # Create a copy of the concept and add section title for context
                concept_data = concept.model_dump(mode='json')
                concept_data['section_title'] = section.section_title
                diagram_concepts.append(concept_data)
    logger.info(f"Found {len(diagram_concepts)} concepts requiring diagrams")


    # STEP 2: Extract transcript data for each diagram concept
    logger.info("Extracting transcript data for each diagram concept")
    transcript_breakdown = transcript_json.lesson_transcript_breakdown
    for concept_data in diagram_concepts:
        concept_name = concept_data['concept_name']
        # Search through all sections to find matching concept
        for section_name, section_content in transcript_breakdown.sections.items():
            if concept_name in section_content.explanations:
                concept_data['concept_transcript'] = section_content.explanations[concept_name]
                break
        else:
            logger.warning(f"Could not find transcript data for concept: {concept_name}")
    logger.info("Finished extracting transcript data for each diagram concept")
    # remove concepts that don't have transcript data
    diagram_concepts_filtered = []
    for concept_data in diagram_concepts:
        if 'concept_transcript' in concept_data:
            concept_data['concept_transcript'] = concept_data['concept_transcript'].model_dump(mode='json')
            diagram_concepts_filtered.append(concept_data)
    diagram_concepts = diagram_concepts_filtered

    return diagram_concepts


def identify_diagram_timings(Model: BaseDiagram, contents: dict, transcript: str, transcript_timings: TranscriptTiming, custom: str = '', is_section: bool = False, start_time: float = -1) -> BaseDiagram:
    history, phrase_matched_content = llm_call(
        system_prompt=DIAGRAM_TIMINGS_SYSTEM_PROMPT.format(model=get_diagram_model(Model)),
        user_prompt=DIAGRAM_TIMINGS_USER_PROMPT.format(
            points=json.dumps({k: v for k,v in contents.items() if k!='visuals'}, indent=2),
            transcript=transcript,
            custom=custom
        ),
        model=LLM.CLAUDE_5_SONNET,
        tag='answer',
        is_json=True,
    )

    phrase_matched_content = review_timings(phrase_matched_content)

    diagram_model = Model(**{**phrase_matched_content, "is_section": is_section, "start_time": start_time})
    try:
        diagram_model.fill_timings(transcript_timings)
        return diagram_model
    except ValueError as e:
        unmatched_phrases = str(e)
    
    _, phrase_matched_content = llm_call(
        system_prompt='',
        user_prompt=f"Some identified phrases did not exactly match the text in the transcript. Remember, each identified phrase must match a substring in the transcript exactly. You may need to slightly adjust these mismatches to align with the transcript verbatim. If the match was completely incorrect, try to identify the closest semantic match in the transcript.\n<unmatched_phrases>\n{unmatched_phrases}\n</unmatched_phrases>\nPlease correct only these phrases, leaving the rest of the JSON as it is. Without asking any further questions, return the best JSON you can.",
        model=LLM.CLAUDE_5_SONNET,
        history=history,
        tag='answer',
        is_json=True
    )

    diagram_model = Model(**{**phrase_matched_content, "is_section": is_section})
    diagram_model.fill_timings(transcript_timings)

    return diagram_model


def process_diagram_concept(concept_data, transcript_timings):
    try:
        # Get the transcript data for this concept
        concept_transcript = concept_data['concept_transcript']

        # First determine diagram content with QC
        diagram_config = DIAGRAM_CONFIGS[concept_data['visual']['diagram_type']]
        _, diagram_content = llm_call_with_qc(
            system_prompt=get_diagram_content_system_prompt(concept_data['visual']['diagram_type']),
            user_prompt=get_diagram_content_user_prompt(
                diagram_type=concept_data['visual']['diagram_type'],
                concept_data=json.dumps({k:v for k,v in concept_data.items() if v and k in ['concept_name', 'concept', 'facts', 'cross_unit_facts']}, indent=2),
                explanation=concept_transcript['explanation'],
                figure_name=concept_data['figure_name']
            ),
            model=LLM.CLAUDE_5_OPUS,
            qc_requirements=DIAGRAM_QC_REQUIREMENTS.format(
                diagram_type=concept_data['visual']['diagram_type'],
                diagram_specific_requirements=diagram_config["qc_requirements"],
                concept=json.dumps({k:v for k,v in concept_data.items() if v and k in ['concept_name', 'concept', 'facts', 'cross_unit_facts']}, indent=2),
                transcript=concept_transcript['explanation'],
                figure_name=concept_data['figure_name']
            ),
            is_json=True, type_of_content=f"{diagram_config['type']} diagram content"
        )

        start_index, _ = match_segment_timings(transcript_timings, " ".join(concept_transcript['explanation'].split()[0:10]))
        _, end_index = match_segment_timings(transcript_timings, " ".join(concept_transcript['explanation'].split()[-10:]))
        diagram_segment_transcript_timings = TranscriptTiming(timings=transcript_timings.timings[start_index: end_index + 1])

        # -1, not None, is identify_diagram_timings' "unknown start" sentinel, and the diagram
        # models require a float, so None reached Model(**...) and failed validation. Tested
        # against None rather than falsiness so a genuine 0.0 survives.
        concept_start = concept_data.get("start_time")

        # Create diagram model with timings
        diagram_model = identify_diagram_timings(
            models[concept_data['visual']['diagram_type']], diagram_content,
            concept_transcript['explanation'], diagram_segment_transcript_timings,
            custom='- This text is designed for a tree diagram. Some node titles may not appear in the transcript as they represent implicit groupings. Regardless, assign a phrase to each node. Ensure that the phrase appears before its child node phrases and is logically placed when the transcript discusses the relevant subject.\n- Also remember to ensure the phrase begins at the exact starting point of the text for each title node. The end can extend beyond, but the beginning must coincide with the start of the point.\n- To reiterate parent node phrases must precede the child node phrase at all times. This is an absolute requirement.\n- Make sure your JSON response adheres to the Pydantic model of TreeDiagram provided.' if concept_data['visual']['diagram_type']=='tree' else '',
            start_time=-1 if concept_start is None else concept_start
        )

        # Create Diagram object
        diagram = Diagram(
            type=DiagramType(concept_data['visual']['diagram_type']),
            data=diagram_model,
            start_index=start_index,
            end_index=end_index,
            start_time=diagram_model.start_time,
            end_time=transcript_timings.timings[end_index + 1 if end_index + 1 < len(transcript_timings.timings) else end_index].end_time,
            src=''  # Will be filled later
        )
        logger.debug(f"For concept: '{concept_data['concept_name']}'. Diagram start and end is: {transcript_timings.timings[start_index].text} - {transcript_timings.timings[end_index+1].text} or {round(diagram.start_time, 3)} - {round(diagram.end_time, 3)}s ")
        
        return diagram
        
    except Exception as e:
        logger.error(f"Error processing diagram for concept {concept_data['concept_name']}: {str(e)}\n{traceback.format_exc()}")
        raise


def get_diagram_content(diagram_concepts: List[Dict[str, Any]], transcript_timings: TranscriptTiming) -> List[Diagram]:
    # STEP 3: Determining the data for each diagram type

    logger.info("Determining content for Diagrams")
    diagrams: List[Diagram] = []


    # Process concepts in parallel using ContextAwareThreadPoolExecutor
    with ContextAwareThreadPoolExecutor(max_workers=4) as executor:
        # Submit all concept processing tasks
        # Same omission as the text slide path, failing the other way round: this one already
        # declares transcript_timings, so the missing argument was a TypeError per concept.
        future_to_concept = {executor.submit(process_diagram_concept, concept_data, transcript_timings): concept_data for concept_data in diagram_concepts}
        
        # Collect results as they complete
        completed = 0
        for future in as_completed(future_to_concept):
            concept_data = future_to_concept[future]
            try:
                diagram = future.result()
                diagrams.append(diagram)
                completed += 1
                logger.info(f"[{completed}/{len(future_to_concept)}] Successfully generated diagram content for concept: {concept_data['concept_name']}")
            except Exception as e:
                logger.error(f"Failed to process diagram for concept {concept_data['concept_name']}: {str(e)}")
                raise  # Re-raise the exception to handle it at a higher level

    logger.info(f"Created content for {len(diagrams)} diagrams")

    return diagrams

def extract_intro_overview_segment(introduction: str, section_names: str):
    messages = [
        system_message(LESSON_ORGANIZER_IDENTIFIER_SYSTEM),
        user_message(LESSON_ORGANIZER_IDENTIFIER_USER.format(
            introduction=introduction,
            sections=section_names
        ))
    ]
    lesson_organizer_part = llm_complete(messages, model=LLM.GPT_5)
    return lesson_organizer_part, messages+[assistant_message(lesson_organizer_part)]

def get_lesson_overview_diagram_contents(video_plan: VideoPlan, transcript_json: TranscriptOutput, transcript_timings: TranscriptTiming) -> Diagram:
    # EXTRA STEP: Create lesson overview diagram
    logger.info("Generating lesson overview diagram content")
    section_names = [section.section_title for section in video_plan.sections]
    lesson_organizer_part, history = extract_intro_overview_segment(transcript_json.lesson_transcript_breakdown.introduction, section_names)
    
    # Match the identified segment with retries
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            start_index, end_index = match_segment_timings(transcript_timings, str(lesson_organizer_part))
            break
        except ValueError as e:
            if attempt < max_retries:
                # Ask LLM to try again with a different segment
                logger.warning(f"Attempt {attempt + 1}: Failed to match lesson organizer segment. Retrying...")
                _, lesson_organizer_part = llm_call(
                    system_prompt='',
                    user_prompt=f"The identified part did not exactly match the text in the transcript. Remember, the segment you return must exactly match a verbatim substring in the transcript. Please try to identify the part again, only return the required part and nothing else.",
                    model=LLM.GPT_5,
                    history=history,
                    is_json=False
                )
            else:
                # Fall back to using the first and last parts of introduction
                logger.warning("All attempts failed for lesson organizer segment. Falling back to full introduction...")
                lesson_organizer_part = transcript_json.lesson_transcript_breakdown.introduction
                start_index, _ = match_segment_timings(transcript_timings, " ".join(lesson_organizer_part.split()[0:5]))
                _, end_index = match_segment_timings(transcript_timings, " ".join(lesson_organizer_part.split()[-5:]))

    lesson_organizer_timings = TranscriptTiming(timings=transcript_timings.timings[start_index: end_index + 1])

    organizer_data = {
        "root": {"title": video_plan.simple_title, "icon": ""},
        "categories": [{"title": {"text": section.simple_title, "icon": ""}, "points": []} for section in video_plan.sections]
    }
    messages = [
        system_message(LESSON_ORGANIZER_CONTENT_SYSTEM),
        user_message(LESSON_ORGANIZER_CONTENT_USER.format(organizer_data=json.dumps(organizer_data, indent=2)))
    ]
    lesson_organizer_data = llm_complete(messages, model=LLM.GPT_5)
    lesson_organizer_data = ensure_json(lesson_organizer_data or json.dumps(organizer_data))
    # print_json(lesson_organizer_data)

    diagram_model = identify_diagram_timings(
        MindMap, lesson_organizer_data, 
        lesson_organizer_part, lesson_organizer_timings,
        custom='This is an introduction, just identify the exact phrase where each node is being introduced.'
    )
    logger.debug(f"Lesson organizer data: {json.dumps(diagram_model.model_dump(), indent=2)}")
    diagram = Diagram(
        type=DiagramType.LESSON_ORGANIZER if len(diagram_model.categories) < 3 else DiagramType.MIND_MAP,
        data=diagram_model,
        start_index=start_index,
        end_index=end_index,
        start_time=transcript_timings.timings[start_index].start_time,
        end_time=transcript_timings.timings[end_index + 1 if end_index + 1 < len(transcript_timings.timings) else end_index].end_time,
        src=''  # Will be filled later
    )
    logger.debug(f"For lesson intro. Diagram start and end is: {transcript_timings.timings[start_index].text} - {transcript_timings.timings[end_index+1].text} or {round(diagram.start_time, 3)} - {round(diagram.end_time, 3)}s ")
    logger.info(f"Lesson overview diagram content generated")
    return diagram


def get_section_overview_diagram_contents(video_plan: VideoPlan, transcript_json: TranscriptOutput, transcript_timings: TranscriptTiming, lesson_overview_diagram: Union[Diagram, None], video_split_times: Dict[str, float]) -> List[Diagram]:
    # EXTRA STEP: Add section overview diagrams
    logger.info("Generating section overview diagram contents")
    section_diagrams = []

    for section in video_plan.sections:
        # Find the section overview in transcript
        section_overview = None
        for section_name, section_content in transcript_json.lesson_transcript_breakdown.sections.items():
            if len(video_plan.sections) == 1:
                concept_names = [concept.concept_name for concept in section.concepts]
                section_overview, history = extract_intro_overview_segment(transcript_json.lesson_transcript_breakdown.introduction, concept_names)
                break
            if section_name == section.section_title:
                section_overview = section_content.overview
                break
        if not section_overview:
            logger.warning(f"Could not find overview for section: {section.section_title}")
            continue
        # Get concept names for this section
        concept_names = [concept.concept_name for concept in section.concepts]
        messages = [
            system_message(SECTION_ORGANIZER_IDENTIFIER_SYSTEM),
            user_message(SECTION_ORGANIZER_IDENTIFIER_USER.format(
                overview=section_overview,
                concepts=concept_names
            ))
        ]
        history = [messages[0]]
        section_organizer_part = llm_complete(messages, model=LLM.GPT_5)
        
        # Match the identified segment with retries
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                start_index, end_index = match_segment_timings(transcript_timings, str(section_organizer_part))
                break
            except ValueError as e:
                if attempt < max_retries:
                    # Ask LLM to try again with different phrases
                    logger.warning(f"Attempt {attempt + 1}: Failed to match section organizer segment for section {section.section_title}. Retrying...")
                    _, section_organizer_part = llm_call(
                        system_prompt='',
                        user_prompt=f"The identified part did not exactly match the text in the transcript. Remember, the segment you return must exactly match a verbatim substring in the transcript. Please try to identify the part again, only return the required part and nothing else.",
                        model=LLM.GPT_5,
                        history=history,
                        is_json=False
                    )
                else:
                    # Fall back to using the full overview
                    logger.warning(f"All attempts failed for section organizer segment in section {section.section_title}. Falling back to full overview...")
                    start_index, _ = match_segment_timings(transcript_timings, " ".join(section_overview.split()[0:5]))
                    _, end_index = match_segment_timings(transcript_timings, " ".join(section_overview.split()[-5:]))

        section_organizer_timings = TranscriptTiming(timings=transcript_timings.timings[start_index: end_index + 1])
        section_title_icon = None
        if lesson_overview_diagram:
            for category in lesson_overview_diagram.data.categories:
                if category.title.text == section.simple_title:
                    section_title_icon = category.title.icon
                    break
        messages = [
            system_message(SECTION_ORGANIZER_CONTENT_SYSTEM.format(overview=section_organizer_part)),
            user_message(SECTION_ORGANIZER_CONTENT_USER.format(
                section_title=section.simple_title,
                concepts=concept_names
            )+(f"\n\nUse the icon: '{section_title_icon}' for the section title." if section_title_icon else ''))
        ]
        section_organizer_data = llm_complete(messages, model=LLM.CLAUDE_5_SONNET)
        section_organizer_data = ensure_json(extract_tag_content('mind_map', section_organizer_data) or '{}')

        section_start_time = next((val for val in video_split_times.values() if 0 < section_organizer_timings.timings[0].start_time - val < 1),
                                   section_organizer_timings.timings[0].start_time)
        
        diagram_model = identify_diagram_timings(
            MindMap, section_organizer_data,
            section_organizer_part, section_organizer_timings,
            custom='This is a section overview, just identify the exact phrase where each node is being introduced.',
            is_section=len(video_plan.sections) > 1, start_time=section_start_time
        )
        logger.debug(f"Section organizer data for {section.section_title} starts at {diagram_model}")
        section_diagrams.append(Diagram(
            type=DiagramType.LESSON_ORGANIZER if len(diagram_model.categories) < 3 else DiagramType.MIND_MAP,
            data=diagram_model,
            start_index=start_index,
            end_index=end_index,
            start_time=diagram_model.start_time,
            end_time=transcript_timings.timings[end_index + 1 if end_index + 1 < len(transcript_timings.timings) else end_index].end_time,
            src=''  # Will be filled later
        ))
        logger.debug(f"For section: {section.section_title}. Diagram start and end is: {transcript_timings.timings[start_index].text} - {transcript_timings.timings[end_index+1].text} or {round(section_diagrams[-1].start_time, 3)} - {round(section_diagrams[-1].end_time, 3)}s ")
        logger.info(f"[{len(section_diagrams)}/{len(video_plan.sections)}] Section overview diagram content generated for {section.section_title}")
    logger.info(f"Section overview diagram contents generated for {len(section_diagrams)} sections")
    return section_diagrams


def render_diagrams(context: Context, diagrams: List[Diagram]) -> List[Diagram]:
    # STEP 4: Render the diagrams and fill the src field of the Diagram objects in parallel
    logger.info(f"Starting parallel rendering of {len(diagrams)} diagrams")
    with ProcessPoolExecutor(max_workers=4) as executor:
        # Submit all rendering tasks
        future_to_diagram = {executor.submit(render_diagram_template, context, diagram): diagram for diagram in diagrams}
        # Process results as they complete
        completed = 0
        for future in as_completed(future_to_diagram):
            diagram = future_to_diagram[future]
            try:
                diagram.src = future.result()
                completed += 1
                logger.info(f"[{completed}/{len(diagrams)}] Successfully rendered diagram ({diagram.type})")
            except Exception as e:
                logger.error(f"Failed to render diagram: {str(e)}\n{traceback.format_exc()}")
                raise
                
    logger.info(f"Finished parallel rendering of diagrams")
    return diagrams


def create_diagrams(context: Context, video_plan: VideoPlan, transcript_json: TranscriptOutput, transcript_timings: TranscriptTiming, video_split_times: Dict[str, float], include_concept_diagrams: bool = True, include_overviews: bool = True) -> List[Diagram]:
    """Every rendered diagram the enabled layers ask for: per-concept ones and/or the overviews."""
    logger.info("Creating Diagrams")

    if include_concept_diagrams:
        diagram_concepts = get_diagram_concepts(video_plan, transcript_json)
        diagrams = get_diagram_content(diagram_concepts, transcript_timings)
    else:
        logger.info("LAYER_INFOGRAPHICS off: no per-concept diagrams")
        diagrams = []

    if not include_overviews:
        logger.info("LAYER_OVERVIEW_DIAGRAMS off: no lesson or section overview diagrams")
        return render_diagrams(context, diagrams) if diagrams else []

    if len(video_plan.sections)>1:
        lesson_overview_diagram = get_lesson_overview_diagram_contents(video_plan, transcript_json, transcript_timings)
        diagrams.append(lesson_overview_diagram)
    else:
        lesson_overview_diagram = None

    section_overview_diagrams = get_section_overview_diagram_contents(video_plan, transcript_json, transcript_timings, lesson_overview_diagram, video_split_times)
    diagrams.extend(section_overview_diagrams)

    diagrams = render_diagrams(context, diagrams)

    return diagrams


# ========================================CONCLUSION OVERLAY========================================

def create_conclusion_slide(context: Context, transcript: TranscriptOutput, transcript_timings: TranscriptTiming) -> Diagram:
    first_sentence = " ".join(transcript.lesson_transcript_breakdown.conclusion.split()[:10])
    start_index, end_index  = match_segment_timings(transcript_timings, first_sentence)
    conclusion_timings      = TranscriptTiming(timings=transcript_timings.timings[start_index:])

    slide = identify_diagram_timings(
        ConclusionSlideNew, transcript.lesson_transcript_breakdown.conclusion_slide.model_dump(),
        transcript.lesson_transcript_breakdown.conclusion, conclusion_timings,
        custom='- As this is a conclusion, identify the exact phrase where each main point and sub-point is introduced.\n- The phrase for the main point should precede the sub-point.\n- The conclusion format follows this sequence: Main Point 1 phrase => Sub Point 1 Phrase => Main Point 2 phrase => Sub Point 2... Ensure to extract the best matching phrases in this exact order, rather than pulling from various parts of the transcript.\n  - In other words, the phrase for sub-point 1 should never appear before main point 2, and so on.\n- Concentrate on the middle part, typically paragraph 2, and extract phrases from there only. This is where all the matching phrases for the points are usually found.\n- Each phrase should be at least 5 words long, with the start of phrase exactly aligned with the bullet and not earlier.',
        start_time=conclusion_timings.timings[0].start_time
    )

    slide.fill_timings(conclusion_timings)

    conclusion = Diagram(
        type=DiagramType.CONCLUSION,
        data=slide,
        start_time=conclusion_timings.timings[0].start_time,
        end_time=transcript_timings.timings[-1].end_time,
        start_index=start_index,
        end_index=end_index
    )
    conclusion.src = render_diagram_template(context, conclusion)
    logger.info(f"Conclusion Slide limits are {transcript_timings.timings[start_index].text} and {conclusion.start_time} - {conclusion.end_time}")
    return conclusion


#=========================================MAIN========================================================

if __name__ == '__main__':
    from config.courses import get_execution_input
    from core.context import prep_content_gen_input
    from core.clients.s3 import download, upload_file_to_s3
    setup_logging(level=logging.DEBUG)
    exec_input    = get_execution_input(
        subject = "AP World History - Unit_1_v2", 
        subsection = "Explain the effects of innovation on the Chinese economy over time."
    )
    context = Context(**prep_content_gen_input(exec_input))

    # print_json(generate_text_overlays('', '', context.dict()))
    assets = OverlaysData(**load_json_from_s3(context.text_overlays_path))

    diagram = next(asset for asset in assets.diagrams if asset.end_time>600 and asset.start_time<600)

    print_json(diagram.model_dump())
    print(diagram.src)

    diagram = Diagram(**json.loads())
    print(render_diagram_template(context, diagram))
    # download(diagram.src, os.path.basename(diagram.src))