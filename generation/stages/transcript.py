import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from config.subject_profiles import resolve_profile
from core.clients.lore import DEFAULT_CHOICE_MODEL, DEFAULT_MODEL, LoreClient
from core.clients.s3 import load_json_from_s3
from core.clients.speech import add_narration_pauses
from core.context import Context
from core.helpers import exception_handler
from core.log import with_logging_context
from core.lore_editorial import Source, generate_story, lesson_payload
from core.types import Concept, LayerName, TranscriptLesson, TranscriptOutput, VideoPlan

logger = logging.getLogger(__name__)


def format_concept(c: Concept) -> str:
    """One planned concept as a research note."""
    return f"Concept: {c.concept_name}.\nConcept Details:\n" + '\n'.join(c.facts)


def get_lore_transcript_string(lesson_transcript: TranscriptLesson) -> str:
    """The single-host script, one [Host] block per spoken passage."""
    blocks = [lesson_transcript.introduction]
    for section in lesson_transcript.sections.values():
        if section.overview:
            blocks.append(section.overview)
        for concept in section.explanations.values():
            if concept.question:
                blocks.append(concept.question)
            blocks.append(concept.explanation)
            if concept.recap:
                blocks.append(concept.recap)
    if lesson_transcript.conclusion:
        blocks.append(lesson_transcript.conclusion)
    return "\n\n".join(f"[Host]: {block}" for block in blocks if block)


def generate_lore_lesson_transcript(context: Context, video_plan: VideoPlan,
                                    narration_params: Dict[str, Any]) -> Dict[str, Any]:
    """Reference-led lore; the plan CLI and production stage share one narrative engine."""
    profile = resolve_profile(context.subject, narration_params.get("subject_profile"))
    sources = [Source(id=f"S{i + 1:03d}", context=section.simple_title or section.section_title,
                      text=format_concept(concept))
               for i, (section, concept) in enumerate((s, c) for s in video_plan.sections for c in s.concepts)]
    target_words = int(narration_params.get("target_words") or
                       narration_params.get("target_minutes", 35) * narration_params.get("words_per_minute", 135))
    trace_root = Path(narration_params.get("editorial_root") or
                      Path(__file__).resolve().parents[2] / "artifacts/lore_editorial")
    trace = trace_root / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid4().hex[:8])
    trace.mkdir(parents=True, exist_ok=False)
    client = LoreClient(narration_params.get("model", DEFAULT_MODEL),
                        narration_params.get("review_model"), narration_params.get("reasoning", "high"),
                        trace / "calls", narration_params.get("choice_model", DEFAULT_CHOICE_MODEL),
                        narration_params.get("choice_reasoning", "medium"))
    result = generate_story(client, profile.voice, video_plan.simple_title or video_plan.lesson_title,
                            context.subject, sources, target_words=target_words,
                            max_revisions=narration_params.get("max_revisions", 2),
                            approved_hook=narration_params.get("approved_hook"), artifact_dir=trace)
    (trace / "provenance.json").write_text(json.dumps(client.provenance(), indent=2), encoding="utf-8")
    if result.get("text"):
        (trace / "candidate.txt").write_text(result["text"], encoding="utf-8")
    if result["status"] != "candidate_model_review_passed":
        raise RuntimeError(f"Lore needs attention ({result['status']}); inspect {trace} before narration")
    lesson_transcript = TranscriptLesson.model_validate(lesson_payload(result))
    transcript_string = get_lore_transcript_string(lesson_transcript)
    return TranscriptOutput(
        lesson_transcript=transcript_string,
        lesson_transcript_paused=add_narration_pauses(transcript_string),
        lesson_transcript_breakdown=lesson_transcript,
    ).model_dump()


@with_logging_context(layer=LayerName.TRANSCRIPT)
@exception_handler
def generate_lesson_transcript(output_path: str, output_type: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Stage entry: the lore narration for one lesson's video plan."""
    context = Context(**inputs)
    video_plan = VideoPlan(**load_json_from_s3(context.video_plan_path)['video_plan'])
    return generate_lore_lesson_transcript(context, video_plan, inputs.get("NARRATION_PARAMS", {}))
