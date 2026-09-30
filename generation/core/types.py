import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from core.helpers import (
    generate_img_prompt, generate_video_prompt, fix_single_icon)
from core.stage_constants import \
    VALID_FA_ICONS
from core.clients.images import GeneratedImageTypes
from pydantic import BaseModel, Field, model_validator, validator
from core.hash import hash_image_description

logger = logging.getLogger(__name__)

class LayerName(str, Enum):
    PLANNER = "planner"
    TRANSCRIPT = "transcript"
    AVATAR = "avatar"
    OVERLAYS = "overlays"
    CLIPS = "clips"
    IMAGES = "images"
    VIDEOS = "videos"
    RENDER = "render"


# =========================== VIDEO PLAN TYPES ===========================

class VisualType(str, Enum):
    TEXT_SLIDE = "text_slide"
    DIAGRAM = "diagram"

class DiagramType(str, Enum):
    MIND_MAP = "mind_map"
    # FLOW_CHART = "flow_chart"
    TREE = "tree"
    VENN_DIAGRAM = "venn_diagram"
    LESSON_ORGANIZER = "lesson_organizer"
    CONCLUSION = "conclusion_slide_new"

class TeachingTechnique(str, Enum):
    SAMENESS_AND_DIFFERENCE = "Sameness and Difference Principle"
    SETUP_PRINCIPLE = "Setup Principle"
    CONTEXTUALIZATION = "Contextualization Technique"
    STORYTELLING = "Storytelling Technique"
    SIMPLE_EXPLANATION = "Simple Explanation"

class Visual(BaseModel):
    type: VisualType
    diagram_type: Optional[Union[Literal[""], DiagramType]] = None
    justification: str

class TeachingTechniqueInfo(BaseModel):
    choice: TeachingTechnique
    suggestion: str

class Concept(BaseModel):
    concept_name: str
    concept: str
    facts: List[str]
    visual: Optional[Visual] = None
    teaching_techniques: List[TeachingTechniqueInfo] = []

class ConceptJustifications(BaseModel):
    for_grouping: str
    for_ordering: str

class Section(BaseModel):
    section_title: str
    simple_title: str = ''
    concepts: List[Concept]
    concept_justifications: ConceptJustifications

class SectionJustifications(BaseModel):
    for_grouping: str
    for_ordering: str

class VideoPlan(BaseModel):
    lesson_title: str
    simple_title: str = ''
    sections: List[Section]
    section_justifications: SectionJustifications

# =========================== IMAGES AND VIDEOS TYPES ===========================
class Media(BaseModel):
    type: str
    description: str
    id: Optional[str] = ''
    img_prompt: Optional[str] = ''
    video_prompt: Optional[str] = ''

    subject: Any = Field(default=None, exclude=True)

    @model_validator(mode='after')
    def enforce_prompts(self):
        subject = self.subject
        if not self.img_prompt:
            self.img_prompt = generate_img_prompt(subject, self.description)
        if not self.video_prompt and self.type.upper() == 'VIDEO':
            self.video_prompt = generate_video_prompt(subject, self.description, self.img_prompt)
        if not self.id:
            self.id = hash_image_description(self.description)
        return self

class Clip(BaseModel):
    text: str
    media: Media  # Assuming Media is defined elsewhere
    range: Optional[Tuple[int, int]] = None
    start_time: float
    end_time: float
    duration: float = None
    duration_valid: bool = False
    location: Optional[str] = None
 
    @model_validator(mode='after')
    def set_duration_and_validate(self):
        if self.duration is None:
            self.duration = round(self.end_time - self.start_time, 3)
        self.duration_valid = 5 <= self.duration <= 9
        return self

class Severity(Enum):
    MINOR="MINOR"
    NOTICEABLE="NOTICEABLE"
    SIGNIFICANT="SIGNIFICANT"

class VideoClipQC(BaseModel):
    passed: bool
    reason: str
    severity: Optional[Severity] = None 

    model_config = {
        "use_enum_values": True
    }
    
class VideoDetails(BaseModel):
    src: str
    prompt: Optional[str] = None
    model: Optional[str] = None # DALLE || MIDJOURNEY
    qc: Optional[VideoClipQC] = None
    retry: int = 0

class VideoMetadata(BaseModel):
    prompt: str
    id: str
    videos: List[VideoDetails]
    n_regenerations: int = 0
    human_choice: Optional[int] = 0

class ImageDetails(BaseModel):
    src: str
    prompt: Optional[str] = None
    model: Optional[str] = None # DALLE || MIDJOURNEY

class ImagesMetadata(BaseModel):
    prompt: str
    id: str
    image: List[ImageDetails]
    type: GeneratedImageTypes = GeneratedImageTypes.FLUX
    n_regenerations: int = 0
    qc_choice: Optional[int] = None
    human_choice: Optional[int] = None
    evaluation: Optional[dict] = None
    
    def dict(self, **kwargs):
        d = super().dict(**kwargs)
        d['type'] = self.type.value
        return d

    def get_best_image(self)->ImageDetails:
        if self.human_choice is not None:
            image_idx = self.human_choice
        elif self.qc_choice is not None:
            image_idx = self.qc_choice
        else:
            image_idx = 0
        return self.image[image_idx]
    
    @validator('type', pre=True)
    def validate_type(cls, value):
        if value == "ai":
            return GeneratedImageTypes.FLUX
        return value

# =========================== RENDER TYPES ==============================


# =========================== AUDIO TIMING TYPES ===========================
class WordTiming(BaseModel):
    text: str
    start_time: float
    end_time: float


class TranscriptTiming(BaseModel):
    timings: List[WordTiming]

# =========================== OVERLAYS TYPES ===========================
class DiagramVisual(BaseModel):
    src: str
    caption: str
    fact: str
    phrase: Union[str, Tuple[str, str]] = ''
    start_time: float = 0
    end_time: float = 0

class BaseDiagram(ABC, BaseModel):
    start_phrase: str = ""
    start_time: float = -1
    visuals: Optional[List[DiagramVisual]] = None

    def model_post_init(self, __context: Any) -> None:
        """Called after the model is fully initialized"""
        self.fix_icons()

    def match_segment_timings(self, transcript_timings: TranscriptTiming, segment_text: str, unmatched_phrases: List[str]):
        from core.media.clip_timings import match_segment_timings
        try:
            start_index, end_index = match_segment_timings(transcript_timings, segment_text)
            # Fallback for incorrect start_time
            current_start_time = transcript_timings.timings[start_index].start_time
            if current_start_time < self.start_time:
                self.start_time = current_start_time
                self.start_phrase = segment_text
            return unmatched_phrases, (start_index, end_index)
        except:
            unmatched_phrases.append(segment_text)
            return unmatched_phrases, (-1, -1)    

    def initialize_start_time(self, transcript_timings: TranscriptTiming, failed_phrases: List[str]) -> List[str]:
        """Common method to initialize start_time for all diagrams"""

        if self.start_time < 0:
            if self.start_phrase != "":
                failed_phrases, (start_index, end_index) = self.match_segment_timings(transcript_timings, self.start_phrase, failed_phrases)
                self.start_time = transcript_timings.timings[start_index].start_time
            else:
                self.start_time = transcript_timings.timings[0].start_time
        return failed_phrases

    def fill_visual_timings(self, transcript_timings: TranscriptTiming) -> List[str]:
        failed_phrases = []

        for artifact in self.visuals:
            if not artifact.phrase:
                continue

            if isinstance(artifact.phrase, str):
                failed_phrases, (start_index, end_index) = self.match_segment_timings(transcript_timings, artifact.phrase, failed_phrases)
                artifact.start_time = transcript_timings.timings[start_index].start_time - self.start_time
                artifact.end_time = transcript_timings.timings[end_index].end_time - self.start_time

            else:
                failed_phrases, (_, start_index) = self.match_segment_timings(transcript_timings, artifact.phrase[0], failed_phrases)
                failed_phrases, (end_index, _) = self.match_segment_timings(transcript_timings, artifact.phrase[1], failed_phrases)

                artifact.start_time = transcript_timings.timings[start_index].start_time - self.start_time
                artifact.end_time = transcript_timings.timings[end_index].end_time - self.start_time

        if failed_phrases:
            raise ValueError(f"Failed to match phrases: {failed_phrases}")
        
        return failed_phrases

    @abstractmethod
    def fill_timings(self, transcript_timings: TranscriptTiming):
        pass

    @abstractmethod
    def fix_icons(self):
        pass
        
class MindMap(BaseDiagram):
    class RootNode(BaseModel):
        title: str
        icon: str
        
    class Category(BaseModel):
        class TimedText(BaseModel):
            text: str
            icon: str
            phrase: str = ""
            start_time: float = 0

        title: TimedText
        points: List[TimedText]   
                
    root: RootNode
    categories: List[Category]
    # visuals: Optional[List[DiagramVisual]] = None
    is_section: bool = False

    def fill_timings(self, transcript_timings: TranscriptTiming):
        failed_phrases = []
        failed_phrases = self.initialize_start_time(transcript_timings, failed_phrases)
        
        # First pass: Get all timings and set self.start_time to the minimum
        for category in self.categories:
            failed_phrases, (start_index, end_index) = self.match_segment_timings(transcript_timings, category.title.phrase, failed_phrases)
            category.title.start_time = transcript_timings.timings[start_index].start_time - 0.5
            
            for point in category.points:
                failed_phrases, (start_index, end_index) = self.match_segment_timings(transcript_timings, point.phrase, failed_phrases)
                point.start_time = transcript_timings.timings[start_index].start_time - 0.5
            
            category.points.sort(key=lambda x: x.start_time)
            category.title.start_time = min([category.title.start_time] + [point.start_time for point in category.points])

        self.categories.sort(key=lambda x: x.title.start_time)

        # Second pass: Adjust all timings relative to diagram start time
        # (By now, self.start_time is set to the minimum start_time of all elements in the diagram)
        self.start_time -= 0.5
        for category in self.categories:
            category.title.start_time -= self.start_time
            for point in category.points:
                point.start_time -= self.start_time

        if failed_phrases:
            raise ValueError(f"Failed to match phrases: {failed_phrases}")
        return self

    def fix_icons(self):
        self.root.icon = fix_single_icon(self.root.icon, self.root.title, VALID_FA_ICONS)
        for category in self.categories:
            category.title.icon = fix_single_icon(category.title.icon, category.title.text, VALID_FA_ICONS)
        return self

class VennDiagram(BaseDiagram):
    class RootNode(BaseModel):
        title: str
        subtitle: str

    class Circle(BaseModel):
        class TimedText(BaseModel):
            text: str
            phrase: str
            start_time: float = 0

        name: TimedText
        points: List[TimedText]

    root: RootNode
    circles: List[Circle]
    intersection: Circle.TimedText
    # visuals: Optional[List[DiagramVisual]] = None

    def fill_timings(self, transcript_timings: TranscriptTiming):
        failed_phrases = []
        failed_phrases = self.initialize_start_time(transcript_timings, failed_phrases)
        
        # First pass: Get all timings and set self.start_time to the minimum
        for circle in self.circles:
            failed_phrases, (start_index, end_index) = self.match_segment_timings(transcript_timings, circle.name.phrase, failed_phrases)
            circle.name.start_time = transcript_timings.timings[start_index].start_time - 0.5
            
            for point in circle.points:
                failed_phrases, (start_index, end_index) = self.match_segment_timings(transcript_timings, point.phrase, failed_phrases)
                point.start_time = transcript_timings.timings[start_index].start_time - 0.5
            
            circle.points.sort(key=lambda x: x.start_time)
            circle.name.start_time = min([circle.name.start_time] + [point.start_time for point in circle.points])

        self.circles.sort(key=lambda x: x.name.start_time)

        failed_phrases, (start_index, end_index) = self.match_segment_timings(transcript_timings, self.intersection.phrase, failed_phrases)
        self.intersection.start_time = transcript_timings.timings[start_index].start_time - 0.5

        # Second pass: Adjust all timings relative to diagram start time
        # (By now, self.start_time is set to the minimum start_time of all elements in the diagram)
        self.start_time -= 0.5
        for circle in self.circles:
            circle.name.start_time -= self.start_time
            for point in circle.points:
                point.start_time -= self.start_time
        self.intersection.start_time -= self.start_time

        if failed_phrases:
            raise ValueError(f"Failed to match phrases: {failed_phrases}")
        return self

    def fix_icons(self):
        pass
    
class TreeDiagram(BaseDiagram):
    class RootNode(BaseModel):
        class Node(BaseModel):
            class TimedNode(BaseModel):
                title: str
                description: Optional[str] = None
                icon: str
                phrase: str
                start_time: float = 0
                children: Optional[List['TreeDiagram.RootNode.Node.TimedNode']] = None
                is_root: bool = False
        
        title: str
        icon: str
        children: List[Node.TimedNode]
        is_root: bool = True

    tree: RootNode
    # visuals: Optional[List[DiagramVisual]] = None

    def fill_timings(self, transcript_timings: TranscriptTiming):
        failed_phrases = []
        failed_phrases = self.initialize_start_time(transcript_timings, failed_phrases)

        def fill_node_timings(node, failed_phrases):
            failed_phrases, (start_index, end_index) = self.match_segment_timings(transcript_timings, node.phrase, failed_phrases)
            node.start_time = transcript_timings.timings[start_index].start_time - 0.5
            if node.children:
                for child in node.children:
                    failed_phrases = fill_node_timings(child, failed_phrases)
                
                node.children.sort(key=lambda x: x.start_time)
                node.start_time = min([node.start_time] + [child.start_time for child in node.children])
            return failed_phrases

        # First pass: Get all timings and set self.start_time to the minimum
        for child in self.tree.children:
            failed_phrases = fill_node_timings(child, failed_phrases)

        self.tree.children.sort(key=lambda x: x.start_time)

        # Second pass: Adjust all timings relative to diagram start time
        # (By now, self.start_time is set to the minimum start_time of all elements in the diagram)
        self.start_time -= 0.5
        def adjust_node_timings(node):
            node.start_time -= self.start_time
            if node.children:
                for child in node.children:
                    adjust_node_timings(child)

        for child in self.tree.children:
            adjust_node_timings(child)

        if failed_phrases:
            raise ValueError(f"Failed to match phrases: {failed_phrases}")
        return self

    def fix_icons(self):
        self.tree.icon = fix_single_icon(self.tree.icon, self.tree.title, VALID_FA_ICONS)
        
        def fix_node_icons(node):
            node.icon = fix_single_icon(node.icon, node.title, VALID_FA_ICONS)
            if node.children:
                for child in node.children:
                    fix_node_icons(child)
        
        for child in self.tree.children:
            fix_node_icons(child)
            
        return self

class ConclusionSlideNew(BaseDiagram):
    class MainBullet(BaseModel):
        class SubBullet(BaseModel):
            text: str
            phrase: str = ""
            start_time: float = 0

        text: str
        phrase: str = ""
        start_time: float = 0
        sub_points: List[SubBullet] = []
    
    title: str
    subtitle: Optional[str] = None
    bullets: List[MainBullet]

    def fill_timings(self, transcript_timings: TranscriptTiming):
        failed_phrases = []
        base_start_time = transcript_timings.timings[0].start_time

        for bullet in self.bullets:
            if bullet.phrase:
                failed_phrases, (start_idx, end_idx) = self.match_segment_timings(transcript_timings, bullet.phrase, failed_phrases)
                bullet.start_time = transcript_timings.timings[start_idx].start_time - base_start_time - 0.5

            for sub in bullet.sub_points:
                if sub.phrase:
                    failed_phrases, (start_idx, end_idx) = self.match_segment_timings(transcript_timings, sub.phrase, failed_phrases)
                    sub.start_time = transcript_timings.timings[start_idx].start_time - base_start_time - 0.5

            if bullet.sub_points:
                bullet.start_time = min([bullet.start_time] + [sub.start_time for sub in bullet.sub_points])

        self.bullets.sort(key=lambda x: x.start_time)

        if failed_phrases:
            raise ValueError(f"Failed to match phrases: {failed_phrases}")

        return self

    def fix_icons(self):
        pass

class TitleOverlayType(str, Enum):
    LESSON_TITLE = "lesson_title"
    SECTION_TITLE = "section_title"

class TitleOverlay(BaseModel):
    text: str
    type: TitleOverlayType
    start_index: int
    end_index: int
    start_time: float
    end_time: float

class TextSlideElementType(str, Enum):
    TEXT = "text"
    IMAGE = "image"

class TextSlidePhrase(BaseModel):
    content: str
    phrase: str = ''
    start_index: int = 0
    start_time: float = 0
    start_duration: float = 0

class TextSlideElement(BaseModel):
    type: TextSlideElementType
    contents: List[TextSlidePhrase] = []
    
    def __init__(self, **data):
        if 'contents' not in data and 'start_time' in data:
            legacy_phrase = TextSlidePhrase(
                content=data.get('content'),
                phrase=data.pop('phrase', None) or '',
                start_index=data.pop('start_index', 0),
                start_time=data.pop('start_time', 0.0),
                start_duration=data.pop('start_duration', 1.0)
            )
            data['contents'] = [legacy_phrase]
        
        super().__init__(**data)
    
class TextSlide(BaseModel):
    title: str
    start_index: int
    end_index: int
    start_time: float
    end_time: float
    elements: List[TextSlideElement]
    src: str = ''
    visuals: Optional[List[DiagramVisual]] = None

    @validator('elements', pre=True, each_item=False)
    def sort_elements_by_start_time(cls, elements: Union[List[TextSlideElement], Dict]):
        if isinstance(elements[0], dict):
            elements = [TextSlideElement(**elem) for elem in elements]       
        return sorted(elements, key=lambda element: min(p.start_time for p in element.contents))
    
    def fill_visual_timings(self, transcript_timings: TranscriptTiming) -> List[str]:
        from core.media.clip_timings import match_segment_timings

        failed_phrases = []
        if not self.visuals:
            return failed_phrases

        for artifact in self.visuals:
            if not artifact.phrase:
                continue

            if isinstance(artifact.phrase, str):
                try:
                    start_index, end_index = match_segment_timings(transcript_timings, artifact.phrase)
                    artifact.start_time = transcript_timings.timings[start_index].start_time - self.start_time
                    artifact.end_time = transcript_timings.timings[end_index].end_time - self.start_time
                except:
                    failed_phrases.append(artifact.phrase)
            else:
                # Handle case where phrase is a list of strings
                try:
                    _, start_index = match_segment_timings(transcript_timings, artifact.phrase[0])
                    end_index, _ = match_segment_timings(transcript_timings, artifact.phrase[1])

                    artifact.start_time = transcript_timings.timings[start_index].start_time - self.start_time
                    artifact.end_time = transcript_timings.timings[end_index].end_time - self.start_time
                except:
                    failed_phrases.extend([artifact.phrase[0], artifact.phrase[1]])

        if failed_phrases:
            raise ValueError(f"Failed to match phrases for visual artifacts: {failed_phrases}")
        
        return failed_phrases

class Diagram(BaseModel):
    type: DiagramType
    data: Union[MindMap, TreeDiagram, VennDiagram, ConclusionSlideNew]
    start_index: int
    end_index: int
    start_time: float
    end_time: float
    src: str = ''

    @validator('data', pre=True)
    def validate_data_based_on_type(cls, data, values):
        if 'type' not in values:
            raise ValueError('type must be provided before data')
        
        diagram_type = values['type']
        
        if isinstance(data, BaseDiagram):
            return data
            
        if diagram_type == DiagramType.MIND_MAP or diagram_type == DiagramType.LESSON_ORGANIZER:
            return MindMap(**data)
        elif diagram_type == DiagramType.TREE:
            return TreeDiagram(**data)
        elif diagram_type == DiagramType.VENN_DIAGRAM:
            return VennDiagram(**data)
        elif diagram_type == DiagramType.CONCLUSION:
            return ConclusionSlideNew(**data)
        else:
            raise ValueError(f"Unsupported diagram type: {diagram_type}")
    


# =========================== AVATAR TYPES ===========================
class AvatarIntroduction(BaseModel):
    start_time: float
    end_time: float
    avatar_name: str 
    description: str
    src: str = ''

class Speaker(BaseModel):
    url: str
    prompt: str
    voice_id: Optional[str] = 'JBFqnCBsd6RMkjVDRZzb'  # Default voice ID for non-host speakers

class AvatarAsset(BaseModel):
    avatar_name: str
    timings: List[WordTiming]
    src: str
    start_time: float
    end_time: float
    image: Optional[str] = None
    prompt: Optional[str] = None
    avatar_clip: Optional[str] = None
    is_listening_avatar: Optional[bool] = False
    avatar_display_time: float = 0

class Feedback(BaseModel):
    feedback: str
    output: str


# =========================== TRANSCRIPT JSON TYPES ===========================
class TranscriptConcept(BaseModel):
    concept: str
    question: str
    explanation: str
    recap: str
    figure_name: str

class TranscriptSection(BaseModel):
    overview: str
    explanations: Dict[str, TranscriptConcept]
    conclusion: str

class TranscriptLesson(BaseModel):
    introduction: str
    sections: Dict[str, TranscriptSection]
    conclusion: str = ''
    conclusion_slide: Optional[ConclusionSlideNew] = None

class TranscriptOutput(BaseModel):
    lesson_transcript: str
    lesson_transcript_paused: str
    lesson_transcript_breakdown: TranscriptLesson

# =========================== RENDER ============================================================
class OverlaysData(BaseModel):
    title_overlays: List[TitleOverlay] = Field(default_factory=list)
    text_slides: List[TextSlide] = Field(default_factory=list)
    diagrams: List[Diagram] = Field(default_factory=list)
    conclusion_slide: Optional[Diagram] = Field(default=None)
    video_splits: Dict[str, float] = {}
