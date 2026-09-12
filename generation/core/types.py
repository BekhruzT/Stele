import logging
import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from core.helpers import (
    generate_img_prompt, generate_video_prompt, print_json, fix_single_icon)
from core.stage_constants import \
    VALID_FA_ICONS
from core.clients.images import GeneratedImageTypes
from fuzzywuzzy import fuzz
from pydantic import BaseModel, Field, model_validator, validator
from core.context import APVideoContext as Context
from core.hash import hash_image_description
from core.clients.s3 import does_file_exist, load_json_from_s3

logger = logging.getLogger(__name__)

class LayerName(str, Enum):
    INPUTS = "inputs"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    PLANNER = "planner"
    TRANSCRIPT = "transcript"
    AVATAR = "avatar"
    OVERLAYS = "overlays"
    CLIPS = "clips"
    IMAGES = "images"
    VIDEOS = "videos"
    SHOTSTACK = "shotstack"


class KGEdge(BaseModel):
    """Represents a relationship between two nodes in the knowledge graph."""
    type: str
    explanation: str
    strength: float
    direction: str
    source_id: str
    target_id: str
    source_statement: str
    target_statement: str

class KGNode(BaseModel):
    """Represents a node containing a fact in the knowledge graph."""
    id: str
    fact_text: str
    is_definition: Optional[bool]
    theme: Optional[str]
    classification: Optional[str]

class LessonKnowledgeGraph(BaseModel):
    """Knowledge graph representation for a lesson."""
    lo_nodes: List[KGNode]
    lo_edges: List[KGEdge]
    iu_edges: Optional[List[KGEdge]] = None
    xu_facts: Optional[List[KGNode]] = None
    graph_repr: str = ""

    def format_lo_nodes(self) -> dict:
        """Format LO nodes into facts and l3_facts."""
        facts = []
        l3_facts = []
        
        for node in self.lo_nodes:
            if node.id.strip().startswith("KC"):
                l3_facts.append(f'{node.id}["{node.fact_text}"]')
            else:
                node_fact = f'{node.id}["{node.fact_text}"]'
                if node.is_definition is not None:
                    node_fact += f"\n\tis_definition: {str(node.is_definition).upper()}"
                if node.theme:
                    node_fact += f"\n\ttheme: {node.theme}"
                if node.classification:
                    node_fact += f"\n\tclassification: {node.classification}"
                facts.append(node_fact)
            
        return "\n\n".join(facts), "\n\n".join(l3_facts)

    def format_xu_facts(self) -> List[str]:
        """Format XU facts."""
        if not self.xu_facts:
            return []
            
        facts = []
        for node in self.xu_facts:
            facts.append(f'{node.id}["{node.fact_text}"]')
            if node.is_definition is not None:
                facts[-1] += f"\n\tis_definition: {str(node.is_definition).upper()}"
            if node.theme:
                facts[-1] += f"\n\ttheme: {node.theme}"
            facts[-1] += f"\n\tclassification: Supporting"
            facts.append("")
        return "\n".join(facts)

    def format_relationships(self) -> List[str]:
        """Format relationships from edges."""
        nodes_lookup = {node.id: node for node in self.lo_nodes}
        if self.xu_facts:
            nodes_lookup.update({node.id: node for node in self.xu_facts})

        relationships = []
        for edge in self.lo_edges:
            if edge.source_id in nodes_lookup and edge.target_id in nodes_lookup:
                direction_based_arrow = "-->" if edge.direction == "uni" else "<-->"
                relationships_edge = f'{edge.source_id} {direction_based_arrow}|"{edge.type} : {edge.explanation}"| {edge.target_id}'
                relationships.append(relationships_edge)
        return "\n".join(relationships)
  
    def format_iu_relationships(self) -> str:
        nodes_lookup = {node.id: node for node in self.lo_nodes}
        if self.xu_facts:
            nodes_lookup.update({node.id: node for node in self.xu_facts})

        relationships = []
        if self.iu_edges:
            for edge in self.iu_edges:
                direction_based_arrow = "-->" if edge.direction == "uni" else "<-->"
                relationship = f'{edge.source_id if edge.source_id in nodes_lookup else edge.source_statement} {direction_based_arrow}|"{edge.type} : {edge.explanation}"| {edge.target_id if edge.target_id in nodes_lookup else edge.target_statement}'
                relationships.append(relationship)

        return "\n".join(relationships)

    def format_kg(self) -> str:
        """Convert nodes and edges into facts format."""
        # Combine all formatted sections
        facts, l3_facts = self.format_lo_nodes()
        xu_facts = self.format_xu_facts()
        relationships = self.format_relationships()       
        iu_relationships = self.format_iu_relationships()        

        return f"FACTS:\n{facts}\n\nL3 Facts:\n{l3_facts}\n\nCROSS UNIT Facts:\n{xu_facts}\n\nRELATIONSHIPS:\n{relationships}\n\nPREVIOUS LESSON RELATIONSHIPS:\n{iu_relationships}"

    @model_validator(mode='after')
    def compute_graph_repr(self):
        """Compute the string representation of the knowledge graph."""
        self.graph_repr = self.format_kg()
        return self

    def find_fact(self, input_fact: str, similarity_threshold: int = 90) -> Optional[KGNode]:
        input_fact = input_fact.replace('(HIGH LEVEL)', '')

        if not self.lo_nodes:
            return None
        most_similar_node, max_fuzz_ratio = None, 0
        for node in self.lo_nodes + (self.xu_facts or []):
            fuzz_ratio = fuzz.ratio(node.fact_text, input_fact)
            if fuzz_ratio > max_fuzz_ratio:
                most_similar_node, max_fuzz_ratio = node, fuzz_ratio

        if max_fuzz_ratio >= similarity_threshold:
            return most_similar_node
        logger.error(f"Fact found with a fuzz ratio {max_fuzz_ratio} (less than the threshold {similarity_threshold})"
                        f"\n\tInput fact: {input_fact}"
                        f"\n\tClosest fact found: {most_similar_node.fact_text}")
        return None

    def find_xu_fact(self, input_fact: str, similarity_threshold: int = 90) -> Optional[KGNode]:
        input_fact = input_fact.replace('(HIGH LEVEL)', '')
        if not self.xu_facts:
            return None
        most_similar_node, max_fuzz_ratio = None, 0
        for node in self.xu_facts:
            fuzz_ratio = fuzz.ratio(node.fact_text, input_fact)
            if fuzz_ratio > max_fuzz_ratio:
                most_similar_node, max_fuzz_ratio = node, fuzz_ratio

        if max_fuzz_ratio >= similarity_threshold:
            return most_similar_node
        # logger.error(f"Fact found with a fuzz ratio {max_fuzz_ratio} (less than the threshold {similarity_threshold})"
        #                 f"\n\tInput fact: {input_fact}"
        #                 f"\n\tClosest fact found: {most_similar_node.fact_text}")
        return None
            
    def find_iu_relationships_per_fact(self, fact: str, similarity_threshold: int = 90) -> Optional[KGEdge]:
        fact = fact.replace('(HIGH LEVEL)', '')
        
        if not self.iu_edges:
            return None
        most_similar_edge, max_fuzz_ratio = None, 0
        for edge in self.iu_edges:
            fuzz_ratio = max(fuzz.ratio(edge.source_statement, fact), fuzz.ratio(edge.target_statement, fact))
            if fuzz_ratio > max_fuzz_ratio:
                most_similar_edge, max_fuzz_ratio = edge, fuzz_ratio

        if max_fuzz_ratio >= similarity_threshold:
            return most_similar_edge
        logger.error(f"Fact found with a fuzz ratio {max_fuzz_ratio} (less than the threshold {similarity_threshold})"
                        f"\n\tInput fact: {fact}"
                        f"\n\tClosest edge found: ({most_similar_edge.source_statement}) -> ({most_similar_edge.target_statement})")
        return None

    def correct_kg_facts(self, plan: dict) -> Tuple[dict, List[str]]:
        missing_facts = []
        for node in self.lo_nodes + (self.xu_facts or []):

            score, kg_fact, ii, jj, kk = max(
                (fuzz.ratio(node.fact_text, fact), node.fact_text, ii, jj, kk) 
                for ii, section in enumerate(plan['sections'])
                for jj, concept in enumerate(section['concepts'])
                for kk, fact in enumerate(concept['facts'])
            )

            if score < 90:
                missing_facts.append(kg_fact)
            else:
                kg_fact = kg_fact + ' (HIGH LEVEL)' if '(HIGH LEVEL)' in plan['sections'][ii]['concepts'][jj]['facts'][kk] else kg_fact
                plan['sections'][ii]['concepts'][jj]['facts'][kk] = kg_fact 
        return plan, missing_facts

    def find_redundant_facts(self, plan: dict):
        redundant_facts = []

        facts =  [fact
                    for section in plan['sections']
                    for concept in section['concepts']
                    for fact in concept['facts']
                ]
        for fact in facts:

            score, redundant_fact = max(
                (fuzz.ratio(node.fact_text, fact.replace('(HIGH LEVEL)', '')), fact) 
                for node in self.lo_nodes + (self.xu_facts or [])
            )

            if score < 95:
                redundant_facts.append(redundant_fact)
        return redundant_facts
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

class FactRelationshipType(str, Enum):
    CAUSES = "causes"
    DETAILS = "details"
    ENABLES = "enables"
    INFLUENCES = "influences"
    EXEMPLIFIES = "exemplifies"
    COMPARES = "compares"

class TeachingTechnique(str, Enum):
    SAMENESS_AND_DIFFERENCE = "Sameness and Difference Principle"
    SETUP_PRINCIPLE = "Setup Principle"
    CONTEXTUALIZATION = "Contextualization Technique"
    STORYTELLING = "Storytelling Technique"
    SIMPLE_EXPLANATION = "Simple Explanation"

class ArtifactImage(BaseModel):
    src: str
    name: str
    fact: str
    phrase: Union[str, Tuple[str, str]] = ''

class Visual(BaseModel):
    type: VisualType
    diagram_type: Optional[Union[Literal[""], DiagramType]] = None
    justification: str

class TeachingTechniqueInfo(BaseModel):
    choice: TeachingTechnique
    suggestion: str

class FactRelationship(BaseModel):
    type: FactRelationshipType
    description: str

class Concept(BaseModel):
    concept_name: str
    concept: str
    facts: List[str]
    cross_unit_facts: Optional[List[str]] = None
    visual: Optional[Visual] = None
    teaching_techniques: List[TeachingTechniqueInfo] = []
    artifact_images: Optional[Dict[str, ArtifactImage]] = None
    figure_name: Optional[str] = None
    includes_question: bool = True

    @model_validator(mode='after')
    def remove_pattern_in_facts(self):
        pattern = re.compile(r'[A-Za-z]_[A-Za-z0-9]+')
        self.facts = [pattern.sub('', fact) for fact in self.facts]
        return self

class ConceptJustifications(BaseModel):
    for_grouping: str
    for_ordering: str

class Section(BaseModel):
    section_title: str
    simple_title: str = ''
    concepts: List[Concept]
    concept_justifications: ConceptJustifications
    historical_figures: List[str] = []

class SectionJustifications(BaseModel):
    for_grouping: str
    for_ordering: str

class FactRelationshipPair(BaseModel):
    source_fact: str
    target_fact: str
    relationship: FactRelationship

class VideoPlan(BaseModel):
    lesson_title: str
    simple_title: str = ''
    sections: List[Section]
    section_justifications: SectionJustifications
    included_map: str = ''
    fact_relationships: List[FactRelationshipPair]
    intra_unit_relationships: List[FactRelationshipPair]

    def update_artifact_image(self, artifact: ArtifactImage) -> bool:
        for section in self.sections:
            for concept in section.concepts:
                if concept.artifact_images and artifact.name in concept.artifact_images:
                    concept.artifact_images[artifact.name] = artifact
                    return True
                    
        logger.error(f"Could not find artifact with name {artifact.name} in any concept's artifact_images")
        return False

    def get_current_concept_relationships(self, concept: Concept, similarity_threshold: int = 85) -> List[FactRelationshipPair]:
        """Get all fact relationships where both source and target facts belong to the given concept.
        Uses fuzzy string matching to match facts.
        
        Args:
            concept: The concept to find relationships for
            similarity_threshold: Minimum fuzzy match ratio to consider facts as matching (default: 85)
            
        Returns:
            List of FactRelationshipPair objects where both facts are in the concept
        """
        concept_relationships = []
        
        for relationship in self.fact_relationships:
            # Check if both source and target facts are in this concept's facts
            source_matches = any(fuzz.ratio(relationship.source_fact, fact) >= similarity_threshold 
                               for fact in concept.facts)
            target_matches = any(fuzz.ratio(relationship.target_fact, fact) >= similarity_threshold 
                               for fact in concept.facts)
            
            if source_matches and target_matches:
                concept_relationships.append(relationship)
                
        return concept_relationships

    def get_fact_location(self, fact: str, similarity_threshold: int=90) -> Tuple[int, int]:
        for s_idx, section in enumerate(self.sections):
            for c_idx, c in enumerate(section.concepts):
                if any(fuzz.ratio(c_fact, fact) >= similarity_threshold 
                            for c_fact in c.facts):
                    return s_idx, c_idx
        return -1, -1
        
    def process_prior_relationships(self, relationships: List[FactRelationshipPair], concept: Concept, similarity_threshold: int = 90) -> List[FactRelationshipPair]:

        filtered_relationships = []
        if not relationships:
            return filtered_relationships
        for relationship in relationships:
            # Check if source or target fact matches with any fact in the concept
            source_in_concept = any(fuzz.ratio(relationship.source_fact, fact) >= similarity_threshold 
                                for fact in concept.facts)
            target_in_concept = any(fuzz.ratio(relationship.target_fact, fact) >= similarity_threshold 
                                for fact in concept.facts)
            
            # Include relationship if exactly one fact matches
            if source_in_concept != target_in_concept:  # XOR - one true, one false
                mapped_fact = relationship.source_fact if target_in_concept else relationship.target_fact
                
                mapped_fact_location = self.get_fact_location(mapped_fact)
                current_concept_location = self.get_fact_location(concept.facts[0])
                if current_concept_location[0] > mapped_fact_location[0] or (current_concept_location[0] == mapped_fact_location[0] and current_concept_location[1] > mapped_fact_location[1]):
                    filtered_relationships.append(relationship)

        return filtered_relationships
    
    def get_prior_relationships(self, concept: Concept, similarity_threshold: int = 85) -> Tuple[List[FactRelationshipPair], List[FactRelationshipPair]]:  
        """Get fact relationships where exactly one fact (either source or target) matches with the concept's facts.
        Uses fuzzy string matching to match facts.
        
        Args:
            concept: The concept to find relationships for
            similarity_threshold: Minimum fuzzy match ratio to consider facts as matching (default: 85)   
            
        Returns:
            List of FactRelationshipPair objects where exactly one fact matches with the concept's facts
        """
        filtered_lesson_relationships = self.process_prior_relationships(self.fact_relationships, concept, similarity_threshold)
        filtered_intra_unit_relationships = self.process_prior_relationships(self.intra_unit_relationships, concept, similarity_threshold)
        
                
        return filtered_lesson_relationships, filtered_intra_unit_relationships

    def fill_lesson_artifacts(self, context: Context):
        from core.media.media_assets import get_lesson_artifacts

        lesson_artifacts = get_lesson_artifacts(context) # returns List[ArtifactImage]
        for artifact in lesson_artifacts:
            best_match_score = 0
            best_match_concept = None
            best_match_fact = None

            artifact_is_present = False
            for section in self.sections:
                for concept in section.concepts:
                    if concept.artifact_images and artifact.name in concept.artifact_images:
                        artifact_is_present = True
                    for fact in concept.facts:
                        match_score = fuzz.ratio(artifact.fact, fact)
                        if match_score > best_match_score:
                            best_match_score = match_score
                            best_match_concept = concept
                            best_match_fact = fact

            if artifact_is_present:
                print(f"Artifact {artifact.name} is already in Video Plan")

            if best_match_score < 85:
                print(f"Couldn't find a good match, highest score {best_match_score}:\nInput fact: {artifact.fact}.\nClosest fact: {fact}")

            if best_match_concept.artifact_images is None:
                best_match_concept.artifact_images = {}

            # print(f"Artifact {artifact.name} found")

            artifact.fact = best_match_fact
            best_match_concept.artifact_images[artifact.name] = artifact

        return self
# =========================== IMAGES AND VIDEOS TYPES ===========================
class SheetImage(BaseModel):
    url: str
    description: str

class SheetImages(BaseModel):
    images: List[SheetImage]
    
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

# =========================== SHOTSTACK TYPES ===========================
class ClipTypes(Enum):
    VIDEO='VIDEO'
    IMAGE='IMAGE'

class AvatarClip(BaseModel):
    start_time: float
    end_time: float
    speaker: str 
    src: str = ""

class AudioClip(BaseModel):
    start_time: float
    end_time: float
    speaker: str 
    src: str

class ImageClip(BaseModel):
    src: str
    description: str

class VideoClip(BaseModel):
    image_src: Optional[str]
    src: str
    description: str
    duration: float

class MediaClip(BaseModel):
    type: ClipTypes
    start_time: float
    end_time: float
    transcript_snippet: str 
    contents: Union[ImageClip, VideoClip]

    class Config:
        use_enum_values = True


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
    
class ConclusionBulletPoint(BaseModel):
    title: str
    title_start_time: float
    title_start_index: int
    text: str 
    start_time: float # Relative to slide start
    start_index: int

class ConclusionSlide(BaseModel):
    title: str
    start_time: float = 0
    end_time: float = 0
    start_index: int
    end_index: int
    bullet_points: List[ConclusionBulletPoint]
    background_src: str = 'static/ap_videos_background_1.png'
    src: str = ''


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
class MCQOption(BaseModel):
    id: str
    answer: str
    correct: bool
    explanation: str

class MCQ(BaseModel):
    question: str
    answer_options: List[MCQOption]
    background_image: Optional[Dict[str, str]] = None
    learning_content: Optional[Dict] = None
    speaker: Optional[Dict] = None
    transcript: str

class TranscriptSupplements(BaseModel):
    questions: Dict[str, Dict[str, List[MCQ]]]

class ConclusionParts(BaseModel):
    re_introduction: str 
    brief_summary: str
    listing_key_concepts: str
    recap: List[str]
    post_recap: str

class GenerateTranscriptOutput(BaseModel):
    introduction: str
    introduction_qc_iterations: List[Feedback]
    main_part: str
    main_part_qc_iterations: List[Feedback]
    conclusion: str
    conclusion_qc_iterations: List[Feedback]
    conclusion_parts: ConclusionParts
    conclusion_bullet_points: Dict


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
    supplementary_content: Optional[TranscriptSupplements] = None

# =========================== SHOTSTACK =========================================================
class QuestionOverlay(BaseModel):
    time: float
    questions: List[MCQ]

class OverlaysData(BaseModel):
    title_overlays: List[TitleOverlay] = Field(default_factory=list)
    text_slides: List[TextSlide] = Field(default_factory=list)
    diagrams: List[Diagram] = Field(default_factory=list)
    conclusion_slide: Optional[Diagram] = Field(default=None)
    video_splits: Dict[str, float] = {}
    questions: Dict[str, Dict[str, QuestionOverlay]] = {}
    
class LessonVideo(BaseModel):
    context: Context
    clips: List[MediaClip]
    audio: List[AudioClip]
    avatar: List[AvatarClip]
    avatar_intros: List[AvatarIntroduction]
    overlay_assets: OverlaysData
# =========================== LESSONG METADATA AND CONTEXT PACK TYPES ===========================
class LessonContextPack(BaseModel):
    transcript_pack: str = Field(default="Please ensure to use grade appropriate and unbiased content")

    @classmethod
    def from_context(cls, context: Context) -> 'LessonContextPack':
        if does_file_exist(context.context_pack_path):
            json_data = load_json_from_s3(context.context_pack_path)
            transcript_pack = json_data.get('transcript_pack', cls().transcript_pack)
            return cls(transcript_pack=transcript_pack)
        return cls()

class KeyConcept(BaseModel):
    title: str
    learning_objectives: List[str]
    key_phrases: List[str] = Field(default_factory=list)

class QCStatus(str, Enum):
    AWAITING_REVIEW = "Awaiting Review"
    PASSED = "Passed"
    FAILED = "Failed"

class LessonMetadata(BaseModel):
    qc_status: QCStatus = QCStatus.AWAITING_REVIEW
    lesson_title: str
    boundaries_and_purpose: str = "Not provided"
    perspective_guidance: str = "Not provided"
    key_concepts: List[KeyConcept]

class LessonMetadataWithContext(BaseModel):
    context: Context
    metadata: LessonMetadata



if __name__ == '__main__':
    from core.context import prep_content_gen_input
    context = prep_content_gen_input({
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons",
            "grade": "Grade 11",
            "subject": "AP World History",
            "category": "High School: AP World History: Modern"
        },
        "Input": {
            "unit": "1200 CE - 1450 CE",
            "chapter": "Networks of Exchange",
            "section": "Effects of Expanding Trade Networks",
            "subsection": "Political Effects"
        }
    })
    context = Context(**context)
    lesson_video(context)

