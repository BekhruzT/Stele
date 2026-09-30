#!/usr/bin/env python3
"""Exercise run.py's orchestration with storage and the stages stubbed out.

run.py decides what runs and in what order, so a mistake in it is a mistake in every video.
This runs it against a fake run directory and fake stages and asserts what every stage
depends on: the storage a directory selects, video selection and folders, stage order,
artifact paths, the skip-if-exists shortcut, and the inputs each stage receives.

Needs no credentials and buys nothing. Run it after any change to run.py.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tenacity import RetryError  # noqa: E402

import run  # noqa: E402
from stages.video_plan import plan_facts, restore_facts  # noqa: E402


def _tmp_video_types(config: dict) -> Path:
    """A throwaway video_types.json holding the given config, for the rejection cases."""
    path = Path(tempfile.mkdtemp()) / "video_types.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path

# install() replaces run.STAGES with stubs, so the real dispatch map has to be captured now
# or the "every title is dispatchable" check compares the stubs against themselves.
REAL_STAGES = dict(run.STAGES)

ROOT = "runs/demo/"
PLAN = {
    "_meta": {"subject": "World History", "subject_profile": "history"},
    "chapters": [
        {"chapter": "Chapter 1: Trade", "videos": [
            {"title": "The Silk Roads: How It Worked", "lessons": [
                {"name": "Caravans", "concepts": ["Caravanserais sat a day's ride apart.", "  "]},
                {"name": "Goods", "concepts": ["Silk was a currency in Central Asia."]},
            ]},
            {"title": "Mansa Musa's Gold", "lessons": [{"name": "Hajj", "concepts": ["He crossed Cairo in 1324."]}]},
        ]},
        {"chapter": "Chapter 2: Empires", "videos": [
            {"title": "Gunpowder Empires", "lessons": [{"name": "Guns", "concepts": ["Cannon broke Constantinople's walls."]}]},
        ]},
    ],
}
FOLDER = "c01-v01-the-silk-roads-how-it-worked"

TITLES = ["Video Plan", "Video Transcript", "Avatar Clips", "Text Overlays",
          "Scenes Breakdown", "Image Gen Clips", "Video Gen Clips", "Local Render"]


class FakeStorage:
    """Stands in for the three storage calls run.py makes."""

    def __init__(self, existing: dict[str, dict] | None = None):
        self.existing = dict(existing or {})
        self.saved: dict[str, dict] = {}

    def does_file_exist(self, path):
        return path in self.existing or path == f"{ROOT}lesson_plan.json"

    def load_json_from_s3(self, path):
        if path == f"{ROOT}lesson_plan.json":
            return PLAN
        return self.existing[path]

    def save_json_to_s3(self, content, path):
        self.saved[path] = content


def install(storage: FakeStorage, stages: dict | None = None) -> list[tuple[str, dict]]:
    """Point run.py at the fakes. Returns the list stage calls get recorded into."""
    calls: list[tuple[str, dict]] = []

    def recorder(title):
        def stage(output_path, output_type, inputs):
            assert output_path == f"{ROOT}{inputs['folder']}/{title}.json", output_path
            assert output_type == title, (output_type, title)
            calls.append((title, inputs))
            return {title.lower().replace(" ", "_"): f"{title} output"}
        return stage

    run.does_file_exist = storage.does_file_exist
    run.load_json_from_s3 = storage.load_json_from_s3
    run.save_json_to_s3 = storage.save_json_to_s3
    # Stubs for every real stage, not just the ones the current mode schedules, so the fakes
    # do not change shape with STORAGE.
    run.STAGES = stages if stages is not None else {t: recorder(t) for t in REAL_STAGES}
    return calls


def context():
    return run.selected([FOLDER[:7]], run.load_plan(ROOT), ROOT)[FOLDER]


def check_storage_for():
    env, root = run.storage_for("s3://my-bucket/runs/demo/")
    assert env == {"STORAGE": "s3", "S3_BUCKET": "my-bucket"} and root == "runs/demo/", (env, root)
    assert run.storage_for("s3://my-bucket")[1] == ""
    env, root = run.storage_for("some/local/dir")
    assert env["STORAGE"] == "local" and Path(env["LOCAL_STORAGE_ROOT"]).is_absolute() and root == "", env
    print("  storage    s3:// picks the bucket and prefix, anything else is a local root")


def check_pipeline_order():
    # run.STORAGE is fixed at import from the ambient .env, and pipeline() filters on it. Pin
    # it per case, or this asserts the stage order against whatever mode the developer has.
    original = run.STORAGE
    try:
        run.STORAGE = "s3"
        assert run.pipeline() == TITLES, run.pipeline()
        run.STORAGE = "local"
        local = run.pipeline()
        expected = [t for t in TITLES if t not in run.LOCAL_SKIP]
        assert local == expected, local
        assert local[-1] == "Local Render", local
    finally:
        run.STORAGE = original
    assert not set(TITLES) - set(REAL_STAGES), set(TITLES) - set(REAL_STAGES)
    print(f"  order      {len(TITLES)} stages on s3, {len(expected)} on local, "
          f"config order, all dispatchable")


def check_video_selection():
    install(FakeStorage())
    plan = run.load_plan(ROOT)
    every = run.selected([], plan, ROOT)
    assert list(every) == [FOLDER, "c01-v02-mansa-musa-s-gold", "c02-v01-gunpowder-empires"], list(every)
    assert list(run.selected(["c02"], plan, ROOT)) == ["c02-v01-gunpowder-empires"]
    assert list(run.selected(["Mansa Musa's Gold"], plan, ROOT)) == ["c01-v02-mansa-musa-s-gold"]
    assert not run.selected(["c09"], plan, ROOT)

    video = every[FOLDER]
    assert (video.subject, video.chapter, video.title) == ("history", "Chapter 1: Trade", "The Silk Roads: How It Worked")
    assert video.media_path == f"{ROOT}{FOLDER}/media/", video.media_path
    assert len(run.slug("x" * 200)) == 60
    print(f"  selection  {len(every)} videos; folder prefix, chapter prefix and exact title all select")


def check_full_run():
    storage = FakeStorage()
    calls = install(storage)
    run.run_video(context(), run.pipeline())

    assert [title for title, _ in calls] == TITLES, [t for t, _ in calls]
    assert sorted(storage.saved) == sorted(f"{ROOT}{FOLDER}/{t}.json" for t in TITLES), sorted(storage.saved)
    for title, inputs in calls:
        assert {"root", "folder", "subject", "chapter", "title", "lessons"} <= set(inputs), (title, set(inputs))
        assert {k: inputs[k] for k in run.LAYER_DEFAULTS} == run.LAYER_DEFAULTS, title
    print(f"  full run   {len(TITLES)} stages in order, each artifact saved under the video folder")


def check_skip_and_force():
    cached = f"{ROOT}{FOLDER}/Video Plan.json"
    storage = FakeStorage({cached: {"cached": True}})
    calls = install(storage)
    run.run_video(context(), run.pipeline())
    assert "Video Plan" not in [title for title, _ in calls], "cached stage still ran"
    assert cached not in storage.saved

    calls = install(FakeStorage({cached: {"cached": True}}))
    run.run_video(context(), run.pipeline(), force=True)
    assert len(calls) == len(TITLES), f"--force should rerun the cached stage, ran {len(calls)}"
    print("  skip       cached stage skipped; --force overrides it")


def check_failure_stops_video():
    storage = FakeStorage()
    calls = install(storage)
    attempts = []

    def explode(output_path, output_type, inputs):
        attempts.append(output_type)
        raise RuntimeError("stage failed")

    run.STAGES = {**run.STAGES, "Video Transcript": explode}
    # tenacity re-raises as RetryError rather than the original exception.
    try:
        run.run_video(context(), run.pipeline())
    except RetryError as error:
        assert isinstance(error.last_attempt.exception(), RuntimeError)
    else:
        raise AssertionError("a failing stage should stop the video")

    assert len(attempts) == 3, f"stop_after_attempt(3) not wired: {len(attempts)} attempts"
    assert [t for t, _ in calls] == ["Video Plan"], [t for t, _ in calls]
    assert len(storage.saved) == 1, sorted(storage.saved)
    print("  failure    retried 3x, raised RetryError, downstream never ran")


def check_video_type():
    lore = run.video_type("lore")
    assert run.video_types() == ["lore"], run.video_types()
    assert run.build_parser().get_default("video_type") == "lore"
    assert lore["skip_stages"] == {"Video Gen Clips"}, lore["skip_stages"]
    assert not lore["layers"]["LAYER_WEB_IMAGES"] and lore["layers"]["LAYER_PROGRAMMATIC_MOTION"]
    assert {"LAYER_PROGRAMMATIC_MOTION", "NARRATION"} <= set(lore["params"]), lore["params"]

    titles = run.pipeline(lore["skip_stages"])
    calls = install(FakeStorage())
    run.run_video(context(), titles, lore["layers"], params=lore["params"])
    assert [t for t, _ in calls] == [t for t in TITLES if t != "Video Gen Clips"], [t for t, _ in calls]
    for title, inputs in calls:
        assert {k: inputs[k] for k in lore["layers"]} == lore["layers"], title
        assert inputs["NARRATION_PARAMS"] == lore["params"]["NARRATION"], title

    for bad, expect in [({"layers": {"LAYER_NOPE": True}}, "unknown layer"),
                        ({"layers": {"LAYER_TEXT_SLIDES": "false"}}, "true or false"),
                        ({"skip_stages": ["Nonexistent Stage"]}, "unknown stage"),
                        ({"nonsense": 1}, "unknown key"),
                        ({"params": {"x": "not-a-dict"}}, "param block an object")]:
        with patch.object(run, "VIDEO_TYPES", _tmp_video_types({"t": bad})):
            try:
                run.video_type("t")
                raise AssertionError(f"expected SystemExit for {bad}")
            except SystemExit as error:
                assert expect in str(error), (bad, str(error))
    print(f"  types      lore skips Video Gen Clips ({len(titles)} stages dispatched, flags and params "
          f"reach each); bad layer, value, stage and key all refused")


def check_video_plan_facts():
    """The planner's facts come from the plan, and drifted wording is put back verbatim."""
    video = context()
    facts = plan_facts(video)
    assert facts == ["Caravanserais sat a day's ride apart.", "Silk was a currency in Central Asia."], facts
    structure = {"sections": [{"concepts": [{"facts": ["Caravanserais sat a days ride apart"]}]}]}
    structure, missing = restore_facts(structure, facts)
    assert structure["sections"][0]["concepts"][0]["facts"] == [facts[0]], structure
    assert missing == [facts[1]], missing
    print("  plan facts blank concepts dropped, reworded fact restored, dropped fact reported")


def main() -> int:
    print("run.py orchestration:")
    run.STORAGE = "s3"
    check_storage_for()
    check_pipeline_order()
    check_video_selection()
    check_full_run()
    check_skip_and_force()
    check_video_type()
    check_failure_stops_video()
    check_video_plan_facts()
    print("\nAll orchestration checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
