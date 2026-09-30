# Docs

Everything the team needs to understand the lore video pipeline is in this folder.

## Start here

| doc | what it covers |
| --- | --- |
| [../README.md](../README.md) | How to run the pipeline. |
| [architecture/13-generation-layout.md](architecture/13-generation-layout.md) | The layout: what lives where, the two storage backends, and the check suite. |
| [lore_input_spec.md](lore_input_spec.md) | The `lesson_plan.json` format and the quality bar its research must clear before generation is worth running. |
| [info/lore_editorial_pipeline.md](info/lore_editorial_pipeline.md) | How the transcript stage plans, hooks, drafts, reviews and repairs the narration. |
| [info/subject_onboarding.md](info/subject_onboarding.md) | What to specify to add a subject, and what each profile field controls. |
| [hook_dataset/2026-09-24/README.md](hook_dataset/2026-09-24/README.md) | 45 attributed hook passages, derived guidelines, and two fresh six-topic experiments. |

## The stage set

Docs 00–13 are the deep reference: one per stage, plus the overview, the pipeline input, the support layer and the layout. Read [00](architecture/00-overview.md) first for the shape of the thing; the rest stand alone.

| doc | covers |
| --- | --- |
| [00-overview.md](architecture/00-overview.md) | The pipeline's shape, the stage contract, the folder scheme, every artifact path, and the load-bearing orderings |
| [01-upstream.md](architecture/01-upstream.md) | The run directory, the `lesson_plan.json` format, storage selection, folder naming and video selection |
| [03-video-plan.md](architecture/03-video-plan.md) | Stage 1: the plan's facts arranged into sections, concepts and teaching techniques |
| [04-transcript.md](architecture/04-transcript.md) | Stage 2: the video as single-host lore narration |
| [05-avatar-clips.md](architecture/05-avatar-clips.md) | Stage 3: the voice, the talking head, and the word clock everything later times against |
| [06-text-overlays.md](architecture/06-text-overlays.md) | Stage 4: slides, diagrams and the conclusion, pinned to that clock |
| [07-scenes-breakdown.md](architecture/07-scenes-breakdown.md) | Stage 5: the transcript cut into timed clips around the overlay windows |
| [08-images.md](architecture/08-images.md) | Stage 6: one still per clip, generated or sourced, and the QC that picks it |
| [09-videos.md](architecture/09-videos.md) | Stage 7: motion from each chosen still. Skipped for lore and under `STORAGE=local` |
| [10-render.md](architecture/10-render.md) | Stage 8: every artifact composited into one MP4 with ffmpeg by `stages/local_render.py` |
| [11-support-layer.md](architecture/11-support-layer.md) | `core/`: storage, the model clients, logging, notifications, and every environment variable |
| [13-generation-layout.md](architecture/13-generation-layout.md) | The folder rules, the two storage backends, and the checks that enforce both |

## Conventions

Every doc in the set has the same spine, and a new one should too: a one-line statement of what the thing does, its **Contract** (what it reads, what it writes, what it may reach into), a **Flow** diagram where the control flow is not obvious, the **Design decisions** worth knowing, and **Seams** — the bugs, dead code and sharp edges a reader will otherwise rediscover the hard way. The Seams section is the one that earns the doc.


- **Code is anchored as `path/file.py::symbol`, never by line number.** Line numbers rot within days. Paths are relative to `generation/`.
- **When a doc and the code disagree, the code is truth and the doc is the bug.**
- `python docs/architecture/check_anchors.py` checks every anchor in the set and exits non-zero on any that no longer resolves. Run it after moving or renaming anything the docs name.
