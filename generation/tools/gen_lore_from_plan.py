"""Generate reference-led lore: plan, five hooks, connected draft, and whole-script review."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from uuid import uuid4

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from config.subject_profiles import resolve_profile
from core.clients.lore import DEFAULT_CHOICE_MODEL, DEFAULT_MODEL, LoreClient
from core.lore_editorial import Source, generate_story
from core.lore_review import diagnostics
from tools.build_lore_viewer import ROOT as VIEWER_ROOT, build, run_dir

LORE_PLAN = BASE / "tools/lore_video_plan.json"


def plan_voice(plan: dict, override: str | None = None):
    meta = plan.get("_meta", {})
    return resolve_profile(meta.get("subject", ""), override or meta.get("subject_profile")).voice


def generate(chapter_idx: int, video_idx: int, root: Path = VIEWER_ROOT, plan_path=LORE_PLAN,
             profile: str | None = None, cold_open_only: bool = False, *, model=DEFAULT_MODEL,
             review_model=None, reasoning="high", choice_model=DEFAULT_CHOICE_MODEL,
             choice_reasoning="medium", target_words=None, hook_only=False,
             max_revisions=2, approved_hook=None, run_id=None, fresh_hook=False) -> Path:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    chapter = plan["chapters"][chapter_idx]
    video = chapter["videos"][video_idx]
    voice = plan_voice(plan, profile)
    plan_meta = plan.get("_meta", {})
    # --profile changes how the story is written, not which subject the topic belongs to.
    subject = resolve_profile(plan_meta.get("subject", ""),
        plan_meta.get("content_subject") or plan_meta.get("subject_profile")).id
    narration_profile = resolve_profile(plan_meta.get("subject", ""),
        profile or plan_meta.get("subject_profile")).id
    sources = [Source(id=f"S{i + 1:03d}", context=lesson, text=text)
               for i, (lesson, text) in enumerate((lesson["name"], c.strip())
                   for lesson in video["lessons"] for c in lesson.get("concepts", []) if c.strip())]
    scope = "hooks" if hook_only else "opening" if cold_open_only else "full"
    words = target_words if target_words is not None else (1500 if cold_open_only else 4600)
    identity = run_id or (datetime.now().strftime("%Y%m%d-v2-%H%M%S-%f") + "-" + uuid4().hex[:8])
    if identity in {".", ".."} or "/" in identity or "\\" in identity or Path(identity).name != identity:
        raise ValueError("run_id must be a directory name, not a path")
    out_dir = run_dir(subject, video["title"], root, identity)
    out_dir.mkdir(parents=True, exist_ok=False)
    meta = {"title": video["title"], "chapter": chapter["chapter"], "origin": "generated",
            "content_subject": subject, "narration_profile": narration_profile,
            "created_at": datetime.now().astimezone().isoformat(),
            "scope": scope, "note": f"GENERATED v2 — {scope}; running", "status": "running"}
    meta_path = out_dir / "meta.json"
    def save_meta():
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    save_meta()
    client = None
    try:
        client = LoreClient(model, review_model, reasoning, out_dir / "editorial/calls",
                            choice_model, choice_reasoning)
        result = generate_story(client, voice, video["title"], chapter["chapter"], sources,
            words, scope, max_revisions, approved_hook, out_dir / "editorial", fresh_hook=fresh_hook)
        if result["status"] == "needs_hook_research":
            text = "Hook research needed\n\n" + result["hook_brief"]["reason"] + "\n\n" + "\n\n".join(
                result["hook_brief"]["missing_research"]) + "\n"
            filename = "hook_review.txt"
            meta["scope"] = "research_needed"
        elif scope == "hooks" or result["status"] == "needs_hook_revision":
            text = "\n\n".join(f"{i + 1}. {h['text']}" for i, h in enumerate(result["hooks"]["candidates"])) + "\n"
            filename = "hook_candidates.txt"
            meta["scope"] = "hooks"
            if result["status"] != "needs_hook_revision":
                (out_dir / "selected_hook.txt").write_text(result["hook"] + "\n", encoding="utf-8")
        else:
            text = result["text"]
            filename = "opening_sample.txt" if scope == "opening" else "full.txt"
        out = out_dir / filename
        out.write_text(text, encoding="utf-8")
        stats = diagnostics(text)
        (out_dir / "editorial/diagnostics.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        meta.update(status=result["status"], prompt_version=result["prompt_version"], **client.provenance())
        meta["note"] = (f"GENERATED {result['prompt_version']} — {client.model}; {meta['scope']}; {stats['word_count']:,} words. "
                        f"{result['status'].replace('_', ' ')}. Not a hand-curated reference.")
        print(f"Wrote: {out}\nStatus: {result['status']}\nWords: {stats['word_count']:,}", flush=True)
        return out
    except Exception as exc:
        meta.update(status="failed", error_type=type(exc).__name__, note="GENERATED v2 — failed; see editorial call records")
        raise
    finally:
        if client:
            meta.update(client.provenance())
        save_meta()
        build(root, quiet=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", type=int, default=0)
    parser.add_argument("--video", type=int, default=0)
    parser.add_argument("--root", type=Path, default=VIEWER_ROOT)
    parser.add_argument("--plan", type=Path, default=LORE_PLAN)
    parser.add_argument("--profile", help="Writing profile override; preserves the plan's content subject")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--cold-open-only", action="store_true", help="Connected opening sample (default ~1500 words)")
    modes.add_argument("--hook-only", action="store_true", help="Five candidates plus selection; no narrative")
    parser.add_argument("--target-words", type=int, help="Soft writing budget; full default 4600")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--review-model", help="Defaults to writing model; provenance records both")
    parser.add_argument("--reasoning", choices=["low", "medium", "high", "xhigh", "max"], default="high")
    parser.add_argument("--choice-model", default=DEFAULT_CHOICE_MODEL)
    parser.add_argument("--choice-reasoning", choices=["low", "medium", "high", "xhigh", "max"], default="medium")
    parser.add_argument("--max-revisions", type=int, choices=range(4), default=2)
    parser.add_argument("--approved-hook-file", type=Path, help="Lock a user-approved hook; findings remain visible")
    parser.add_argument("--fresh-hook", action="store_true", help="Test new hooks instead of reusing this topic's approved one")
    parser.add_argument("--run-id", help="Must be a new run directory name")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.run_id and (Path(args.run_id).name != args.run_id or args.run_id in {".", ".."} or "/" in args.run_id or "\\" in args.run_id):
        parser.error("--run-id must be a directory name, not a path")
    if args.list:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        for ci, chapter in enumerate(plan["chapters"]):
            for vi, video in enumerate(chapter["videos"]):
                print(f"[{ci},{vi}] {video['title']}")
        return 0
    out = generate(args.chapter, args.video, args.root, args.plan, args.profile, args.cold_open_only,
        model=args.model, review_model=args.review_model, reasoning=args.reasoning,
        choice_model=args.choice_model, choice_reasoning=args.choice_reasoning,
        target_words=args.target_words, hook_only=args.hook_only, max_revisions=args.max_revisions,
        approved_hook=args.approved_hook_file.read_text(encoding="utf-8").strip() if args.approved_hook_file else None,
        run_id=args.run_id, fresh_hook=args.fresh_hook)
    return 2 if json.loads((out.parent / "meta.json").read_text(encoding="utf-8"))["status"].startswith("needs_") else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
