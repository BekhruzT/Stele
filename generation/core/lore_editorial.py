"""Shared story planning, hook selection, whole-draft writing, and editorial review."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from config.subject_profiles import LoreVoice
from core.hook_examples import format_hook_examples, youtube_hook_examples
from prompts.lore_hooks import HOOK_CHOICE_SYS, HOOK_GOAL
from prompts.lore_prompts import (DRAFT_SYS, HISTORY_GUIDANCE, HOOK_REPAIR_SYS, HOOK_SYS, JSON_CONTRACT_SUFFIX,
                                  LORE_LANG, PLAN_SYS, PROMPT_VERSION, PROMPTS, REFERENCE_EXAMPLE_ROLE, REPAIR_SYS,
                                  REVIEW_SYS, render)

logger = logging.getLogger(__name__)
Call = Callable[[str, str, str, int], str]
REFERENCE_DIR = Path(__file__).resolve().parents[1] / "docs/golden_references/2026-09-23"
CRITERIA = {"hook_scope", "hook_premise", "hook_restraint", "selection", "explanation", "continuity",
            "development", "listenability", "source_fidelity", "scientific_meaning", "ending"}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(Contract):
    id: str
    context: str
    text: str = Field(min_length=1)


class Movement(Contract):
    id: str
    title: str
    purpose: str
    source_ids: list[str] = Field(min_length=1)
    understanding: str
    transition: str


class Omission(Contract):
    source_id: str
    reason: str


class StoryPlan(Contract):
    central_question: str
    significance: str
    premise: str
    answer: str
    necessary_explanation: list[str]
    factual_boundaries: list[str]
    opening_source_ids: list[str] = Field(min_length=1)
    movements: list[Movement] = Field(min_length=1, max_length=12)
    sample_end_movement_id: str
    omissions: list[Omission]
    limitations: list[str]


class Hook(Contract):
    text: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    reason: str
    factual_risk: str


class Hooks(Contract):
    candidates: list[Hook] = Field(min_length=5, max_length=5)
    selected_index: int = Field(ge=0, le=4)
    selection_reason: str


class HookDrafts(Contract):
    candidates: list[str] = Field(min_length=5, max_length=5)


class HookChoiceCheck(Contract):
    usable: bool
    source_ids: list[str] = Field(min_length=1)
    reason: str

    @property
    def passed(self) -> bool:
        return self.usable


class HookChoice(Contract):
    candidate_checks: list[HookChoiceCheck] = Field(min_length=1, max_length=5)
    ranking: list[int] = Field(min_length=1, max_length=5)


def choose_hook_candidates(call: Call, title: str, subject: str, candidates: list[str],
                           research: list[dict], save: Callable, suffix: str = ''):
    """One editorial choice of the spoken alternatives and their factual support."""
    source_ids = {s['id'] for s in research}

    def validate(choice: HookChoice):
        if len(choice.candidate_checks) != len(candidates) or sorted(choice.ranking) != list(range(len(candidates))):
            raise ValueError('Check each candidate once and rank every zero-based index')
        if any(not set(check.source_ids) <= source_ids for check in choice.candidate_checks):
            raise ValueError('Hook choice must cite current research IDs')

    choice = json_call(call, HOOK_CHOICE_SYS,
        {'title': title, 'subject': subject, 'research': research, 'candidates': candidates},
        HookChoice, 'hook-choice', 5500, validate)
    save(f'hook-choice{suffix}.json', choice.model_dump())
    selected = next((i for i in choice.ranking if choice.candidate_checks[i].passed), None)
    hooks = [Hook(text=text, source_ids=check.source_ids, reason=check.reason,
                  factual_risk='' if check.usable else check.reason)
             for text, check in zip(candidates, choice.candidate_checks)]
    return hooks, choice, selected


class Passage(Contract):
    id: str
    text: str = Field(min_length=1)


class Narrative(Contract):
    opening: str = Field(min_length=1)
    sections: list[Passage]
    closing: str
    limitations: list[str]


class Criterion(Contract):
    verdict: Literal["pass", "needs_work", "not_applicable"]
    reason: str


class Issue(Contract):
    location: str
    quote: str = Field(min_length=1)
    severity: Literal["major", "minor"]
    problem: str
    repair: str


class Review(Contract):
    criteria: dict[str, Criterion]
    issues: list[Issue]
    required_revision: bool
    limitations: list[str]


def reference_examples(profile: str = "science") -> dict:
    """Load profile-specific, fixed excerpts and their hashes; never rewrite the goldens."""
    catalog = json.loads((REFERENCE_DIR / "style-reference-catalog.json").read_text(encoding="utf-8"))
    if profile not in catalog:
        raise ValueError(f"No style-reference set for {profile!r}")
    examples = {}
    for entry in catalog[profile]:
        name = entry["file"]
        path = REFERENCE_DIR / name
        text = path.read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        excerpts = paragraphs[entry.get("opening_skip_paragraphs", 0):entry["opening_paragraphs"]]
        for passage in entry.get("passages", []):
            first = next(i for i, p in enumerate(paragraphs) if p.startswith(passage["starts_with"]))
            excerpts += paragraphs[first:first + passage["paragraphs"]]
        if ending_count := entry.get("ending_paragraphs", 0):
            excerpts += paragraphs[-ending_count:]
        examples[name] = {"role": REFERENCE_EXAMPLE_ROLE,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "excerpts": excerpts}
    return examples


def approved_hook_for(title: str) -> dict | None:
    registry = json.loads((REFERENCE_DIR / "approved-hooks.json").read_text(encoding="utf-8"))
    return next((entry for entry in registry["topics"] if entry["title"] == title), None)


def json_call(call: Call, system: str, context: dict, schema: type[Contract], tag: str,
              max_tokens: int, validate: Callable | None = None):
    """Strict local contract; one explicit retry for malformed output, no silent prose salvage."""
    request = {**context, "output_schema": schema.model_json_schema()}
    system += JSON_CONTRACT_SUFFIX
    for attempt in range(2):
        raw = call(system, json.dumps(request, ensure_ascii=False), tag, max_tokens)
        try:
            result = schema.model_validate_json(raw)
            if validate:
                validate(result)
            return result
        except (ValueError, TypeError) as exc:
            if attempt:
                raise ValueError(f"{tag} failed its output contract after retry: {exc}") from exc
            request["contract_error_to_correct"] = str(exc)
            request["previous_response"] = raw
    raise AssertionError("unreachable")


def validate_plan(plan: StoryPlan, source_ids: set[str]) -> None:
    ids = [m.id for m in plan.movements]
    if len(set(ids)) != len(ids) or set(ids) & {"hook", "opening", "closing"}:
        raise ValueError("Movement IDs must be unique and not hook/opening/closing")
    if plan.sample_end_movement_id not in ids:
        raise ValueError("sample_end_movement_id must name a planned movement")
    selected = set(plan.opening_source_ids) | {s for m in plan.movements for s in m.source_ids}
    omitted = {o.source_id for o in plan.omissions}
    if selected & omitted or selected | omitted != source_ids:
        raise ValueError("Account for all valid source IDs, with no ID both selected and omitted")


def validate_hook(hook: Hook, source_ids: set[str]) -> None:
    if not set(hook.source_ids) <= source_ids or "\n" in hook.text.strip():
        raise ValueError("A hook needs valid source IDs and one paragraph")


def validate_narrative(narrative: Narrative, movements: list[Movement], scope: str, hook: str) -> None:
    if [s.id for s in narrative.sections] != [m.id for m in movements]:
        raise ValueError("Return each requested movement exactly once and in order")
    if hook.strip() in narrative.opening:
        raise ValueError("Do not repeat the separately inserted hook in opening")
    if scope == "opening" and narrative.closing.strip():
        raise ValueError("An opening sample must have an empty closing")
    if scope == "full" and not narrative.closing.rstrip().endswith("Good night."):
        raise ValueError("A full narrative must include a closing ending in Good night.")


def validate_review(review: Review, narrative: Narrative, hook: str, scope: str) -> None:
    if set(review.criteria) != CRITERIA:
        raise ValueError("Review every requested criterion, using the exact criterion keys")
    locations = {"hook": hook, "opening": narrative.opening, "closing": narrative.closing,
                 **{s.id: s.text for s in narrative.sections}}
    for issue in review.issues:
        if issue.location not in locations or issue.quote not in locations[issue.location]:
            raise ValueError("Review quotes must occur verbatim in their named location")
    required = any(c.verdict == "needs_work" for c in review.criteria.values()) or any(
        i.severity == "major" for i in review.issues)
    if required != review.required_revision:
        raise ValueError("required_revision must agree with criterion verdicts and major issues")
    if scope == "opening" and review.criteria["ending"].verdict != "not_applicable":
        raise ValueError("An opening sample's ending must be not_applicable")


def transcript_text(hook: str, narrative: Narrative) -> str:
    return "\n\n".join(p.strip() for p in [hook, narrative.opening,
        *(s.text for s in narrative.sections), narrative.closing] if p.strip()) + "\n"


def lesson_payload(result: dict) -> dict:
    """Keep the existing TranscriptLesson contract while preserving editorial movement order.

    Lore disables lesson-organizer slides, so movements may regroup research concepts.
    """
    narrative = Narrative.model_validate(result["narrative"])
    movements = {m["id"]: m for m in result["plan"]["movements"]}
    return {"introduction": result["hook"] + "\n\n" + narrative.opening,
            "sections": {p.id: {"overview": "", "conclusion": "", "explanations": {
                movements[p.id]["title"]: {"concept": movements[p.id]["purpose"], "question": "",
                    "explanation": p.text, "recap": "", "figure_name": "Host"}}}
                for p in narrative.sections}, "conclusion": narrative.closing}


def generate_story(call: Call, voice: LoreVoice, title: str, subject: str, sources: list[Source],
                   target_words: int = 4600, scope: Literal["full", "opening", "hooks"] = "full",
                   max_revisions: int = 2, approved_hook: str | None = None,
                   artifact_dir: Path | None = None, fresh_hook: bool = False) -> dict:
    if not sources or len({s.id for s in sources}) != len(sources):
        raise ValueError("Provide nonempty research with unique source IDs")
    if target_words < 200 or target_words > 20000 or max_revisions not in range(4):
        raise ValueError("Use a 200–20000 word budget and 0–3 revision rounds")
    if scope not in {"full", "opening", "hooks"}:
        raise ValueError("Unknown narrative scope")
    if approved_hook and "\n" in approved_hook.strip():
        raise ValueError("approved_hook must contain one opening paragraph, not a full transcript")
    registered = approved_hook_for(title)
    if not approved_hook and registered and not fresh_hook and scope != "hooks":
        approved_hook = registered["text"]
    source_ids = {s.id for s in sources}
    examples = reference_examples(voice.genre_noun)
    domain_guidance = HISTORY_GUIDANCE if voice.genre_noun == "history" else ""
    context = {"title": title, "subject": subject, "research": [s.model_dump() for s in sources],
               "style_references": examples,
               "domain_guidance": domain_guidance,
               "hook_guidance": HOOK_GOAL,
               "hook_intent": registered["meaning"] if registered and approved_hook == registered["text"] else None,
               "approved_hook": approved_hook,
               "target_words": max(4600, target_words) if scope == "opening" else target_words,
               "requested_sample_words": target_words if scope == "opening" else None}
    snapshots = {name: render(value, voice) for name, value in PROMPTS.items()}
    voice_text = render(LORE_LANG, voice)
    if domain_guidance:
        voice_text += "\n" + domain_guidance

    def save(name, value):
        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    save("inputs.json", context)
    save("prompts.json", {"version": PROMPT_VERSION, "templates": snapshots})
    # Prose examples and history narration cautions must not become hook templates.
    hook_context = {k: context[k] for k in ('title', 'subject', 'research', 'approved_hook')}
    corpus = youtube_hook_examples()
    hook_system = HOOK_SYS.format(reference_hooks=format_hook_examples(corpus))
    save('youtube-hook-examples.json', corpus)
    result = {"prompt_version": PROMPT_VERSION, "scope": scope, "hook_brief": None,
              "hook_corpus": {k: corpus[k] for k in ('version', 'count', 'sha256')},
              "plan": None, "hooks": None, "hook": approved_hook or "", "hook_locked": bool(approved_hook),
              "hook_selection": None, "reviews": [], "text": ""}
    logger.info("[five hooks] %s", title)

    def hooks_valid(h):
        if len({c.text.strip().lower() for c in h.candidates}) != 5:
            raise ValueError("Provide five distinct hook candidates")
        for candidate in h.candidates:
            validate_hook(candidate, source_ids)

    def drafts_valid(h):
        if len({c.strip().casefold() for c in h.candidates}) != 5:
            raise ValueError('Provide five distinct spoken openings')
        if any(not c.strip() or '\n' in c.strip() for c in h.candidates):
            raise ValueError('Each opening must be one nonempty paragraph')

    selection = None
    if approved_hook:
        hooks = json_call(call, hook_system, hook_context, Hooks, "hooks", 7000, hooks_valid)
        save("hook-candidates-0.json", hooks.model_dump())
        hook = approved_hook.strip()
    else:
        drafts = json_call(call, hook_system, hook_context, HookDrafts, "hooks", 7000, drafts_valid)
        save("hook-drafts-0.json", drafts.model_dump())
        candidates, choice, selected = choose_hook_candidates(call, title, subject, drafts.candidates,
            context['research'], save, '-0')
        diagnostic_index = selected if selected is not None else choice.ranking[0]
        reason = choice.candidate_checks[diagnostic_index].reason
        hooks = Hooks(candidates=candidates, selected_index=diagnostic_index, selection_reason=reason)
        save("hook-candidates-0.json", hooks.model_dump())
        selection = {**choice.model_dump(), "selected_index": selected,
                     "candidate_reasons": [c.reason for c in choice.candidate_checks],
                     "regenerate": selected is None, "reason": reason}
        save("hook-selection-0.json", selection)
        hook = drafts.candidates[selected].strip() if selected is not None else ""
    save("hooks.json", {**hooks.model_dump(), "active_hook": hook, "locked_by_user": bool(approved_hook)})
    result.update(hooks=hooks.model_dump(), hook=hook,
                  hook_selection=selection)
    if selection and selection["regenerate"]:
        result["status"] = "needs_hook_revision"
        save("result.json", result)
        return result
    if scope == "hooks":
        result["status"] = "hook_locked_by_user" if approved_hook else "hook_selection_passed"
        save("result.json", result)
        return result
    context["selected_hook"] = hook
    logger.info("[editorial plan] %s", title)
    plan = json_call(call, PLAN_SYS, context, StoryPlan, "plan", 10000,
                     lambda p: validate_plan(p, source_ids))
    context["editorial_plan"] = plan.model_dump()
    result["plan"] = plan.model_dump()
    save("editorial-plan.json", plan.model_dump())
    sample_end = next(i for i, m in enumerate(plan.movements) if m.id == plan.sample_end_movement_id) + 1
    movements = plan.movements if scope == "full" else plan.movements[:sample_end]
    context.update(scope="COMPLETE" if scope == "full" else "OPENING SAMPLE", selected_hook=hook,
                   target_words=target_words,
                   requested_movements=[m.model_dump() for m in movements])
    cap = min(60000, max(6500, target_words * 3 + 4000))
    logger.info("[whole draft] %s (%s, target ~%s words)", title, scope, target_words)
    narrative = json_call(call, DRAFT_SYS.format(voice=voice_text), context, Narrative, "draft", cap,
                          lambda n: validate_narrative(n, movements, scope, hook))
    save("draft-0.json", narrative.model_dump())
    repair_check = None
    for round_index in range(max_revisions + 1):
        logger.info("[whole review %s] %s", round_index + 1, title)
        review = json_call(call, REVIEW_SYS, {**context, "selected_hook": hook,
            "assembled_transcript": transcript_text(hook, narrative),
            "narrative": narrative.model_dump()}, Review, "review", 10000,
            lambda r: validate_review(r, narrative, hook, scope))
        result["reviews"].append(review.model_dump())
        save(f"review-{round_index}.json", review.model_dump())
        if not review.required_revision or round_index == max_revisions:
            break
        hook_issues = [i for i in review.issues if i.location == "hook"]
        if hook_issues and not approved_hook:
            fixed = json_call(call, HOOK_REPAIR_SYS, {**context, "selected_hook": hook,
                "youtube_hook_examples": corpus,
                "issues": [i.model_dump() for i in hook_issues]}, Hook, "hook-repair", 5000,
                lambda h: validate_hook(h, source_ids))
            hook = fixed.text.strip()
            _, repaired_choice, _ = choose_hook_candidates(call, title, subject, [fixed.text],
                context['research'], save, f'-repair-{round_index}')
            repair_check = repaired_choice.candidate_checks[0]
            save(f"hook-repair-check-{round_index}.json", repair_check.model_dump())
            result["hook_repair_check"] = repair_check.model_dump()
        context["selected_hook"] = hook
        logger.info("[whole revision %s] %s", round_index + 1, title)
        narrative = json_call(call, REPAIR_SYS.format(voice=voice_text), {**context,
            "narrative": narrative.model_dump(), "assembled_transcript": transcript_text(hook, narrative),
            "review": review.model_dump()}, Narrative,
            "repair", cap, lambda n: validate_narrative(n, movements, scope, hook))
        save(f"draft-{round_index + 1}.json", narrative.model_dump())
    unresolved_hook = repair_check is not None and not repair_check.passed
    result.update(hook=hook, narrative=narrative.model_dump(), text=transcript_text(hook, narrative),
                  status="needs_editorial_review" if review.required_revision or unresolved_hook else "candidate_model_review_passed")
    # Final review covers the actual returned revision. No return of an unchecked repair.
    save("result.json", {k: v for k, v in result.items() if k != "text"})
    return result
