"""Per-subject values the lore prompts and image stages interpolate; add an entry here to onboard a subject."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


class LoreVoice(BaseModel):
    """The subject-specific clauses the lore narration prompts interpolate."""
    genre_noun: str
    figure_noun: str
    jargon_examples: str
    vague_examples: str
    comparison_anchors: str
    evidence_rule: str
    provenance_rule: str
    procedural_examples: str
    cold_open_guard: str
    close_guard: str
    entity_kinds: str


class ImageStyle(BaseModel):
    """The subject-specific values the image prompt and QC stages interpolate."""
    tuning_instructions: str
    qc_accuracy: str
    qc_instructions: str
    qc_must: str
    qc_conditions: List[str]
    detect_maps: bool = False

    def conditions(self, **runtime: str) -> List[str]:
        """QC conditions with their runtime slots filled."""
        return [condition.format(**runtime) for condition in self.qc_conditions]

    def prompt_values(self) -> Dict[str, str]:
        """The placeholders the image description and QC prompt templates expect."""
        return {"tuning_instructions": self.tuning_instructions, "accuracy": self.qc_accuracy,
                "instructions": self.qc_instructions, "must": self.qc_must}


class SubjectProfile(BaseModel):
    """Everything one subject needs to run through the pipeline."""
    id: str
    aliases: List[str]
    images: ImageStyle
    voice: LoreVoice


HISTORY = SubjectProfile(
    id="history",
    aliases=["history"],
    voice=LoreVoice(
        genre_noun="history",
        figure_noun="historical figures",
        jargon_examples="sextant, escapement, interdict",
        vague_examples='''"the ruler," "at this time," "a significant sum," "a major
   center."''',
        comparison_anchors="""a named city, a known voyage, a
   worker's yearly wage""",
        evidence_rule="Quote primary sources wherever available.",
        provenance_rule="""HOW WE KNOW, ONCE WHERE IT HELPS. If this concept names a source, spend at most one paragraph
    on who recorded the fact and whether they witnessed it. Do not manufacture a lesson from every
    silence, repeat that records are incomplete, or turn "we do not know" into a profound-sounding
    conclusion. Most segments need no archive paragraph at all.""",
        procedural_examples="how a ritual was performed, how a ship was loaded, how a law was enforced",
        cold_open_guard="never introduce a later-era traveller the material does not mention",
        close_guard="comparison, new region, thesis, or historical balancing",
        entity_kinds="""person, title, place, building, date, number, event, decision, cause, outcome, quotation,
social movement, or surviving/missing-record claim""",
    ),
    images=ImageStyle(
        tuning_instructions="- If the context includes years, timelines, or specific historical events, do not alter these key terms.\n- If possible, use the context of the time period and location to refine the description.",
        qc_accuracy="the time period and region",
        qc_instructions="Pay special attention to the accuracy of the time period and region in the images. As these images are for history textbooks, they must accurately represent the historical context.\n- Do not approve an image if it does not accurately represent the time period and region.",
        qc_must="the period or region involved to ensure geographic and temporal accuracy",
        qc_conditions=[
            "The image does not contain any elements that are anachronistic the time period, except for those specifically requested in the image prompt. The scene is set in the period - {period}, so all elements should be appropriate for that era unless more contemporary objects are specifically requested.",
            "The image does not contain any legible textual or numeric elements.",
            "The image content must be appropriate for the specified location. The image will be shown during a discussion about {location}, as part of the {subject} narration on '{title}'. Ensure all elements shown realistically match both the identified location and the relevant time period.",
            "If the image includes people, their appearance, clothing, hairstyles, and overall style should match their ethnicity and the time period ({period}).",
            "If people are the main subjects in the image and their faces are shown close-up (for example, a group sitting around a table), ensure each person's appearance while matching their ethnicity and the time period, also appears distinct. Faces should not look too similar; appropriate variation in age, beard style, hairstyle, and skin tone should be present.",
        ],
        detect_maps=True,
    ),
)

SCIENCE = SubjectProfile(
    id="science",
    aliases=["science", "physics"],
    voice=LoreVoice(
        genre_noun="science",
        figure_noun="the people who did the work",
        jargon_examples="isotope, polarizer, cryostat",
        vague_examples='''"the researchers," "at the time," "an experiment showed," "scientists
   believed."''',
        comparison_anchors="""a room the story has already described, an instrument already on
   the bench, a run whose length the listener has already heard""",
        evidence_rule="""Quote the paper, the notebook, the letter, or the recorded interview wherever one survives, and
   quote what it claimed at the time rather than what the field later concluded from it.""",
        provenance_rule="""HOW WE KNOW, NEVER A LESSON. Where this concept names an instrument, a reading, or a repeat of
    someone else's run, spend at most one paragraph on what the apparatus did and what it showed.
    Let the idea arrive through the hardware: give the apparatus, the reading, and what the people
    concluded from it, rather than teaching the theory in the abstract, and define no term the
    concept did not itself raise. But where a paper, a claim, or a result is one the segment keeps
    returning to, say in one plain sentence what it actually claimed, in the terms the people
    themselves used at the time. Naming a result repeatedly without ever saying what it was is the
    worse failure. Describe a belief later abandoned as what those people had good reason to hold at
    the time, never as an error seen from now. Most segments need no paragraph on method at all.""",
        procedural_examples="how an instrument was built, how a sample was prepared, how a reading was taken and repeated",
        cold_open_guard="never reach forward to a later discovery or a present-day application the material does not name",
        close_guard="later discovery, present-day application, new theory, thesis, or verdict on what the work meant",
        entity_kinds="""person, title, institution, place, instrument, material, date, number, measurement, experiment,
result, prediction, publication, quotation, decision, or contested/unreplicated claim""",
    ),
    images=ImageStyle(
        tuning_instructions="- If the context names an instrument, a material, a quantity, or a date, do not alter these key terms.\n- If possible, use the laboratory, workshop, or field setting the work was actually done in to refine the description.",
        qc_accuracy="the instruments and the working setting they belong to",
        qc_instructions="Pay special attention to the accuracy of the instruments and of the laboratory, workshop, or field setting. As these images accompany a narration about real experiments, the apparatus must look like equipment that was actually used for that work rather than generic modern laboratory imagery.\n- Do not approve an image showing equipment from a visibly later era than the work being described.",
        qc_must="the instruments, materials, and working setting involved to ensure the apparatus is plausible for the work described",
        qc_conditions=[
            "The image does not contain any legible textual or numeric elements, and no equations, formulae, axis labels, or chemical symbols.",
            "The image is a photographic scene rather than an illustration of an idea: no arrows, callouts, leader lines, orbit rings, particle trails, glowing energy effects, or schematic cutaways.",
            "The apparatus, tools, and furnishings are plausible for the work discussed in the {subject} narration on '{title}', and show nothing from a visibly later era — no digital displays, moulded plastic housings, or modern safety equipment — unless specifically requested in the image prompt.",
            "The image content must be appropriate for the setting it depicts. The image will be shown during a discussion about {location}, so the room, landscape, and building fabric should match that place.",
            "If the image includes people, their clothing, hairstyles, and grooming match the working setting and period, and any protective equipment shown is of the kind used in that setting rather than modern laboratory safety gear.",
        ],
    ),
)

PROFILES: Dict[str, SubjectProfile] = {profile.id: profile for profile in (HISTORY, SCIENCE)}


def resolve_profile(subject: str, explicit: Optional[str] = None) -> SubjectProfile:
    """Find a profile by explicit id or by alias in the subject name, refusing to guess."""
    known = ", ".join(sorted(PROFILES))
    if explicit:
        if explicit not in PROFILES:
            raise ValueError(f"unknown subject profile {explicit!r}; have: {known}")
        return PROFILES[explicit]
    lowered = subject.lower()
    if match := next((p for p in PROFILES.values() if any(a in lowered for a in p.aliases)), None):
        return match
    raise ValueError(f"no subject profile matches subject {subject!r}; have: {known}")
