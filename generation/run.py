#!/usr/bin/env python3
"""Generate AP video lessons from a course's lesson plan, one stage at a time.

The whole orchestrator: stage order, dispatch, skip, retry, lesson selection and the
worker pool. A stage knows nothing about any of it -- it is handed a dict and returns a
dict, and this module decides everything else.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from concurrent.futures import as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

# Load the environment before any core import, because core/constants.py reads os.getenv at
# module scope and would otherwise bake in None for every key. Without it there is no
# bucket and no credentials.
for _env in (Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"):
    if _env.is_file():
        load_dotenv(_env)
        break

# --storage has to reach the environment before the first core import too, because
# core/clients/s3.py chooses its backend at module scope. The real parser in build_parser()
# runs inside main(), long after that decision, so the flag is read twice: here to set the
# variable, and there so it appears in --help and is not rejected as unknown.
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--storage", choices=("s3", "local"))
_preselected = _pre.parse_known_args()[0].storage
if _preselected:
    os.environ["STORAGE"] = _preselected
STORAGE = os.getenv("STORAGE", "s3").strip().lower()

from config.courses import get_execution_input  # noqa: E402
from core.clients.s3 import (check_folder_exists, copy_s3_folder,  # noqa: E402
                             does_file_exist, load_json_from_s3, save_json_to_s3)
from core.context import Context  # noqa: E402
from core.log import (ContextAwareThreadPoolExecutor, setup_logging,  # noqa: E402
                      with_logging_context)
from core.notification_system import NotificationSystem  # noqa: E402
from core.path import get_content_path, get_lesson_plan_path  # noqa: E402
from stages import (avatar_clips, image_clips, knowledge_graph,  # noqa: E402
                    local_render, scenes_breakdown, text_overlays,
                    transcript, video_clips, video_plan)

logger = logging.getLogger(__name__)

CONFIG = Path(__file__).parent / "config" / "stages.json"
VIDEO_TYPES = Path(__file__).parent / "config" / "video_types.json"

# Each layer is a piece of a stage rather than a stage, so none is a config/stages.json entry.
LAYER_DEFAULTS: Dict[str, bool] = {
    # Off keeps the ElevenLabs audio and its timings, dropping only the D-ID talking head.
    "LAYER_AVATAR_VIDEO": True,
    "LAYER_TEXT_SLIDES": True,
    # Per-concept diagrams only, never the overviews below.
    "LAYER_INFOGRAPHICS": True,
    # The lesson and section overview diagrams, which are per-section, not per-concept.
    "LAYER_OVERVIEW_DIAGRAMS": True,
    "LAYER_CONCLUSION_SLIDE": True,
    # Off skips one O1 call and leaves concept.visual unset, which only the layers above read.
    "LAYER_PLANNER_VISUAL_TECHNIQUES": True,
    # Off sends the map clips to the image model too, so nothing is web-sourced.
    "LAYER_WEB_IMAGES": True,
    # Gentle ffmpeg camera moves over each still, as an alternative to Kling/Luma AI motion.
    "LAYER_PROGRAMMATIC_MOTION": False,
}

# Which callable answers to each config title. This is a lookup table and its order means
# nothing: the order stages run in comes from config/stages.json. Adding an entry here
# does not schedule it, and the config is what to edit to change the pipeline.
STAGES: Dict[str, Callable] = {
    "Knowledge Graph": knowledge_graph.generate_lesson_knowledge_graph,
    "Video Plan": video_plan.generate_lesson_video_plan,
    "Video Transcript": transcript.generate_lesson_transcript,
    "Avatar Clips": avatar_clips.generate_avatar_assets,
    "Text Overlays": text_overlays.generate_text_overlays,
    "Scenes Breakdown": scenes_breakdown.generate_clips,
    "Image Gen Clips": image_clips.generate_all_images,
    "Video Gen Clips": video_clips.generate_all_videos,
    "Local Render": local_render.render_lesson,
}


# Dropped whole in local mode: the vendor fetches the asset over the internet and a local
# folder cannot serve it. Luma and Kling need a URL per still, and nothing downstream of them
# runs locally anyway. D-ID is the same problem but it is one block inside Avatar Clips, so it
# is skipped in place by stages/avatar_clips.py and the ElevenLabs audio around it still runs.
LOCAL_SKIP = {"Video Gen Clips"}


def pipeline(skip: set | None = None) -> List[str]:
    """Stage titles in config order, minus anything in skip."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    titles = [entry["title"] for entry in config["content"]["subsection"]
              if entry.get("type", "gen-ai") == "custom" and entry["title"] not in (skip or set())]
    if STORAGE == "local":
        return [title for title in titles if title not in LOCAL_SKIP]
    return titles


def video_type(name: str) -> Dict[str, Any]:
    """One entry of config/video_types.json, validated, stating only what it changes."""
    config = json.loads(VIDEO_TYPES.read_text(encoding="utf-8"))
    if name not in config:
        raise SystemExit(f"No such video type {name!r}; have: {', '.join(sorted(config))}")
    entry = config[name]
    if bad := sorted(set(entry) - {"layers", "skip_stages", "params", "unsupported"}):
        raise SystemExit(f"video type {name!r} has unknown key(s): {', '.join(bad)}")
    flags, skip, params = entry.get("layers", {}), entry.get("skip_stages", []), entry.get("params", {})
    # Refused rather than silently defaulted, so a typo doesn't quietly buy a full set of vendor calls.
    if bad := sorted(set(flags) - set(LAYER_DEFAULTS)):
        raise SystemExit(f"video type {name!r} sets unknown layer(s): {', '.join(bad)}\n"
                         f"known layers: {', '.join(LAYER_DEFAULTS)}")
    if bad := sorted(k for k, v in flags.items() if not isinstance(v, bool)):
        raise SystemExit(f"video type {name!r} must give every layer true or false: {', '.join(bad)}")
    if bad := sorted(set(skip) - set(STAGES)):
        raise SystemExit(f"video type {name!r} skips unknown stage(s): {', '.join(bad)}\n"
                         f"known stages: {', '.join(STAGES)}")
    # Only shape-checked here; each stage owns and defaults the contents of its own block.
    if bad := sorted(k for k, v in params.items() if not isinstance(v, dict)):
        raise SystemExit(f"video type {name!r} must give every param block an object: {', '.join(bad)}")
    return {"layers": {**LAYER_DEFAULTS, **flags}, "skip_stages": set(skip), "params": params,
            "unsupported": bool(entry.get("unsupported", False))}


def video_types() -> List[str]:
    """Every video type config/video_types.json defines."""
    return sorted(json.loads(VIDEO_TYPES.read_text(encoding="utf-8")))


def load_plan(execution_input: dict) -> dict:
    """The course lesson plan, which every stage and the lesson list are derived from."""
    path = get_lesson_plan_path(
        execution_input["course"], execution_input["curriculum"], execution_input["subject"])
    if STORAGE == "local" and not does_file_exist(path):
        # The first thing local mode needs and the one thing it cannot generate, so say
        # exactly where to put it rather than raising a bare file-not-found from json.
        # path_for, not the raw key: the on-disk name has its colons percent-encoded.
        from core.clients.local_store import path_for
        raise SystemExit(
            f"No lesson plan under STORAGE=local. Copy it from S3 to:\n  {path_for(path)}"
        )
    return load_json_from_s3(path)


def lessons(execution_input: dict) -> List[dict]:
    """Every subsection in the course's lesson plan, flattened to unit/chapter/section."""
    plan = load_plan(execution_input)
    return [
        {"unit": unit, "chapter": chapter, "section": section, "subsection": subsection}
        for unit, unit_plan in plan.get("Units", {}).items()
        for chapter, chapter_plan in unit_plan.get("Chapters", {}).items()
        for section, section_plan in chapter_plan.get("Sections", {}).items()
        for subsection in section_plan.get("Subsections", {})
    ]


def artifact_path(context: Context, title: str) -> str:
    """Where a stage's JSON lands. The stage never builds this path itself."""
    return get_content_path(context.course, context.curriculum, context.subject,
                            "subsection", f"{title}/{context.key}.json")


def placeholders(context: Context, plan: dict, content: dict, layer_flags: Dict[str, bool],
                 params: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """The uppercase input dict every stage receives; Context ignores the LAYER_*/*_PARAMS in it."""
    unit = context.get_unit_lesson_plan(plan)
    chapter = context.get_chapter_lesson_plan(plan)
    section = context.get_section_lesson_plan(plan)
    subsection = context.get_subsection_lesson_plan(plan)
    return {
        "GRADE": context.grade,
        "SUBJECT": context.subject,
        "COURSE": context.course,
        "CURRICULUM": context.curriculum,
        "CATEGORY": context.category,
        "UNIT_TITLE": context.unit,
        "UNIT_LESSON_PLAN": json.dumps(unit, indent=4),
        "UNIT_OBJECTIVE": unit.get("Objective", ""),
        "CHAPTER_TITLE": context.chapter,
        "CHAPTER_LESSON_PLAN": json.dumps(chapter, indent=4),
        "CHAPTER_OBJECTIVE": chapter.get("Objective", ""),
        "SECTION_TITLE": context.section,
        "SECTION_LESSON_PLAN": json.dumps(section, indent=4),
        "SECTION_OBJECTIVE": section.get("Objective", ""),
        "SUBSECTION_TITLE": context.subsection,
        "SUBSECTION_OBJECTIVE": subsection.get("Objective", ""),
        "SUBSECTION_CONCEPTS": json.dumps(subsection.get("ContentPlan", []), indent=4),
        "SUBSECTION_CONTENT": json.dumps(content, indent=4),
        "THINKING_SKILL": subsection.get("Thinking Skill", ""),
        **layer_flags,
        # One block becomes one "<name>_PARAMS" key, so a stage asks by a name it already knows.
        **{f"{name}_PARAMS": block for name, block in (params or {}).items()},
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=15))
def run_stage(title: str, context: Context, inputs: dict, force: bool = False) -> dict:
    """One stage, skipped if its artifact is already in S3. The only place skip and retry live.

    Only the canonical {key}.json is tested, never the {key}-edited.json sidecar a reviewer
    may have written. So an edited sidecar does not stop the stage regenerating, and
    deleting only the canonical file leaves a stale sidecar that downstream stages still
    prefer. To genuinely redo a stage, delete both.

    Only JSON is skipped. Media is not: every mp3, mp4, mov and png below a stage that
    runs is regenerated and re-bought at full vendor cost.
    """
    path = artifact_path(context, title)
    if does_file_exist(path) and not force:
        logger.info(f"Content already exists at {path}. Skipping!")
        return load_json_from_s3(path)

    content = STAGES[title]("subsection", title, inputs)
    save_json_to_s3(content, path)
    logger.info(f"Successfully generated custom content and saved at {path}")
    return content


def run_lesson(execution_input: dict, lesson: dict, plan: dict, titles: List[str],
               layer_flags: Dict[str, bool] | None = None, force: bool = False,
               params: Dict[str, Dict[str, Any]] | None = None) -> dict:
    """Every stage for one subsection in order; no per-stage try/except since a later stage reads what an earlier one wrote."""
    context = Context(**execution_input, **lesson)
    content: Dict[str, Any] = {}
    for title in titles:
        content.update(run_stage(
            title, context,
            placeholders(context, plan, content, layer_flags or LAYER_DEFAULTS, params), force))
    content["title"] = context.subsection
    return content


def selected(args: argparse.Namespace, execution_input: dict) -> Dict[str, dict]:
    """The lessons this run will build, keyed by the hash every artifact path carries.

    The filter is the CLI, and asking for something that matches nothing is an error
    rather than a silent no-op: a run that quietly schedules zero work and finishes clean
    looks exactly like a run that worked.
    """
    wanted = lessons(execution_input)
    for field in ("unit", "chapter", "section", "subsection"):
        values = getattr(args, field)
        if values:
            wanted = [lesson for lesson in wanted if lesson[field] in values]
    return {Context(**execution_input, **lesson).key: lesson for lesson in wanted}


class _Silent:
    """Stands in for NotificationSystem when there is nothing to notify. Any method call
    is accepted and does nothing, so it tracks the real class without restating it."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", default="AP US History - v2",
                        help="subject with version suffix, e.g. 'AP US History - v2'")
    parser.add_argument("--unit", action="append", default=[], metavar="TITLE")
    parser.add_argument("--chapter", action="append", default=[], metavar="TITLE")
    parser.add_argument("--section", action="append", default=[], metavar="TITLE")
    parser.add_argument("--subsection", action="append", default=[], metavar="TITLE",
                        help="repeatable; the usual way to name one lesson")
    parser.add_argument("--video-type", choices=video_types(), default="lore",
                        help="which layers run, from config/video_types.json (default lore)")
    parser.add_argument("--allow-unsupported", action="store_true",
                        help="run a video type marked unsupported in config/video_types.json")
    parser.add_argument("--until", metavar="STAGE",
                        help="stop after this stage instead of running the rest")
    parser.add_argument("--force", action="store_true",
                        help="run every stage even where its JSON already exists")
    parser.add_argument("--workers", type=int, default=3,
                        help="lessons built in parallel (default 3)")
    parser.add_argument("--storage", choices=("s3", "local"), default=STORAGE,
                        help="where artifacts live; local skips the stages whose vendors must "
                             f"fetch a URL ({', '.join(sorted(LOCAL_SKIP))}, and D-ID inside "
                             "Avatar Clips). Local Render needs local, so s3 has no renderer")
    parser.add_argument("--list-stages", action="store_true", help="print the pipeline and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the lessons, keys and artifact paths, touch nothing")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    selection = video_type(args.video_type)
    # AP stays wired but unmaintained: prompts, models and pacing were all retuned for lore.
    if selection["unsupported"] and not args.allow_unsupported:
        raise SystemExit(f"video type {args.video_type!r} is unsupported and untested; "
                         f"pass --allow-unsupported to run it anyway")
    layer_flags, skip_stages, params = selection["layers"], selection["skip_stages"], selection["params"]
    titles = pipeline(skip_stages)
    if args.list_stages:
        for number, title in enumerate(titles, 1):
            print(f"{number}. {title}")
        for title in sorted(skip_stages):
            print(f"-. {title} (skipped: video type {args.video_type})")
        for title in sorted(LOCAL_SKIP - skip_stages) if STORAGE == "local" else []:
            print(f"-. {title} (skipped: STORAGE=local)")
        for old, new in sorted(LOCAL_SWAP.items()) if STORAGE == "local" else []:
            print(f"-. {old} (replaced by {new}: STORAGE=local)")
        print(f"\nvideo type: {args.video_type}")
        for flag, on in layer_flags.items():
            print(f"  {'on ' if on else 'off'}  {flag}")
        for key, block in params.items():
            print(f"  param  {key}: {block}")
        return 0
    if args.until:
        if args.until not in titles:
            parser.error(f"unknown stage {args.until!r}; see --list-stages")
        titles = titles[: titles.index(args.until) + 1]

    # CloudWatch is AWS, so local mode logs to the console only.
    setup_logging(cloudwatch=not args.dry_run and STORAGE != "local")

    data = get_execution_input(args.subject)
    execution_input = data["ExecutionInput"]

    keys = selected(args, execution_input)
    if not keys:
        parser.error("no lessons matched; narrow or widen --unit/--chapter/--section/--subsection")

    if args.dry_run:
        print(f"subject: {execution_input['subject']}")
        print(f"storage: {STORAGE}")
        print(f"stages : {len(titles)} of {len(pipeline())}")
        print(f"type   : {args.video_type}"
              + (f" (skips {', '.join(sorted(skip_stages))})" if skip_stages else ""))
        for flag, on in layer_flags.items():
            print(f"  {'on ' if on else 'off'}  {flag}")
        for key, block in params.items():
            print(f"  param  {key}: {block}")
        for key, lesson in keys.items():
            context = Context(**execution_input, **lesson)
            print(f"\n{key}  {lesson['subsection']}")
            print(f"  media  {context.media_path}")
            for title in titles:
                print(f"  {'HAVE' if does_file_exist(artifact_path(context, title)) else 'MISS'}"
                      f"  {artifact_path(context, title)}")
        return 0

    # A versioned subject starts from the v0 corpus. Idempotent: skipped if the prefix is
    # already there.
    base = f"{execution_input['curriculum']}/{execution_input['course']}/{args.subject.split('-')[0].strip()} - v0/"
    new = f"{execution_input['curriculum']}/{execution_input['course']}/{execution_input['subject']}/"
    if base != new and not check_folder_exists(new):
        logger.info(f"Copying base contents {base} -> {new}")
        copy_s3_folder(base, new)

    logger.info(f"STARTING GENERATION IN SUBJECT: {execution_input['subject']}")
    logger.info(f"{len(keys)} lesson(s), {len(titles)} stage(s) each")
    off = [flag for flag, on in layer_flags.items() if not on]
    logger.info(f"Video type '{args.video_type}': "
                + (f"layers off: {', '.join(off)}" if off else "every layer on")
                + (f"; stages skipped: {', '.join(sorted(skip_stages))}" if skip_stages else ""))
    if STORAGE == "local":
        swaps = ', '.join(f"{old} -> {new}" for old, new in sorted(LOCAL_SWAP.items()))
        logger.info(f"STORAGE=local: skipping {', '.join(sorted(LOCAL_SKIP))} and the D-ID "
                    f"block inside Avatar Clips; {swaps}")

    # Notifications are SES and Google Chat, both AWS-side, and a local run has no audience.
    notifications = _Silent() if STORAGE == "local" else NotificationSystem(data, keys)
    notifications.send_initial_message()

    plan = load_plan(execution_input)

    failures = 0
    futures = {}
    with ContextAwareThreadPoolExecutor(max_workers=args.workers) as pool:
        for key, lesson in keys.items():
            logger.info(f"GENERATING SUBSECTION: {lesson['subsection']}")
            work = with_logging_context(lesson_id=key)(run_lesson)
            futures[pool.submit(work, execution_input, lesson, plan, titles,
                                layer_flags, args.force, params)] = key

        for future in as_completed(futures):
            key = futures[future]
            try:
                future.result()
                notifications.send_success_message(key)
            except Exception as error:
                failures += 1
                logger.error(
                    f"Generation of subsection '{keys[key]['subsection']}' failed with error:\n{error}")
                notifications.send_error_message(key, str(error), traceback.format_exc())

    logger.info(f"Finished: {len(keys) - failures} succeeded, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
