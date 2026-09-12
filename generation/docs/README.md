# Docs

Everything the team needs to understand the video pipeline is in this folder.

## Start here

| doc | what it covers |
| --- | --- |
| [../README.md](../README.md) | How to run the pipeline. |
| [architecture/13-generation-layout.md](architecture/13-generation-layout.md) | The layout: what lives where, the two storage backends, and the check suite. |
| [../ops/README.md](../ops/README.md) | The human-driven tooling: what each tool does, and its status. |

## The stage set

Docs 00–12 are the deep reference: one per stage, plus the overview, the upstream prerequisites, the support layer and operator tooling. Read [00](architecture/00-overview.md) first for the shape of the thing; the rest stand alone.

| doc | covers |
| --- | --- |
| [00-overview.md](architecture/00-overview.md) | The pipeline's shape, the stage contract, the key scheme, every artifact path, and the load-bearing orderings |
| [01-upstream.md](architecture/01-upstream.md) | The three prerequisites a lesson run assumes exist: guidelines, lesson plan, content plan and metadata |
| [02-knowledge-graph.md](architecture/02-knowledge-graph.md) | Stage 1: the facts, read out of Google Sheets with no model involved |
| [03-video-plan.md](architecture/03-video-plan.md) | Stage 2: sections, concepts, teaching techniques, visuals, historical figures |
| [04-transcript.md](architecture/04-transcript.md) | Stage 3: the lesson as dialogue, plus its knowledge-check questions |
| [05-avatar-clips.md](architecture/05-avatar-clips.md) | Stage 4: voices, talking heads, and the word clock everything later times against |
| [06-text-overlays.md](architecture/06-text-overlays.md) | Stage 5: slides, diagrams and the conclusion, pinned to that clock |
| [07-scenes-breakdown.md](architecture/07-scenes-breakdown.md) | Stage 6: the transcript cut into timed clips around the overlay windows |
| [08-images.md](architecture/08-images.md) | Stage 7: one still per clip, generated or sourced, and the QC that picks it |
| [09-videos.md](architecture/09-videos.md) | Stage 8: motion from each chosen still. Skipped under `STORAGE=local` |
| [10-shotstack.md](architecture/10-shotstack.md) | Stage 9: the timeline assembled, rendered, split, subtitled and published. Under local mode `stages/local_render.py` reproduces its layer order |
| [11-support-layer.md](architecture/11-support-layer.md) | `core/`: storage, the model clients, cost, logging, notifications, and every environment variable |
| [12-operator-tooling.md](architecture/12-operator-tooling.md) | `ops/`: the reviewer, the `-edited.json` contract, repair and delivery, and what QC actually gates |
| [13-generation-layout.md](architecture/13-generation-layout.md) | The folder rules, the two storage backends, and the checks that enforce both |

## Conventions

Every doc in the set has the same spine, and a new one should too: a one-line statement of what the thing does, its **Contract** (what it reads, what it writes, what it may reach into), a **Flow** diagram where the control flow is not obvious, the **Design decisions** worth knowing, and **Seams** — the bugs, dead code and sharp edges a reader will otherwise rediscover the hard way. The Seams section is the one that earns the doc.


- **Code is anchored as `path/file.py::symbol`, never by line number.** Line numbers rot within days. Paths are relative to `generation/`.
- **When a doc and the code disagree, the code is truth and the doc is the bug.**
- `python docs/architecture/check_anchors.py` checks every anchor in the set and exits non-zero on any that no longer resolves. Run it after moving or renaming anything the docs name.
