# generation/

The lore video pipeline, self-contained. Eight stages turn each video of a run directory's
`lesson_plan.json` into a rendered, narrated MP4, and `run.py` is the only entry point.

Nothing here imports anything outside this folder. `tools/check_selfcontained.py` enforces
that, which is what makes the rest of the repository deletable.

## Where things are

| folder | what it holds |
| --- | --- |
| `stages/`, `core/`, `prompts/`, `config/` | the pipeline: what `run.py` runs |
| `templates/` | the HTML slides and diagrams, rendered by Playwright |
| `tools/` | the check suites, and the lore authoring and preview tools |
| `docs/` | the architecture set. Start at [docs/architecture/00-overview.md](docs/architecture/00-overview.md). |

New to this code, read [00](docs/architecture/00-overview.md) for the shape of the pipeline and
[13](docs/architecture/13-generation-layout.md) for the tree and the two storage backends.

## Running it

Two things have to exist outside pip: ffmpeg, which composites everything, and the shared
libraries headless Chromium needs. On a fresh Debian or Ubuntu machine:

```bash
sudo apt-get install -y ffmpeg libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libatspi2.0-0 libxcomposite1 libxdamage1 libgbm1
```

Then:

```bash
pip install -r requirements.txt
playwright install chromium          # the HTML slide and diagram renderer needs a browser
python run.py runs/world --list-stages
python run.py runs/world --dry-run
python run.py runs/world --video c01-v02
```

`runs/world` stands for any run directory: a local folder or `s3://bucket/prefix` that
already holds `lesson_plan.json`. Every artifact of the run is written back into it, one
folder per video named `c{chapter}-v{video}-{slug of the title}`, for example
`c01-v02-mansa-musa-s-gold/`. `tools/lore_video_plan.json`, `tools/history_reference_plan.json`
and `tools/science_video_plan.json` are plans in the right format; copy one in as
`lesson_plan.json`. The format is in [docs/lore_input_spec.md](docs/lore_input_spec.md) and
[01](docs/architecture/01-upstream.md).

Credentials come from `.env`, looked for in this folder first and then the repository root.
`run.py` loads it before importing anything else, because `core/constants.py` reads
`os.getenv` at module scope.

Useful flags:

| flag | effect |
| --- | --- |
| `--video FOLDER\|TITLE` | repeatable; a folder prefix such as `c01-v02` (or `c01` for a chapter), or an exact title. None means every video |
| `--video-type NAME` | which layers and stages run, from `config/video_types.json`, default `lore` |
| `--until STAGE` | stop after a stage instead of running the rest |
| `--force` | run a stage even where its JSON already exists |
| `--dry-run` | print the videos, their folders, and which artifacts already exist; touch nothing |
| `--workers N` | videos in parallel, default 3 |
| `--list-stages` | print the pipeline for the video type and storage, and exit |

`--dry-run` is worth using first every time: it lists every selected video's folder and
marks each stage's artifact `HAVE` or `MISS`, so you can see what a real run would actually
buy. It also prints the resolved storage, the video type and which layers it turns off.

## Storage

The run directory picks the backend; there is no separate flag. `s3://bucket/prefix` sets
`STORAGE=s3` and `S3_BUCKET=bucket`; a local path sets `STORAGE=local` and
`LOCAL_STORAGE_ROOT` to that folder, and needs no AWS credentials at all. Either overrides
the same keys in `.env`.

The switch happens once, at the bottom of `core/clients/s3.py`, which rebinds its own names
onto `core/clients/local_store.py`. Every module that does `from core.clients.s3 import ...`
picks it up untouched.

Local mode cannot run everything, because some vendors fetch an asset from a URL over the
internet and a folder cannot serve one:

- **Video Gen Clips** (Luma/Kling) is dropped from the pipeline by `LOCAL_SKIP`, because Luma
  and Kling need a URL per still and nothing downstream of them runs locally anyway.
- **D-ID** is skipped inside Avatar Clips, but the ElevenLabs half still runs. That matters:
  it produces the `lesson_timings` word-level clock that Text Overlays and Scenes Breakdown
  read.

Image QC survives because `create_presigned_url` returns a base64 `data:` URI, which
OpenAI's vision endpoint accepts. Asking it for audio or video raises rather than handing
back a URL that cannot work.

Notifications (SES and Google Chat) and CloudWatch logging are S3-mode only; a local run logs
to the console.

## Video types

A video type selects which *layers* of a video get built. All of them live in one file,
`config/video_types.json`, keyed by type name; each entry states only what it changes. Three
optional keys per type:

- `layers` — the `LAYER_*` flags (see `LAYER_DEFAULTS` in `run.py`), each `true` or `false`.
  A layer is a piece of a stage, so switching one off never changes the stage list.
- `skip_stages` — whole stages to drop, by their `config/stages.json` title.
- `params` — one object per stage that wants tuning, reaching the stage as `<name>_PARAMS`.

`lore` is the only type and the default: voiceover and imagery only, with no talking head,
no overlays of any kind, every image model-generated rather than web-sourced, and Video Gen
Clips skipped in favour of programmatic camera moves. Its `NARRATION` params block sets the
target length and speaking rate of the narration.

Two of the flags are not about overlays:

- `LAYER_WEB_IMAGES` (default on, off for lore) — off sends the map clips to the image model
  as well, so nothing in the video is web-sourced. It works by forcing
  `generate_image_wrapper`'s `type` override to FLUX, bypassing the `media.type == 'IMAGE'`
  branch that would otherwise search Google.
- `LAYER_PROGRAMMATIC_MOTION` (default off, on for lore) — gives every still a gentle ffmpeg
  camera move in the local renderer, as an alternative to the Kling/Luma AI motion that
  Video Gen Clips buys. One move per still, chosen from zoom in/out and pan
  left/right/up/down, seeded from the clip's media id so a re-render is identical rather
  than different every time. Its `params` block tunes the zoom range, the pan drift and how
  far off centre a zoom may sit. Animated stills are scaled to cover the frame rather than
  letterboxed, since panning a letterboxed still would drag its bars into view.

Unknown layer names, non-boolean values, unknown stage names and unknown keys are all rejected
with a message naming the offender, because a config that reads as configured but runs as
default would quietly buy a full set of vendor calls.

Avatar Clips and Text Overlays always run even when every layer they own is off, because they
also produce the voiceover audio and the word-level timing clock every later stage syncs
against. `lore` therefore still has narration; it just has nothing drawn over it.

Because the video type is not part of a video's folder, re-running one video under a
different type reuses the cached artifacts unless you pass `--force`.

## Rendering

`stages/local_render.py` is the last stage and the only renderer; it composites with ffmpeg
over local paths, so a run ends in a watchable MP4 with no bucket and no vendor account. It
refuses to run under S3 storage, where every asset would have to be downloaded first. The
MP4 lands in the video's `media/` folder, named after the video's title.

It reads its inputs through the same `Context` properties as every other stage, which is what
picks up the `-edited.json` sidecars, and it reads per-image metadata rather than the Image
Gen Clips aggregate because that is where a `human_choice` override lands. Bottom to top the
picture is stills, text slides, diagrams, conclusion, avatar.

The stills are the bottom layer and any cards are opaque and full-frame, so an image is
visible *between* overlay windows, not underneath them. Anything that fills the gaps in the
scene track must preserve their length, or every overlay after the first gap lands at the
wrong timestamp.

Only the stage's JSON is cached, never its media, so re-running a video whose
`Local Render.json` exists is a no-op. To re-render, delete that file from the video's folder
and run again; `--force` would redo every stage and re-buy every vendor asset.

`tools/render_lore_sample.py` renders a lore narration sample locally; `--check` checks the
wiring only, and without it the script calls ElevenLabs and fal.ai.

## Stage order matters

`config/stages.json` sets it, and the dependencies are real rather than conventional:

1. **Video Plan** — the plan's facts arranged into sections and concepts
2. **Video Transcript** — the single-host lore narration
3. **Avatar Clips** — narration audio (and talking-head video, off for lore); produces the word-level clock
4. **Text Overlays** — timed against that clock, so it cannot run earlier
5. **Scenes Breakdown** — carves clips around the overlay windows
6. **Image Gen Clips** — a still per clip
7. **Video Gen Clips** — motion, starting from the chosen still; skipped for lore
8. **Local Render** — ffmpeg composites the lot into one MP4

`run.py`'s `STAGES` dict is a lookup table, not a schedule. Adding an entry there does not
make it run; the config is what to edit.

## Skipping, and what it does not skip

A stage is skipped when its artifact already exists at `<run dir>/<video folder>/<stage>.json`,
and the cached JSON is returned instead.

Two things to know before relying on that:

- Only the canonical `<stage>.json` is tested, never a hand-written `<stage>-edited.json`
  sidecar, which downstream stages prefer when it exists. Deleting only the canonical file
  leaves a stale sidecar that downstream stages still read. To genuinely redo a stage,
  delete both.
- **Only JSON is skipped. Media is not.** Every mp3, mp4, mov and png below a stage that
  runs is regenerated and re-bought at full vendor cost.

## Which LLM runs

Every chat completion goes to the TrueFoundry gateway, which needs `TFY_API_KEY` and
`TFY_BASE_URL` in `.env`. `core/clients/openai.py::gateway_slug` resolves an `LLM` member to
a gateway slug and raises on a missing key or an unmapped model, so there is no
direct-to-vendor fallback to fall into. `GATEWAY_MODEL_SLUGS` is the whole catalogue:
`LLM.GPT_5` for the GPT calls, `LLM.CLAUDE_5_SONNET` for most transcript and QC work, and
`LLM.CLAUDE_5_OPUS` where a reasoning tier is wanted.

Claude models take the gateway's native Anthropic route, which wants the system prompt
separate from the messages; everything else takes the OpenAI-compatible route, vision
included. `temperature` is still accepted by `chat_complete` and `llm_complete` but is never
sent, and `max_tokens` reaches the Claude route only, because the reasoning models behind
the other slugs reject a temperature and count their own thinking against an output cap.

`OPENAI_API_KEY` is still needed, but only for DALL-E and `gpt-image-1`, which are not chat
and do not go through the gateway. Speech is ElevenLabs (`ELEVENLABS_API_KEY`), and FLUX
images are fal.ai (`FAL_KEY`). Gemini is separate: `core/clients/gemini.py` reads
`GEMINI_API_KEY` and talks to Google directly, for the Video Gen Clips QC only.

## The checks

All of these are offline and free. None needs credentials.

```bash
python tools/check_selfcontained.py       # nothing imports out of this folder
python tools/check_llm_gateway.py         # the gateway slugs, both vendor routes and the refusals
python tools/check_orchestration.py       # run.py against a fake run directory: order, skip, retry, selection
python tools/check_local_store.py         # the local backend, the rebinding and the stage skips
python tools/check_subject_profiles.py    # editorial prompt and profile contracts
python tools/check_lore_review.py         # lore editorial boundaries and workflow, no model calls
python tools/check_narration_pauses.py    # narration pause safety and tiers
python -m stages.local_render             # the compositing geometry, camera motion and scene-gap filling
python docs/architecture/check_anchors.py # every code anchor in the docs resolves
```

Two dependencies live outside pip and outside this list: ffmpeg and headless Chromium. Both
are named at the top of this file, and both fail loudly rather than silently.

## Known traps

Live bugs, not surprises. Each is here because it costs an afternoon to rediscover.

- `stages/text_overlays.py::slides_timings_identifier` and `::identify_diagram_timings` call
  `input("Check Timings")`. They are off unless `REVIEW_TIMINGS` is set, because they run
  inside a worker pool and raced each other over one fixed file. Set it and a
  non-interactive run blocks on stdin forever.
- `stages/video_clips.py::generate_ai_video_with_qc` returns before its QC branch, so the
  Gemini verdict is discarded whenever Video Gen Clips runs.
- Video folders follow plan order. Inserting a video or chapter above an existing one
  renumbers the folders after it, and those videos regenerate from scratch.
