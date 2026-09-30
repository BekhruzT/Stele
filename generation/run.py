#!/usr/bin/env python3
"""Generate lore videos from a run directory, one stage at a time.

The run directory is a local folder or an s3://bucket/prefix holding lesson_plan.json, and
every artifact of the run is written back into it, one folder per video. This module is the
whole orchestrator: stage order, dispatch, skip, retry, video selection and the worker
pool. A stage knows nothing about any of it -- it is handed a dict and returns a dict.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import traceback
from concurrent.futures import as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

# Load the environment before any core import, because core/constants.py reads os.getenv at
# module scope and would otherwise bake in None for every key.
for _env in (Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"):
    if _env.is_file():
        load_dotenv(_env)
        break


def storage_for(directory: str) -> tuple[Dict[str, str], str]:
    """The environment a run directory needs, and the key prefix of the directory itself."""
    if directory.startswith("s3://"):
        bucket, _, prefix = directory[len("s3://"):].partition("/")
        prefix = prefix.strip("/")
        return {"STORAGE": "s3", "S3_BUCKET": bucket}, f"{prefix}/" if prefix else ""
    return {"STORAGE": "local", "LOCAL_STORAGE_ROOT": str(Path(directory).resolve())}, ""


# The directory has to reach the environment before the first core import, because
# core/clients/s3.py picks its backend and bucket at module scope. The real parser in
# build_parser() runs inside main(), long after that, so the argument is read twice.
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("directory", nargs="?")
_directory = _pre.parse_known_args()[0].directory
if _directory:
    _env_vars, ROOT = storage_for(_directory)
    os.environ.update(_env_vars)
else:
    ROOT = ""
STORAGE = os.getenv("STORAGE", "s3").strip().lower()

from config.subject_profiles import resolve_profile  # noqa: E402
from core.clients.s3 import (does_file_exist, load_json_from_s3,  # noqa: E402
                             save_json_to_s3)
from core.context import Context  # noqa: E402
from core.log import (ContextAwareThreadPoolExecutor, setup_logging,  # noqa: E402
                      with_logging_context)
from core.notification_system import NotificationSystem  # noqa: E402
from stages import (avatar_clips, image_clips, local_render,  # noqa: E402
                    scenes_breakdown, text_overlays, transcript, video_clips,
                    video_plan)

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
    titles = [title for title in json.loads(CONFIG.read_text(encoding="utf-8"))["stages"]
              if title not in (skip or set())]
    if STORAGE == "local":
        return [title for title in titles if title not in LOCAL_SKIP]
    return titles


def video_type(name: str) -> Dict[str, Any]:
    """One entry of config/video_types.json, validated, stating only what it changes."""
    config = json.loads(VIDEO_TYPES.read_text(encoding="utf-8"))
    if name not in config:
        raise SystemExit(f"No such video type {name!r}; have: {', '.join(sorted(config))}")
    entry = config[name]
    if bad := sorted(set(entry) - {"layers", "skip_stages", "params"}):
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
    return {"layers": {**LAYER_DEFAULTS, **flags}, "skip_stages": set(skip), "params": params}


def video_types() -> List[str]:
    """Every video type config/video_types.json defines."""
    return sorted(json.loads(VIDEO_TYPES.read_text(encoding="utf-8")))


def load_plan(root: str) -> dict:
    """The run directory's lesson_plan.json, which the video list is derived from."""
    path = f"{root}lesson_plan.json"
    if not does_file_exist(path):
        raise SystemExit(f"No lesson_plan.json in the run directory ({_directory})")
    return load_json_from_s3(path)


def slug(text: str, limit: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].rstrip("-")


def videos(plan: dict, root: str) -> List[Context]:
    """Every video in the plan, each with the folder all of its artifacts go into."""
    meta = plan.get("_meta", {})
    subject = resolve_profile(meta.get("subject", ""), meta.get("subject_profile")).id
    return [
        Context(root=root, folder=f"c{ci:02d}-v{vi:02d}-{slug(video['title'])}", subject=subject,
                chapter=chapter["chapter"], title=video["title"], lessons=video["lessons"])
        for ci, chapter in enumerate(plan["chapters"], 1)
        for vi, video in enumerate(chapter["videos"], 1)
    ]


def selected(wanted: List[str], plan: dict, root: str) -> Dict[str, Context]:
    """The videos this run builds, keyed by folder. A --video matches a folder prefix
    (c01-v02) or an exact title; asking for nothing builds every video in the plan."""
    found = videos(plan, root)
    if wanted:
        found = [c for c in found if any(c.folder.startswith(w) or c.title == w for w in wanted)]
    return {context.key: context for context in found}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=15))
def run_stage(title: str, context: Context, inputs: dict, force: bool = False) -> dict:
    """One stage, skipped if its artifact already exists. The only place skip and retry live.

    Only the canonical "<stage>.json" is tested, never the "<stage>-edited.json" sidecar a
    reviewer may have written. So an edited sidecar does not stop the stage regenerating, and
    deleting only the canonical file leaves a stale sidecar that downstream stages still
    prefer. To genuinely redo a stage, delete both.

    Only JSON is skipped. Media is not: every mp3, mp4, mov and png below a stage that
    runs is regenerated and re-bought at full vendor cost.
    """
    path = context.artifact_path(title)
    if does_file_exist(path) and not force:
        logger.info(f"Content already exists at {path}. Skipping!")
        return load_json_from_s3(path)

    content = STAGES[title](path, title, inputs)
    save_json_to_s3(content, path)
    logger.info(f"Successfully generated custom content and saved at {path}")
    return content


def run_video(context: Context, titles: List[str], layer_flags: Dict[str, bool] | None = None,
              force: bool = False, params: Dict[str, Dict[str, Any]] | None = None) -> None:
    """Every stage for one video in order; no per-stage try/except since a later stage reads what an earlier one wrote."""
    inputs = {
        **context.model_dump(),
        **(layer_flags or LAYER_DEFAULTS),
        # One block becomes one "<name>_PARAMS" key, so a stage asks by a name it already knows.
        **{f"{name}_PARAMS": block for name, block in (params or {}).items()},
    }
    for title in titles:
        run_stage(title, context, inputs, force)


class _Silent:
    """Stands in for NotificationSystem when there is nothing to notify. Any method call
    is accepted and does nothing, so it tracks the real class without restating it."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",
                        help="run directory holding lesson_plan.json: a local folder or s3://bucket/prefix")
    parser.add_argument("--video", action="append", default=[], metavar="FOLDER|TITLE",
                        help="repeatable; a folder prefix such as c01-v02, or an exact title")
    parser.add_argument("--video-type", choices=video_types(), default="lore",
                        help="which layers run, from config/video_types.json (default lore)")
    parser.add_argument("--until", metavar="STAGE",
                        help="stop after this stage instead of running the rest")
    parser.add_argument("--force", action="store_true",
                        help="run every stage even where its JSON already exists")
    parser.add_argument("--workers", type=int, default=3,
                        help="videos built in parallel (default 3)")
    parser.add_argument("--list-stages", action="store_true", help="print the pipeline and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the videos, folders and artifact paths, touch nothing")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    selection = video_type(args.video_type)
    layer_flags, skip_stages, params = selection["layers"], selection["skip_stages"], selection["params"]
    titles = pipeline(skip_stages)
    if args.list_stages:
        for number, title in enumerate(titles, 1):
            print(f"{number}. {title}")
        for title in sorted(skip_stages):
            print(f"-. {title} (skipped: video type {args.video_type})")
        for title in sorted(LOCAL_SKIP - skip_stages) if STORAGE == "local" else []:
            print(f"-. {title} (skipped: local run directory)")
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

    contexts = selected(args.video, load_plan(ROOT), ROOT)
    if not contexts:
        parser.error("no videos matched --video; see --dry-run for the folder names")

    if args.dry_run:
        print(f"directory: {args.directory}")
        print(f"storage  : {STORAGE}")
        print(f"stages   : {len(titles)} of {len(pipeline())}")
        print(f"type     : {args.video_type}"
              + (f" (skips {', '.join(sorted(skip_stages))})" if skip_stages else ""))
        for flag, on in layer_flags.items():
            print(f"  {'on ' if on else 'off'}  {flag}")
        for key, block in params.items():
            print(f"  param  {key}: {block}")
        for key, context in contexts.items():
            print(f"\n{key}  {context.title}")
            print(f"  media  {context.media_path}")
            for title in titles:
                path = context.artifact_path(title)
                print(f"  {'HAVE' if does_file_exist(path) else 'MISS'}  {path}")
        return 0

    logger.info(f"STARTING GENERATION IN: {args.directory}")
    logger.info(f"{len(contexts)} video(s), {len(titles)} stage(s) each")
    off = [flag for flag, on in layer_flags.items() if not on]
    logger.info(f"Video type '{args.video_type}': "
                + (f"layers off: {', '.join(off)}" if off else "every layer on")
                + (f"; stages skipped: {', '.join(sorted(skip_stages))}" if skip_stages else ""))
    if STORAGE == "local":
        logger.info(f"Local run directory: skipping {', '.join(sorted(LOCAL_SKIP))} and the D-ID "
                    f"block inside Avatar Clips")

    # Notifications are SES and Google Chat, both AWS-side, and a local run has no audience.
    notifications = _Silent() if STORAGE == "local" else NotificationSystem(args.directory, contexts)
    notifications.send_initial_message()

    failures = 0
    futures = {}
    with ContextAwareThreadPoolExecutor(max_workers=args.workers) as pool:
        for key, context in contexts.items():
            logger.info(f"GENERATING VIDEO: {context.title}")
            work = with_logging_context(lesson_id=key)(run_video)
            futures[pool.submit(work, context, titles, layer_flags, args.force, params)] = key

        for future in as_completed(futures):
            key = futures[future]
            try:
                future.result()
                notifications.send_success_message(key)
            except Exception as error:
                failures += 1
                logger.error(f"Generation of video '{contexts[key].title}' failed with error:\n{error}")
                notifications.send_error_message(key, str(error), traceback.format_exc())

    logger.info(f"Finished: {len(contexts) - failures} succeeded, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

