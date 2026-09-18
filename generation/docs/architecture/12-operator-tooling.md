# 12 — Operator tooling

> Not a stage ([00](00-overview.md)). This is everything a human uses around the pipeline: the review app that corrects a lesson, the scripts that repair and publish one, and the evaluation machinery that judges the result without blocking it.

## What it does

Gives a subject-matter expert a way to inspect each stage's output, correct it, force the affected stages to regenerate, and then deliver the finished lesson — plus a shelf of batch scripts for the things the pipeline does not do for itself.

## The edit contract

- **A correction is a sidecar, never an in-place edit.**
  - The reviewer writes `{key}-edited.json` alongside the canonical `{key}.json`.
  - Six `APVideoContext` properties prefer the sidecar when it exists: `content_plan_path`, `video_plan_path`, `transcripts_path`, `clips_path`, `avatar_assets_path`, `text_overlays_path`.
  - So a downstream stage picks up the correction with no coordination, and the original generation is preserved for comparison.
- **`run.py::run_stage` does not know about sidecars.**
  - It tests only the canonical `{key}.json` when deciding to skip.
  - The consequences, both silent:
    - An edited sidecar does not stop its own stage regenerating. Delete the canonical file and the stage runs again, and its new output will still be shadowed by the stale sidecar.
    - Deleting only the canonical file to force a rerun leaves the sidecar in place, so every downstream stage keeps reading the old edit.
  - To genuinely redo an edited stage, delete both files.
- **Images and videos use a different mechanism.**
  - There is no sidecar. The reviewer writes `human_choice` into the per-clip metadata under `media/{key}/`, which [09](09-videos.md) and [10](10-render.md) read in preference to `qc_choice`.

## The reviewer: `ops/review/app.py`

- **A linear seven-layer wizard, not a set of tabs.**
  - `::render_landing_page` builds the unit, chapter, section and subsection picker from `::get_topics_list`; starting a lesson runs the pipeline for one subsection.
  - Each layer shows one stage's output, allows edits, and can generate the artifact on demand when S3 does not have it, by calling the same `stages/` functions the pipeline calls.
  - An auto-next toggle walks the layers in order.

| Layer | Reviews | Writes |
| --- | --- | --- |
| `InputValidationLayer` | the content plan and context pack | `content_plan/{key}-edited.json`, `context_pack/{key}.json` |
| `TranscriptValidationLayer` | per-concept concept, question, explanation and recap | `Video Transcript/{key}-edited.json` |
| `OverlayValidationLayer` | the tagged transcript, titles, topics, key phrases, conclusion | nothing — `process` is a `pass` with a TODO |
| `ClipsValidationLayer` | clip snippets and image and video prompts | `Scenes Breakdown/{key}-edited.json` |
| `ImagesValidationLayer` | image candidates, with regenerate and upload | per-clip metadata under `media/{key}/images/` |
| `VideoValidationLayer` | generated videos | nothing — `process` is a no-op |
| `LocalRenderLayer` | the finished composite | `Local Render/{key}.json` if absent |

- **Each layer is wrapped in `core/log.py::with_logging_context`** with its own `LayerName`, and `ImagesValidationLayer` uses `::ContextAwareThreadPoolExecutor` so its parallel QC keeps the lesson id ([11](11-support-layer.md)).
- **Two of the seven layers cannot save.**
  - Overlay edits and video choices are displayed, accepted in the UI, and discarded.
  - This is why no `Text Overlays/{key}-edited.json` appears in practice, and why [09](09-videos.md)'s `human_choice` is effectively always the default.
- **`TranscriptValidationLayer` imports `generate_lesson_transcript` from `stages/transcript.py`**, the same function the pipeline runs, so the regenerate button and a pipeline run produce the same shape ([04](04-transcript.md)). Anything else here is a bug: an edited transcript that did not match what [05](05-avatar-clips.md) and [06](06-text-overlays.md) expect would corrupt every stage below it, silently.
- **`ops/review/app.py`'s `__main__` block pins its execution input** to `AP World History: Video Lessons 2` and `AP World History - v0`.

## `ops/review/mcq_app.py`

A Streamlit app for reviewing the knowledge-check questions. It reads the MCQs already embedded in the transcript artifact, via `APVideoContext.transcripts_path`, and neither writes back nor gates anything.

## The repair workflow

- **`ops/repair/regenerate_concept.py` is the real edit loop, and the only script that re-enters the pipeline properly.**
  - It regenerates one concept end to end: transcript, then audio, then overlays, then clips, then the render, with human approval gates between.
  - This is what a subject-matter expert uses after finding a bad concept, rather than deleting artifacts by hand.
  - Its prompts live in `ops/repair/regenerate_concept_prompts.py`.
- **`ops/repair/delete_lesson.py` is the blunt version**: it deletes a lesson's artifacts outright. Destructive, and the fastest way to lose a lesson's paid media.
- **`ops/repair/text_slides.py` repairs overlays in place.**
  - Finds text slides over roughly 517 characters, has a model shorten them, re-derives their timings, re-renders them, writes the manifest back, and deletes the render artifact so the lesson re-composes ([06](06-text-overlays.md)).
- **`ops/quality/questions.py`** shuffles, QCs and filters MCQs and updates their overlay timings, with an optional fix mode.

## Delivery

- **`ops/delivery/delivery_sheet.py`** fills empty cells in the delivery sheet with the video and resource links from each lesson's render artifact. It reads `lesson_video.output_data`, which ffmpeg does not emit, so it only ever worked against the removed hosted renderer.
- **`ops/delivery/stele.py`** takes completed delivery-sheet rows and uploads them to the Stele learning platform, keyed by the `DomainId`, `ClusterId` and `StandardId` carried down from [01](01-upstream.md).
- **`core/media/thumbnails.py`** and **`core/media/subtitles.py`** batch-produce assets that [10](10-render.md) now makes inline, for lessons rendered before it did.
- **`ops/delivery/track_folders.py`** maintains a Google Sheet matrix of which pipeline layers exist for which lesson, which is the closest thing the project has to a run dashboard.

## Evaluation

- **In-pipeline QC gates regeneration, not publication.**
  - The `core/helpers.py::qc_llm_call` loops inside [03](03-video-plan.md), [04](04-transcript.md) and [06](06-text-overlays.md) either fix once and continue, or accept.
  - [08](08-images.md)'s image QC does drive a real retry with a rewritten prompt, and is the only QC in the pipeline that changes what gets bought.
  - [09](09-videos.md)'s video QC runs and its verdict is discarded.
  - Nothing anywhere refuses to publish a lesson.
- **Post-hoc evaluation is advisory and lands in spreadsheets.**
  - `core/post_evaluations.py::orchestrator` batch-evaluates transcript quality and word overuse and dumps results to a sheet.
  - `core/media/lesson_report.py::get_lesson_report` produces a composite per-lesson QC report: coverage, slide length and similar.
  - `core/content_analysis.py` looks for repetition across a transcript.
  - `ops/feedback/key_phrases.py` and `ops/feedback/sme_comments.py` are embedding-based analyses across lessons.
  - `ops/quality/chapter_reviewer.py` reviews a chapter's metadata for consistency across lessons.

## Curation and analysis

| Script | Purpose |
| --- | --- |
| `ops/feedback/curate_metadata.py` | metadata curation driven by subject-matter-expert sheet comments |
| `ops/feedback/curate_transcripts.py` | processes lessons past a cutoff date for sheet curation |
| `ops/quality/chapter_reviewer.py` | chapter-wide metadata review with embeddings; called by `APVideosContentPlanner.aggregate_content_plan` ([01](01-upstream.md)) |
| `ops/media/characters.py` | edits the avatar character bundles |
| `ops/media/character_bundle.py` | pulls the character bundle from Drive and uploads it to S3 |
| `ops/authoring/blacklist_los.py` | identifies learning objectives to exclude, via sheet plus embeddings |
| `ops/quality/time_stats.py` | timing statistics from the transcript, avatar and overlay artifacts |
| `ops/feedback/dump_context_packs.py` | exports context packs |
| `ops/repair/delete_lesson.py` | one-off cleanup against a hardcoded v1 bucket and prefix |
| `ops/feedback/append_to_context.py` | appends corrections into a lesson's context pack |

There is no script for turning a `{key}` hash back into a subsection title. `core/path.py::get_key` and `core/hash.py::hash_code` are the whole derivation, and it runs one way ([11](11-support-layer.md)).

## Seams

- **Hardcoded spreadsheet and folder ids** are spread across `core/post_evaluations.py`, `core/media/media_assets.py`, `ops/delivery/track_folders.py` and `ops/delivery/delivery_sheet.py`. None is configuration.
- **`ops/feedback/sme_comments.py` filters on a named individual.**
- **`ops/repair/delete_lesson.py` hardcodes the `gen-ai-textbooks-dev` bucket**, matching the defaults in `core/clients/s3.py` ([11](11-support-layer.md)).
- **`ops/authoring/blacklist_los.py` imports `langchain`**, which nothing else here does, so it carries the only dependency in `ops/` that a pipeline run does not need.
- **`core/clients/openai.py::log_llm_message` writes `./prompts.txt` in the working directory**, so running any of these scripts from a shared machine leaves a plaintext prompt log behind ([11](11-support-layer.md)).
