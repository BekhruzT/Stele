# 13 — Layout

> Not a stage ([00](00-overview.md)). This is the shape of the tree: what lives where, the rules that keep it that way, the two storage backends, and the checks that enforce both.

`generation/` contains everything needed to turn a course lesson plan into a finished MP4, and nothing else.

- **Self-contained is a checked property, not an intention.**
  - `tools/check_selfcontained.py` parses every `.py` here and fails on three things: an import that resolves outside `generation/` (`LEAK`), a third-party import `requirements.txt` does not ask for (`UNDECLARED`), and an internal import with no file behind it (`MISSING`).
  - It reads source rather than importing it, so it runs with no dependencies installed and no credentials.
  - Adding a dependency means adding it to `requirements.txt` in the same commit, or this check goes red.

## The two layers

Everything here is either **pipeline** or **ops**, and the split is about who starts it.

| | pipeline | ops |
| --- | --- | --- |
| Started by | `run.py`, unattended | a person, one lesson at a time |
| Lives in | `stages/`, `core/`, `prompts/`, `config/` | `ops/` |
| Scheduled by | `config/stages.json` | nothing |
| Verified | six check suites, and a full local run | not verified; see `ops/README.md` |

- **The pipeline layer is the nine stages and what they lean on.**
  - `run.py::STAGES` maps a config title to a callable. It is a lookup table and its order means nothing.
  - `config/stages.json` under `content.subsection` is the running order. Adding a stage means adding a config entry and a map entry; nothing else knows the list exists.
  - `config/video_types.json` holds every video type in one file. `run.py::video_type` validates one entry and returns its `LAYER_*` flags, merged over `LAYER_DEFAULTS` and threaded into every stage's `inputs`, plus the `skip_stages` set `pipeline()` filters the running order by. A layer is a piece of a stage; `skip_stages` is the only way a type drops a whole one.
  - `run.py::run_stage` is the only place skip and retry live. It tests the canonical `{key}.json` only, never the `-edited.json` sidecar. The video type is not in `{key}`, so switching type on the same lesson needs `--force`.
- **The ops layer is everything a human does around a lesson.**
  - Review, the SME feedback loop, repair, course authoring, delivery, presenter setup.
  - Nothing under `ops/` is imported by any stage, and nothing in it is wired into `run.py`. Deleting the whole folder would not change what a run produces.
  - It is grouped by capability rather than by the vendor each tool talks to, because the question asked of that folder is always "how do I fix a bad lesson", never "what calls Google Sheets".

## Folder map

    generation/
      run.py              the only entry point; CLI, lesson selection, stage ordering
      config/             courses.py (execution inputs), stages.json (the running order)
      stages/             the nine stages plus local_render, one file each
      core/               everything the stages share
        clients/          one module per external service, plus local_store for STORAGE=local
        media/            asset manufacture: clip timings, html_to_video, subtitles, thumbnails
      prompts/            every LLM prompt, by stage
      templates/          the Jinja HTML rendered into slides and diagrams
      ops/                human-driven tooling, not wired into the pipeline
      tools/              the check suites
      docs/               this set

## Storage, and the two ways local mode differs

`STORAGE` selects the artifact backend, by `--storage` or the environment.

- **`core/clients/s3.py` is the single choke point.**
  - Under `STORAGE=local` the module rebinds its own functions onto `core/clients/local_store.py` at import time, so every caller keeps working unchanged. `core/clients/s3.py::is_local` reports which backend won.
  - `core/clients/local_store.py::path_for` percent-encodes the characters Windows forbids in a path, which is why the on-disk folder names contain `%3A` where the S3 key had a colon.
- **`run.py::LOCAL_SKIP` drops a stage from the local pipeline.**
  - A vendor that must *fetch a URL* cannot work against a local folder, but compositing was never the part that needed a vendor.
  - `LOCAL_SKIP` holds Video Gen Clips only. Luma and Kling need a public URL per still, and nothing downstream of them runs locally.
    - D-ID is the third URL-fetching vendor, but it is one block inside a stage rather than a stage, so it is skipped in place by `stages/avatar_clips.py` and the ElevenLabs audio around it still runs.
- **`stages/local_render.py` is the only renderer ([10](10-render.md)).**
  - It composites with ffmpeg over local paths, bottom to top: stills, then text slides, diagrams, conclusion, avatar.
  - `stages/local_render.py::place` converts an overlay manifest's placement to ffmpeg overlay arguments. The two disagree twice: the manifests size as a fraction of the output and position by an asset's centre with +y up, ffmpeg takes pixels and positions by the top-left corner with +y down.
  - `stages/local_render.py::scene_segments` fills the gaps in the scene track. The stills are the bottom layer and the cards are opaque and full-frame, so a still shows *between* card windows; anything filling those gaps has to preserve their length or every later overlay lands at the wrong timestamp.
  - It writes the MP4 to the lesson's media path and returns a `lesson_video` block carrying `src`, the duration and the asset counts.

## The one input the pipeline cannot make

- **`lesson_plan.json` is read and never written.**
  - `run.py::load_plan` reads it per course; `core/lesson_plan.py` holds only readers.
  - Under `STORAGE=local` a missing plan exits with the exact path to copy it to, rather than a bare file-not-found out of `json`.
  - Its producer is `ops/authoring/lesson_plan.py`, which is why that file is worth keeping even though nothing calls it.
- **`content_plan` and `lesson_metadata` look required and are not.**
  - `core/context.py` exposes `content_plan_path` and `metadata_path` for them, and nothing on any stage path calls either property.
  - A full local run produces a finished lesson with neither artifact present. Their producer is `ops/authoring/metadata.py`, kept for the same reason.

## Checks

Run all of these from `generation/`. Together they are what a change to this tree has to survive.

```bash
python tools/check_selfcontained.py       # no imports escape generation/
python tools/check_orchestration.py       # stage order, skip, retry, failure isolation
python tools/check_local_store.py         # the local backend and the local stage list
python -m stages.local_render             # layer geometry and scene-gap filling
python docs/architecture/check_anchors.py # every code anchor in these docs resolves
```

- **`docs/architecture/check_anchors.py` is what keeps this doc set honest.** It reads every `path/file.py::symbol` anchor in `docs/architecture/`, resolves the file, and parses it for the symbol. Renaming a function without updating the docs that name it turns the check red in the same commit.

## Rules that are not obvious from the folder names

- **A stage imports from `core/` and from `prompts/`. Nothing else.** No stage imports another stage, and no stage imports `ops/`. `run.py` is the only module that imports `stages/`.
- **`ops/` is grouped by capability, not by vendor.** The question asked of that folder is always "how do I fix a bad lesson", never "what calls Google Sheets".
- **Names say what a thing is for, not how it was built.** `core/media/media_assets.py`, not `media_asset_utils.py`; `ops/delivery/stele.py`, not `upload_to_stele.py`.
- **Windows is a supported development platform.** `core/media/html_to_video.py` uses `tempfile.gettempdir()` rather than a hardcoded `/tmp`, writes its scratch page inside `templates/` so relative asset links resolve, and reads and writes pages as UTF-8 because the slide text is model output and can contain anything.
- **Nothing constructs an AWS client at import time.** `core/clients/did.py` builds its boto3 client lazily, so importing `stages/avatar_clips.py` under `STORAGE=local` needs no AWS configuration at all.
