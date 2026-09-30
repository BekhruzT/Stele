# 13 — Layout

> Not a stage ([00](00-overview.md)). This is the shape of the tree: what lives where, the rules that keep it that way, the two storage backends, and the checks that enforce both.

`generation/` contains everything needed to turn a run directory's `lesson_plan.json` into finished MP4s, and nothing else.

- **Self-contained is a checked property, not an intention.**
  - `tools/check_selfcontained.py` parses every `.py` here and fails on three things: an import that resolves outside `generation/` (`LEAK`), a third-party import `requirements.txt` does not ask for (`UNDECLARED`), and an internal import with no file behind it (`MISSING`).
  - It reads source rather than importing it, so it runs with no dependencies installed and no credentials.
  - Adding a dependency means adding it to `requirements.txt` in the same commit, or this check goes red.

## The pipeline layer

Everything under `stages/`, `core/`, `prompts/` and `config/` is started by `run.py`, unattended, and scheduled by `config/stages.json`. `tools/` holds the checks and the lore authoring tools, which are run by hand.

- **The pipeline is the eight stages and what they lean on.**
  - `run.py::STAGES` maps a config title to a callable. It is a lookup table and its order means nothing.
  - `config/stages.json` under `stages` is the running order. Adding a stage means adding a config entry and a map entry; nothing else knows the list exists.
  - `config/video_types.json` holds every video type in one file; `lore` is the only one. `run.py::video_type` validates one entry and returns its `LAYER_*` flags, merged over `LAYER_DEFAULTS` and threaded into every stage's `inputs`, plus the `skip_stages` set `pipeline()` filters the running order by and the `params` blocks each stage receives as `<NAME>_PARAMS`. A layer is a piece of a stage; `skip_stages` is the only way a type drops a whole one.
  - `run.py::run_stage` is the only place skip and retry live. It tests the canonical `{stage}.json` only, never the `-edited.json` sidecar. The video type is not in the folder name, so switching type on the same video needs `--force`.
  - `config/subject_profiles.py` holds the `history` and `science` profiles; `resolve_profile` turns the plan's `_meta` into one ([01](01-upstream.md)).

## Folder map

    generation/
      run.py              the only entry point; CLI, storage selection, video selection, stage ordering
      config/             stages.json (the running order), video_types.json (lore), subject_profiles.py
      stages/             the eight stages, one file each
      core/               everything the stages share, including the lore editorial pipeline
        clients/          one module per external service, plus local_store for STORAGE=local
        media/            asset manufacture: clip_timings, html_to_video, media_assets
      prompts/            every model-facing string, by stage; images/ for the image client
      templates/          the Jinja HTML rendered into slides and diagrams
      tools/              the check suites, and the lore authoring and preview tools
      docs/               this set, the lore input spec, info/, and the golden_references/ and hook_dataset/ corpora

## Storage, and the two ways local mode differs

`STORAGE` selects the artifact backend. `run.py::storage_for` sets it from the run directory: `s3://...` is `s3`, a local path is `local` ([01](01-upstream.md)).

- **`core/clients/s3.py` is the single choke point.**
  - Under `STORAGE=local` the module rebinds its own functions onto `core/clients/local_store.py` at import time, so every caller keeps working unchanged. `core/clients/s3.py::is_local` reports which backend won.
  - `core/clients/local_store.py::path_for` maps a key onto a path below `LOCAL_STORAGE_ROOT`, percent-encoding the characters Windows forbids in a path.
- **`run.py::LOCAL_SKIP` drops a stage from the local pipeline.**
  - A vendor that must *fetch a URL* cannot work against a local folder, but compositing was never the part that needed a vendor.
  - `LOCAL_SKIP` holds Video Gen Clips only. Luma and Kling need a public URL per still, and nothing downstream of them runs locally. The `lore` type skips it anyway.
    - D-ID is the third URL-fetching vendor, but it is one block inside a stage rather than a stage, so it is skipped in place by `stages/avatar_clips.py` and the ElevenLabs audio around it still runs.
- **`stages/local_render.py` is the only renderer ([10](10-render.md)).**
  - It refuses to run unless `STORAGE=local`, and composites with ffmpeg over local paths, bottom to top: stills, then text slides, diagrams, conclusion, avatar.
  - `stages/local_render.py::place` converts an overlay manifest's placement to ffmpeg overlay arguments. The two disagree twice: the manifests size as a fraction of the output and position by an asset's centre with +y up, ffmpeg takes pixels and positions by the top-left corner with +y down.
  - `stages/local_render.py::scene_segments` fills the gaps in the scene track. The stills are the bottom layer and the cards are opaque and full-frame, so a still shows *between* card windows; anything filling those gaps has to preserve their length or every later overlay lands at the wrong timestamp.
  - It writes the MP4 to the video's media path and returns a `lesson_video` block carrying `src`, the duration and the asset counts.

## The one input the pipeline cannot make

- **`lesson_plan.json` is read and never written.**
  - `run.py::load_plan` reads it from the run directory and exits naming the directory when it is missing.
  - `tools/lore_video_plan.json`, `tools/history_reference_plan.json` and `tools/science_video_plan.json` are plans in the same format; copy one into a run directory as `lesson_plan.json` to start a run.

## Checks

Run all of these from `generation/`. Together they are what a change to this tree has to survive.

```bash
python tools/check_selfcontained.py       # no imports escape generation/
python tools/check_llm_gateway.py         # gateway slugs, both vendor routes, the refusals
python tools/check_orchestration.py       # run.py against a fake run directory: order, skip, retry, selection, failure isolation
python tools/check_local_store.py         # the local backend and the local stage list
python tools/check_subject_profiles.py    # editorial prompt and profile contracts
python tools/check_lore_review.py         # lore editorial boundaries and workflow, no model calls
python tools/check_narration_pauses.py    # narration pause safety and tiers
python -m stages.local_render             # layer geometry, camera motion and scene-gap filling
python docs/architecture/check_anchors.py # every code anchor in these docs resolves
```

Two diagnostics take input rather than pass or fail: `tools/check_lore_plan.py` recomputes `estimated_concepts` and flags near-duplicate beats in a plan, and `tools/check_lore_style.py <transcript.txt> <reference.txt>` compares a transcript's AI tells and flow metrics against a reference.

- **`docs/architecture/check_anchors.py` is what keeps this doc set honest.** It reads every `path/file.py::symbol` anchor in `docs/architecture/`, resolves the file, and parses it for the symbol. Renaming a function without updating the docs that name it turns the check red in the same commit.

## Rules that are not obvious from the folder names

- **A stage imports from `core/`, `prompts/` and `config/`.** The one stage-to-stage import is `stages/video_clips.py` reusing `stages/image_clips.py::generate_image_wrapper`. `run.py` is the only non-tool module that imports `stages/`.
- **Every model-facing string lives in `prompts/`.** Stage and core modules only import them.
- **Names say what a thing is for, not how it was built.** `core/media/media_assets.py`, not `media_asset_utils.py`.
- **Windows is a supported development platform.** `core/media/html_to_video.py` uses `tempfile.gettempdir()` rather than a hardcoded `/tmp`, writes its scratch page inside `templates/` so relative asset links resolve, and reads and writes pages as UTF-8 because the slide text is model output and can contain anything.
- **Nothing constructs an AWS client at import time.** `core/clients/did.py` builds its boto3 client lazily, so importing `stages/avatar_clips.py` under `STORAGE=local` needs no AWS configuration at all.
