# ops/ — the tooling around the pipeline

Everything here is started by a person, one lesson or one course at a time. Nothing here is imported by a stage, and nothing is wired into `run.py`: delete this whole folder and a run still produces the same video.

Grouped by capability rather than by the vendor each tool talks to, because the question asked of this folder is always "how do I fix a bad lesson", never "what calls Google Sheets".

## Status: read this first

**None of this is verified at runtime.** The nine stages and the local renderer have been run end to end against a real lesson. These files have not.

What is checked:

- Imports resolve. `tools/check_selfcontained.py` covers this folder, so every `core.*`, `stages.*` and `prompts.*` import here points at a real module, and every third-party import is in `requirements.txt`.
- They parse. That check ASTs every file.

What is not: **anything that needs a network or a credential.** Expect stale spreadsheet IDs, hardcoded course versions in `__main__` blocks, and absolute paths from a Linux container. Two patterns to check before running anything:

- **Hardcoded execution inputs.** Several `__main__` blocks pin a specific subject and subsection, often an older course version than you want.
- **Google credentials.** `ops/media/character_bundle.py` reads `GOOGLE_SERVICE_ACCOUNT_FILE`, defaulting to `service-account.json` in the working directory.

## What is here

### `review/` — a human looking at a finished lesson

| file | what it does |
| --- | --- |
| `app.py` | The seven-layer Streamlit review wizard. Walks content plan, transcript, overlays, clips, images, videos and the composite; regenerates any of them on demand. |
| `mcq_app.py` | Read-only browser for the knowledge-check questions embedded in the transcript artifact. |

`app.py` is the single most valuable file in this folder, because it is the only writer of the two correction mechanisms the pipeline already honours:

- **A correction is a sidecar, never an in-place edit.** The reviewer writes `{key}-edited.json` beside the canonical `{key}.json`, and the `core/context.py` path properties prefer the sidecar when it exists. So a downstream stage picks up the correction with no coordination.
- **Images use a different mechanism.** There is no sidecar; the reviewer writes `human_choice` into the per-clip metadata under `media/{key}/images/`, which `stages/local_render.py` and `stages/shotstack.py` read in preference to `qc_choice`.
- **Only the canonical file is tested when deciding to skip.** So an edited sidecar does not stop its own stage regenerating, and deleting only the canonical file leaves a stale sidecar that downstream stages still prefer. To genuinely redo an edited stage, delete both.

`app.py` imports `generate_lesson_transcript` from `stages/transcript.py`, the same function the pipeline runs, so the regenerate button and a pipeline run produce the same shape. Keep it that way: a reviewer writing a transcript in a shape the later stages do not expect corrupts everything below it, silently.

Two of the seven layers cannot save. Overlay edits and video choices are displayed, accepted in the UI, and discarded.

### `feedback/` — reviewer corrections coming back in

| file | what it does |
| --- | --- |
| `curate_metadata.py` | Reads sheet edits *and* in-cell comments, classifies what changed, versions key concepts and phrases, writes back. |
| `curate_transcripts.py` | Puts transcripts into Google Docs for review and drives the curation pass. |
| `sme_comments.py` | LLM-categorises reviewer comments and writes them into the context pack as notes, so the next generation does not repeat the mistake. |
| `key_phrases.py` | Analyses key phrases and objectives across lessons. |
| `append_to_context.py` | Appends a feedback item to a lesson's context pack. |
| `dump_context_packs.py` | Exports context packs and their feedback to CSV. |

### `repair/` — changing part of a finished lesson

| file | what it does |
| --- | --- |
| `regenerate_concept.py` | Regenerates one concept inside a finished lesson: classifies the change, redoes that transcript slice, its MCQs and its avatar audio, re-stitches timings. |
| `regenerate_concept_prompts.py` | The prompts that drives the above. |
| `text_slides.py` | Post-hoc QC and repair of text slides and diagrams: length checks, timing re-match, diagram fixes. |
| `delete_lesson.py` | Deletes every artifact and media file for one lesson key. |

`regenerate_concept.py` is the one to reach for after `app.py`, and the reason is cost: a stage that runs regenerates and re-buys **all** of its media, because only JSON is cached. Fixing one concept by re-running the lesson pays ElevenLabs, FLUX and the LLMs for the whole thing.

`delete_lesson.py` is the clean way to force a rerun, given the sidecar rule above.

### `authoring/` — everything upstream of the pipeline

| file | what it does |
| --- | --- |
| `lesson_plan.py` | Builds `lesson_plan.json` for a course. **The only producer of the one input the pipeline cannot make.** |
| `content_plan.py` | Builds the per-lesson content plan. |
| `metadata.py` | Builds `lesson_metadata`. |
| `blacklist_los.py` | Embedding-clusters learning objectives and blacklists near-duplicates, before you pay to generate the duplicate lesson. |

### `quality/` — judging the result

| file | what it does |
| --- | --- |
| `chapter_reviewer.py` | Reviews every lesson in a chapter together and can apply changes. The only thing that sees more than one lesson; every stage sees exactly one subsection. |
| `questions.py` | MCQ lifecycle: QC, filtering, option shuffling, re-timing the question overlays, stats. |
| `time_stats.py` | Per-stage timing and duration statistics across lessons. |

### `delivery/` — getting a lesson to its audience

| file | what it does |
| --- | --- |
| `stele.py` | Pushes lessons, video parts and questions into Stele. Uses the two `standard_mapping_*.csv` beside it for standards alignment. |
| `delivery_sheet.py` | Fills the delivery tracking sheet, thumbnails, and diagram last-frames. |
| `track_folders.py` | Maintains the folder tracking sheet. |

### `media/` — presenter and voice, which are per-course choices

| file | what it does |
| --- | --- |
| `characters.py` | Publishes edited characters and updates voices. |
| `character_bundle.py` | Downloads character bundles from Google Drive. |

## Things that live outside this folder on purpose

- **Subtitles are in `core/media/subtitles.py`, not here.** They make an asset out of the word timings the pipeline already produces, so they belong with the other media producers. `core/clients/speech.py::create_subtitles_file` is the `.srt` writer it calls; wiring subtitles into the pipeline is mostly a matter of calling it per section.
- **Thumbnails, the lesson report, post-evaluations, content analysis and cost tracking** are in `core/` — `core/media/thumbnails.py`, `core/media/lesson_report.py`, `core/post_evaluations.py`, `core/content_analysis.py`, `core/pricing.py`. Nothing calls most of them. Capabilities you own but are not using.

## Dependencies

The pipeline needs none of this. `streamlit` and `PyDrive2` in `requirements.txt` exist only for `review/` and `media/`; install without them and `run.py` still builds a video.

Run the Streamlit apps by path, from `generation/`:

```bash
streamlit run ops/review/app.py
```
