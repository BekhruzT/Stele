#!/usr/bin/env python3
"""Exercise run.py's orchestration with S3 and the stages stubbed out.

run.py decides what runs and in what order, so a mistake in it is a mistake in every lesson.
This runs it against a fake lesson plan and fake stages and asserts the four things every
stage depends on: stage order, artifact paths, the skip-if-exists shortcut, and the
accumulating content dict.

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


def _tmp_video_types(config: dict) -> Path:
    """A throwaway video_types.json holding the given config, for the rejection cases."""
    path = Path(tempfile.mkdtemp()) / "video_types.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path

# install() replaces run.STAGES with stubs, so the real dispatch map has to be captured now
# or the "every title is dispatchable" check compares the stubs against themselves.
REAL_STAGES = dict(run.STAGES)

EXECUTION_INPUT = {
    "curriculum": "college_board",
    "course": "AP US History: Video Lessons",
    "grade": "Grade 11",
    "subject": "AP US History - v2",
    "category": "High School: AP US History",
}

LESSON_PLAN = {
    "Units": {
        "Period 3: 1754-1800": {
            "Objective": "unit objective",
            "Chapters": {
                "The American Revolution": {
                    "Objective": "chapter objective",
                    "Sections": {
                        "Causes": {
                            "Objective": "section objective",
                            "Subsections": {
                                "Taxation Without Representation": {
                                    "Objective": "subsection objective",
                                    "ContentPlan": [{"concept": "Stamp Act"}],
                                    "Thinking Skill": "Causation",
                                },
                                "Boston Tea Party": {"Objective": "another"},
                            },
                        }
                    },
                },
                "Ignored Chapter": {"Sections": {"S": {"Subsections": {"Nope": {}}}}},
            },
        }
    }
}


class FakeS3:
    """Stands in for the three S3 calls run.py makes."""

    def __init__(self, existing: dict[str, dict] | None = None):
        self.existing = dict(existing or {})
        self.saved: dict[str, dict] = {}
        self.checked: list[str] = []

    def does_file_exist(self, path):
        self.checked.append(path)
        return path in self.existing

    def load_json_from_s3(self, path):
        if path.endswith("lesson_plan.json"):
            return LESSON_PLAN
        return self.existing[path]

    def save_json_to_s3(self, content, path):
        self.saved[path] = content


def install(s3: FakeS3, stages: dict | None = None) -> list[tuple[str, dict]]:
    """Point run.py at the fakes. Returns the list stage calls get recorded into."""
    calls: list[tuple[str, dict]] = []

    def recorder(title):
        def stage(output_path, output_type, inputs):
            assert output_path == "subsection", output_path
            assert output_type == title, (output_type, title)
            calls.append((title, inputs))
            return {title.lower().replace(" ", "_"): f"{title} output"}
        return stage

    run.does_file_exist = s3.does_file_exist
    run.load_json_from_s3 = s3.load_json_from_s3
    run.save_json_to_s3 = s3.save_json_to_s3
    # Stubs for every real stage, not just the ones the current mode schedules, so the fakes
    # do not change shape with STORAGE.
    run.STAGES = stages if stages is not None else {t: recorder(t) for t in REAL_STAGES}
    return calls


EXPECTED_PLACEHOLDERS = {
    "GRADE", "SUBJECT", "COURSE", "CURRICULUM", "CATEGORY",
    "UNIT_TITLE", "UNIT_LESSON_PLAN", "UNIT_OBJECTIVE",
    "CHAPTER_TITLE", "CHAPTER_LESSON_PLAN", "CHAPTER_OBJECTIVE",
    "SECTION_TITLE", "SECTION_LESSON_PLAN", "SECTION_OBJECTIVE",
    "SUBSECTION_TITLE", "SUBSECTION_OBJECTIVE", "SUBSECTION_CONCEPTS",
    "SUBSECTION_CONTENT", "THINKING_SKILL",
} | set(run.LAYER_DEFAULTS)

TITLES = ["Knowledge Graph", "Video Plan", "Video Transcript", "Avatar Clips",
          "Text Overlays", "Scenes Breakdown", "Image Gen Clips", "Video Gen Clips",
          "Local Render"]


def check_pipeline_order():
    # run.STORAGE is fixed at import from the ambient .env, and pipeline() filters on it. Pin
    # it per case, or this asserts the nine-stage order against whatever mode the developer
    # happens to have configured -- which is how it started failing once .env said local.
    original = run.STORAGE
    try:
        run.STORAGE = "s3"
        assert run.pipeline() == TITLES, run.pipeline()
        run.STORAGE = "local"
        local = run.pipeline()
        expected = [t for t in TITLES if t not in run.LOCAL_SKIP]
        assert local == expected, local
        # The render is only ever dropped by LOCAL_SKIP, so it stays last in both modes.
        assert local[-1] == "Local Render", local
        assert len(local) == len(TITLES) - len(run.LOCAL_SKIP), local
    finally:
        run.STORAGE = original
    # the dispatch map must answer to every title either mode schedules
    assert not set(TITLES) - set(REAL_STAGES), set(TITLES) - set(REAL_STAGES)
    print(f"  order      {len(TITLES)} stages on s3, {len(expected)} on local, "
          f"config order, all dispatchable")


def check_lesson_selection():
    s3 = FakeS3()
    install(s3)

    class Args:
        unit = []
        chapter = ["The American Revolution"]
        section = []
        subsection = ["Taxation Without Representation"]

    keys = run.selected(Args(), EXECUTION_INPUT)
    assert len(keys) == 1, keys
    key = next(iter(keys))
    assert keys[key]["subsection"] == "Taxation Without Representation"
    # the key is the hash the artifact paths are named after, not the title
    assert len(key) == 8 and key.isalnum(), key

    class All:
        unit = chapter = section = subsection = []

    assert len(run.selected(All(), EXECUTION_INPUT)) == 3, run.selected(All(), EXECUTION_INPUT)
    print(f"  selection  filters to 1 of 3 lessons, key {key}")
    return key


def check_full_run(key):
    s3 = FakeS3()
    calls = install(s3)
    lesson = {"unit": "Period 3: 1754-1800", "chapter": "The American Revolution",
              "section": "Causes", "subsection": "Taxation Without Representation"}

    content = run.run_lesson(EXECUTION_INPUT, lesson, LESSON_PLAN, run.pipeline())

    assert [title for title, _ in calls] == TITLES, [t for t, _ in calls]
    assert len(s3.saved) == 9, sorted(s3.saved)
    for title in TITLES:
        expected = (f"college_board/AP US History: Video Lessons/AP US History - v2/"
                    f"contents/subsection/{title}/{key}.json")
        assert expected in s3.saved, f"{expected} not in {sorted(s3.saved)}"

    # every stage sees the same uppercase contract
    for title, inputs in calls:
        assert set(inputs) == EXPECTED_PLACEHOLDERS, (title, set(inputs) ^ EXPECTED_PLACEHOLDERS)

    # content accumulates: the last stage sees the first eight stages' output, and the
    # literal-string bug in prep_content_gen_input is not reproduced here
    first, last = calls[0][1]["SUBSECTION_CONTENT"], calls[-1][1]["SUBSECTION_CONTENT"]
    assert first == "{}", first
    assert "Knowledge Graph output" in last, last
    assert "json.dumps" not in last, last
    assert content["title"] == "Taxation Without Representation"
    assert content["knowledge_graph"] == "Knowledge Graph output"
    print(f"  full run   9 stages in order, 9 artifacts saved, content accumulates")


def check_skip_and_force(key):
    base = ("college_board/AP US History: Video Lessons/AP US History - v2/"
            "contents/subsection")
    existing = {f"{base}/Knowledge Graph/{key}.json": {"cached": True}}
    s3 = FakeS3(existing)
    calls = install(s3)
    lesson = {"unit": "Period 3: 1754-1800", "chapter": "The American Revolution",
              "section": "Causes", "subsection": "Taxation Without Representation"}

    content = run.run_lesson(EXECUTION_INPUT, lesson, LESSON_PLAN, run.pipeline())
    assert "Knowledge Graph" not in [title for title, _ in calls], "cached stage still ran"
    assert len(calls) == 8, len(calls)
    assert content["cached"] is True, content
    # a skipped stage writes nothing
    assert f"{base}/Knowledge Graph/{key}.json" not in s3.saved

    s3 = FakeS3(existing)
    calls = install(s3)
    run.run_lesson(EXECUTION_INPUT, lesson, LESSON_PLAN, run.pipeline(), force=True)
    assert len(calls) == 9, f"--force should rerun the cached stage, ran {len(calls)}"
    print("  skip       cached stage skipped and returned; --force overrides it")


def check_until():
    titles = run.pipeline()[: run.pipeline().index("Avatar Clips") + 1]
    s3 = FakeS3()
    calls = install(s3)
    lesson = {"unit": "Period 3: 1754-1800", "chapter": "The American Revolution",
              "section": "Causes", "subsection": "Taxation Without Representation"}
    run.run_lesson(EXECUTION_INPUT, lesson, LESSON_PLAN, titles)
    assert [t for t, _ in calls] == TITLES[:4], [t for t, _ in calls]
    print("  --until    stops after the named stage")


def check_failure_stops_lesson():
    s3 = FakeS3()
    calls = install(s3)
    attempts = []

    def explode(output_path, output_type, inputs):
        attempts.append(output_type)
        raise RuntimeError("stage failed")

    stages = dict(run.STAGES)
    stages["Video Plan"] = explode
    run.STAGES = stages
    lesson = {"unit": "Period 3: 1754-1800", "chapter": "The American Revolution",
              "section": "Causes", "subsection": "Taxation Without Representation"}

    # tenacity re-raises as RetryError rather than the original exception, so the Google
    # Chat error message names RetryError and not the underlying cause.
    try:
        run.run_lesson(EXECUTION_INPUT, lesson, LESSON_PLAN, run.pipeline())
    except RetryError as error:
        assert isinstance(error.last_attempt.exception(), RuntimeError)
    else:
        raise AssertionError("a failing stage should stop the lesson")

    assert len(attempts) == 3, f"stop_after_attempt(3) not wired: {len(attempts)} attempts"
    # nothing downstream of the failure ran, because it would read what was never written
    assert [t for t, _ in calls] == ["Knowledge Graph"], [t for t, _ in calls]
    assert len(s3.saved) == 1, sorted(s3.saved)
    print("  failure    retried 3x, raised RetryError, downstream never ran")


def check_layer_flags():
    """Every stage sees the video type's flags, and an absent layer_flags means every layer on."""
    lesson = {"unit": "Period 3: 1754-1800", "chapter": "The American Revolution",
              "section": "Causes", "subsection": "Taxation Without Representation"}
    general = run.video_type("general")["layers"]
    assert set(general) == set(run.LAYER_DEFAULTS), general
    # general drops the per-concept visuals and the talking head; everything else is default.
    assert general == {**run.LAYER_DEFAULTS,
                       "LAYER_AVATAR_VIDEO": False, "LAYER_TEXT_SLIDES": False,
                       "LAYER_INFOGRAPHICS": False,
                       "LAYER_PLANNER_VISUAL_TECHNIQUES": False}, general

    calls = install(FakeS3())
    run.run_lesson(EXECUTION_INPUT, lesson, LESSON_PLAN, run.pipeline(), general)
    for title, inputs in calls:
        assert {k: inputs[k] for k in general} == general, (title, general)

    # No flags at all is the pre-video-type contract: every stage sees exactly the defaults.
    calls = install(FakeS3())
    run.run_lesson(EXECUTION_INPUT, lesson, LESSON_PLAN, run.pipeline())
    for title, inputs in calls:
        assert {k: inputs[k] for k in run.LAYER_DEFAULTS} == run.LAYER_DEFAULTS, title

    assert run.video_type("history") == {"layers": run.LAYER_DEFAULTS, "skip_stages": set(),
                                         "params": {}, "unsupported": True}
    print(f"  layers     {len(run.LAYER_DEFAULTS)} flags reach all 9 stages; "
          f"types {', '.join(run.video_types())}; no flags means the defaults")


def check_unsupported_types():
    """The AP exam-prep types stay wired but are refused unless the operator opts in."""
    assert run.video_type("history")["unsupported"], "history is the AP flow and is unsupported"
    assert run.video_type("general")["unsupported"], "general is the AP flow and is unsupported"
    assert not run.video_type("lore")["unsupported"], "lore is the supported flow"

    parser = run.build_parser()
    assert parser.get_default("video_type") == "lore", parser.get_default("video_type")
    # Every stage still has to be reachable: unsupported means unmaintained, not deleted.
    for name in run.video_types():
        assert set(run.video_type(name)["layers"]) == set(run.LAYER_DEFAULTS), name
    print(f"  unsupported history and general refused by default, every layer still wired")


def check_video_type_stage_skips():
    """A video type can drop a whole stage, and only the stages it names."""
    lore = run.video_type("lore")
    assert lore["skip_stages"] == {"Video Gen Clips"}, lore["skip_stages"]
    assert not lore["layers"]["LAYER_CONCLUSION_SLIDE"], "lore is expected to drop the conclusion"
    assert not lore["layers"]["LAYER_OVERVIEW_DIAGRAMS"], "lore is expected to drop the overviews"
    # Every image model-generated, and the motion it loses with Video Gen Clips added back by ffmpeg.
    assert not lore["layers"]["LAYER_WEB_IMAGES"], "lore is expected to generate every image"
    assert lore["layers"]["LAYER_PROGRAMMATIC_MOTION"], "lore is expected to animate its stills"

    titles = run.pipeline(lore["skip_stages"])
    assert "Video Gen Clips" not in titles, titles
    assert titles == [t for t in TITLES if t != "Video Gen Clips"], titles
    assert run.pipeline() == TITLES, "an unskipped pipeline must be unchanged"

    # The skipped stage must not merely be absent from the list; it must never be dispatched.
    calls = install(FakeS3())
    run.run_lesson(EXECUTION_INPUT, {"unit": "Period 3: 1754-1800",
                                     "chapter": "The American Revolution", "section": "Causes",
                                     "subsection": "Taxation Without Representation"},
                   LESSON_PLAN, titles, lore["layers"])
    assert [t for t, _ in calls] == titles, [t for t, _ in calls]

    # lore should expose its per-stage param blocks via the params contract.
    assert isinstance(lore["params"], dict), lore["params"]
    assert "LAYER_PROGRAMMATIC_MOTION" in lore["params"], "lore should override motion params"
    assert "NARRATION" in lore["params"], "lore should declare narration config"
    assert lore["params"]["NARRATION"].get("style") == "lore_sleep", lore["params"]

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
    print(f"  types      lore skips Video Gen Clips ({len(titles)} stages dispatched); "
          f"bad layer, value, stage and key all refused")


def main() -> int:
    print("run.py orchestration:")
    # These checks are about the machinery, not the backend, so pin the mode instead of
    # inheriting whatever .env says. Left on local, load_plan's seeding guard aborts the run
    # against a fake that has no plan in it. check_pipeline_order covers both modes itself,
    # and check_local_store.py covers the local backend.
    run.STORAGE = "s3"
    install(FakeS3())
    check_pipeline_order()
    key = check_lesson_selection()
    check_full_run(key)
    check_skip_and_force(key)
    check_until()
    check_layer_flags()
    check_unsupported_types()
    check_video_type_stage_skips()
    check_failure_stops_lesson()
    print("\nAll orchestration checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
