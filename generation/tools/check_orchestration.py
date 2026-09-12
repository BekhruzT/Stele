#!/usr/bin/env python3
"""Exercise run.py's orchestration with S3 and the stages stubbed out.

run.py decides what runs and in what order, so a mistake in it is a mistake in every lesson.
This runs it against a fake lesson plan and fake stages and asserts the four things every
stage depends on: stage order, artifact paths, the skip-if-exists shortcut, and the
accumulating content dict.

Needs no credentials and buys nothing. Run it after any change to run.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tenacity import RetryError  # noqa: E402

import run  # noqa: E402

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
}

TITLES = ["Knowledge Graph", "Video Plan", "Video Transcript", "Avatar Clips",
          "Text Overlays", "Scenes Breakdown", "Image Gen Clips", "Video Gen Clips",
          "ShotStack"]


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
        expected = [run.LOCAL_SWAP.get(t, t) for t in TITLES if t not in run.LOCAL_SKIP]
        assert local == expected, local
        # ShotStack is replaced in place, not dropped, so the render stays last and the local
        # pipeline is only shorter by what LOCAL_SKIP drops.
        assert "ShotStack" not in local and local[-1] == "Local Render", local
        assert len(local) == len(TITLES) - len(run.LOCAL_SKIP), local
    finally:
        run.STORAGE = original
    # the dispatch map must answer to every title either mode schedules
    scheduled = set(TITLES) | set(run.LOCAL_SWAP.values())
    assert not scheduled - set(REAL_STAGES), scheduled - set(REAL_STAGES)
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
    check_failure_stops_lesson()
    print("\nAll orchestration checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
