# generation/

The video pipeline, self-contained. Nine stages turn one subsection of a course lesson plan
into a rendered video, and `run.py` is the only entry point.

> **`lore` is the supported video type.** The AP exam-prep types, `history` and `general`, are
> marked `"unsupported": true` in `config/video_types.json` and refused unless you pass
> `--allow-unsupported`. Their stages, layers and ops tooling are all still wired, but the
> prompts, models and pacing were retuned for sleep-lore narration and nobody checks the AP
> output any more. Expect it to run and to produce something nobody has reviewed.

Nothing here imports anything outside this folder. `tools/check_selfcontained.py` enforces
that, which is what makes the rest of the repository deletable.

## Where things are

| folder | what it holds |
| --- | --- |
| `stages/`, `core/`, `prompts/`, `config/` | the pipeline: what `run.py` runs |
| `ops/` | human-driven tooling — review, feedback, repair, authoring, delivery. Not wired into `run.py`, and not verified. See [ops/README.md](ops/README.md). |
| `tools/` | the check suites, and the lore authoring and preview tools |
| `docs/` | the architecture set. Start at [docs/architecture/13-generation-layout.md](docs/architecture/13-generation-layout.md). |

New to this code, read [13](docs/architecture/13-generation-layout.md) first: it maps this tree,
explains the pipeline/ops split, and covers the two storage backends.

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
python run.py --list-stages
python run.py --subsection "Taxation Without Representation" --dry-run
```

Credentials come from `.env`, looked for in this folder first and then the repository root.
`run.py` loads it before importing anything else, because `core/constants.py` reads
`os.getenv` at module scope.

Useful flags:

| flag | effect |
| --- | --- |
| `--subsection TITLE` | repeatable; the usual way to name one lesson |
| `--unit`, `--chapter`, `--section` | coarser filters, also repeatable |
| `--video-type NAME` | which layers and stages run, from `config/video_types.json`, default `lore` |
| `--allow-unsupported` | run a video type marked `unsupported`, i.e. the AP exam-prep flow |
| `--until STAGE` | stop after a stage instead of running the rest |
| `--force` | run a stage even where its JSON already exists |
| `--dry-run` | print keys, artifact paths and which already exist; touch nothing |
| `--workers N` | lessons in parallel, default 3 |
| `--storage s3\|local` | where artifacts live, default `s3`; also settable as `STORAGE` in `.env` |

`--dry-run` is worth using first every time: it shows the `{key}` each lesson hashes to and
marks each of the nine artifacts `HAVE` or `MISS`, so you can see what a real run would
actually buy. It also prints the resolved video type and which layers it turns off.

## Video types

A video type selects which *layers* of a lesson get built. All of them live in one file,
`config/video_types.json`, keyed by type name; each entry states only what it changes, so an
empty entry is "every layer on". Four optional keys per type:

- `layers` — the `LAYER_*` flags (see `LAYER_DEFAULTS` in `run.py`), each `true` or `false`.
  A layer is a piece of a stage, so switching one off never changes the stage list.
- `skip_stages` — whole stages to drop, by their `config/stages.json` title.
- `params` — one object per stage that wants tuning, reaching the stage as `<name>_PARAMS`.
- `unsupported` — refuse the type unless `--allow-unsupported` is passed.

| type | what it produces |
| --- | --- |
| `history` | **unsupported.** Every layer, every stage: the original AP exam-prep lesson |
| `general` | **unsupported.** Voiceover + synced image clips, keeping the lesson/section overview diagrams and the conclusion slide; no talking head, no per-concept bullet slides or infographics |
| `lore` | voiceover + imagery only: no talking head, no overlays of any kind, every image model-generated rather than web-sourced, and Video Gen Clips skipped in favour of programmatic camera moves |

Two of the flags are not about overlays:

- `LAYER_WEB_IMAGES` (default on) — off sends the map clips to the image model as well, so nothing
  in the lesson is web-sourced. It works by forcing `generate_image_wrapper`'s existing `type`
  override to FLUX, bypassing the `media.type == 'IMAGE'` branch that would otherwise search the
  maps DB and then Google.
- `LAYER_PROGRAMMATIC_MOTION` (default off) — on gives every still a gentle ffmpeg camera move in
  the local renderer, as an alternative to the Kling/Luma AI motion that Video Gen Clips buys. One
  move per still, chosen from zoom in/out and pan left/right/up/down, seeded from the clip's media
  id so a re-render of a lesson is identical rather than different every time. The motion is
  deliberately small (6-12% magnification over the whole clip, linear, slightly off-centre) and
  zoom never drops below 1.0, so a zoom-out settles into the frame instead of needing image that
  is not there. Animated stills are scaled to cover the frame rather than letterboxed, since
  panning a letterboxed still would drag its bars into view.

`LAYER_PROGRAMMATIC_MOTION` is read by `Local Render`, and its `params` block in
`config/video_types.json` tunes the zoom range, the pan drift and how far off centre a zoom
may sit without touching code.

Unknown layer names, non-boolean values, unknown stage names and unknown keys are all rejected
with a message naming the offender, because a config that reads as configured but runs as
default would quietly buy a full set of vendor calls.

Avatar Clips and Text Overlays always run even when every layer they own is off, because they
also produce the voiceover audio and the word-level timing clock every later stage syncs
against. `lore` therefore still has narration; it just has nothing drawn over it.

Because the video type is not part of a lesson's artifact `{key}`, re-running one lesson under
a different type reuses the cached artifacts unless you pass `--force`.

## Running against a local folder

`--storage local` puts every artifact under `LOCAL_STORAGE_ROOT` (default `artifacts/`)
instead of S3, and needs no AWS credentials at all. The tree mirrors the S3 keys, so a file
can be copied straight in by hand, with one wrinkle: characters S3 allows but Windows
forbids in a path are percent-encoded, so `AP US History: Video Lessons` becomes
`AP US History%3A Video Lessons` on disk.

The switch happens once, at the bottom of `core/clients/s3.py`, which rebinds its own names
onto `core/clients/local_store.py`. All 25 modules that do `from core.clients.s3 import ...`
pick it up untouched.

Local mode cannot run everything, because some vendors fetch an asset from a URL over the
internet and a folder cannot serve one:

- **Video Gen Clips** (Luma/Kling) is dropped from the pipeline by `LOCAL_SKIP`, because Luma
  and Kling need a URL per still and nothing downstream of them runs locally anyway.
- **D-ID** is skipped inside Avatar Clips, but the ElevenLabs half still runs. That matters:
  it produces the `lesson_timings` word-level clock that Text Overlays reads, so stages 5
  through 7 still work.

`stages/local_render.py` is stage 9 and the only renderer; it composites with ffmpeg over
local paths, so a run ends in a watchable MP4 with no bucket and no vendor account. It
refuses to run under `--storage s3`, where every asset would have to be downloaded first.

It reads its inputs through the same `Context` properties as every other stage, which is what
picks up the `-edited.json` sidecars, and it reads per-image metadata rather than the Image
Gen Clips aggregate because that is where a `human_choice` override lands. Bottom to top the
picture is stills, text slides, diagrams, conclusion, avatar.

The one thing to understand before reading that code: the stills are the bottom layer and the
cards are opaque and full-frame, so an image is visible *between* overlay windows, not
underneath them. The Scenes Breakdown track proves it — its eight gaps line up one for one
with the ten card windows. Anything that fills those gaps must preserve their length, or
every overlay after the first gap lands at the wrong timestamp.

What it does not do: the avatar inset. D-ID is skipped, so there is no talking head, and
Avatar Clips leaves the speaker portrait as a fal.media URL rather than storing it, so the
slot is usually empty. The geometry is implemented and checked, waiting for an asset.

Section splits, SRTs and native text overlays are not implemented. `core/media/subtitles.py`
still builds subtitles on demand, taking its split indexes from `core/media/clip_timings.py`.

Only the stage's JSON is cached, never its media, so re-running a lesson whose Local Render
artifact exists is a no-op. To re-render, delete `contents/subsection/Local Render/{key}.json`
and run again; `--force` would redo every stage and re-buy every vendor asset.

Three things make a render look broken, and all of them live in the overlay data rather than
the renderer. The templates animate off `performance.now()`, which `html_to_mov` overrides
and steps per frame, so the animation is entirely driven by those numbers:

- `TextSlidePhrase.start_duration` is how long the typewriter takes to reveal a phrase. A
  flat `1.0` types any sentence out in one second and then waits; it has to be the phrase's
  spoken length or the text does not track the voice.
- A card's clip has to outlast its final reveal. Ending the clip at the last phrase's onset
  put that reveal on the last frame, so one of three sentences never appeared at all.
- A diagram's `start_time` values have to span its card. Crammed into the opening seconds,
  the map finishes building and then sits frozen for the rest of the clip.
- Cards are opaque and full-frame, so an image is only visible where no card covers it, or
  inside one through `TextSlide.visuals`.

`--check` covers these; without it the script calls ElevenLabs and fal.ai and takes about
four minutes.

Image QC survives because `create_presigned_url` returns a base64 `data:` URI, which
OpenAI's vision endpoint accepts. Asking it for audio or video raises rather than handing
back a URL that cannot work.

Seed the run first: `run.py` reads the course lesson plan before it can list a single
lesson, and local mode cannot generate that. It will print the exact path to copy it to.

The Knowledge Graph stage reads Google Sheets rather than storage, so local mode does not
affect it. The service account it needs is already in `.env` as the `GOOGLE_*` variables,
which `core/google_api_utils.py::construct_service_account_dict` assembles in memory. All
twenty of the hardcoded knowledge graph spreadsheets in `stages/knowledge_graph.py` are
readable with it.

## Layout

```
run.py            CLI, dispatch, skip, retry, notify
config/
  stages.json     the nine stages, in order. This file decides what runs
  courses.py      the two AP courses and their execution input
stages/           one module per stage, plus local_render
core/
  context.py      Context: the lesson identity, and every S3 path derived from it
  types.py        the pydantic models the stages hand each other
  helpers.py      llm_call, qc_llm_call, exception_handler
  log.py          CloudWatch logging and the context-preserving thread pool
  clients/        s3 local_store openai gemini speech did sheets gsheet images
  media/          html_to_video clip_timings media_assets thumbnails subtitles lesson_report
prompts/          the video prompts; prompts/images/ are the ones the image client uses
templates/        the HTML slides and diagrams, rendered by Playwright
tools/            the checks, and the lore authoring and preview tools
```

## Stage order matters

`config/stages.json` sets it, and the dependencies are real rather than conventional:

1. **Knowledge Graph** — concepts and their relationships
2. **Video Plan** — the lesson's shape and section breakdown
3. **Video Transcript** — the script
4. **Avatar Clips** — narration audio and talking-head video; produces the word-level clock
5. **Text Overlays** — timed against that clock, so it cannot run earlier
6. **Scenes Breakdown** — carves clips around the overlay windows
7. **Image Gen Clips** — a still per clip
8. **Video Gen Clips** — motion, starting from the chosen still
9. **Local Render** — ffmpeg composites the lot into one MP4

`run.py`'s `STAGES` dict is a lookup table, not a schedule. Adding an entry there does not
make it run; the config is what to edit.

## Skipping, and what it does not skip

A stage is skipped when its artifact already exists at
`{curriculum}/{course}/{subject}/contents/subsection/{title}/{key}.json`, and the cached
JSON is returned instead.

Two things to know before relying on that:

- Only the canonical `{key}.json` is tested, never a reviewer's `{key}-edited.json`
  sidecar. Deleting only the canonical file leaves a stale sidecar that downstream stages
  still prefer. To genuinely redo a stage, delete both.
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

`OPENAI_API_KEY` is still needed, but only for DALL-E, `gpt-image-1`, TTS and Whisper, which
are not chat and do not go through the gateway. Gemini is unaffected: `core/clients/gemini.py`
needs Google's file upload API for video QC, so it talks to Google directly.

## The checks

All of these are offline and free. None needs credentials.

```bash
python tools/check_selfcontained.py       # nothing imports out of this folder
python tools/check_llm_gateway.py         # the gateway slugs, both vendor routes and the refusals
python tools/check_orchestration.py       # run.py's stage order, skip, retry and filters
python tools/check_local_store.py         # the local backend, the rebinding and the stage skips
python -m stages.local_render             # the compositing geometry and the camera motion
python -m stages.local_render             # the layer geometry and the scene-gap filling
python docs/architecture/check_anchors.py # every code anchor in the docs resolves
```

Two dependencies live outside pip and outside this list: ffmpeg and headless Chromium. Both
are named at the top of this file, and both fail loudly rather than silently.

## Known traps

Live bugs, not surprises. Each is here because it costs an afternoon to rediscover.

- `stages/text_overlays.py::slides_timings_identifier` and `::identify_diagram_timings` call
  `input("Check Timings")`. They are off unless `REVIEW_TIMINGS` is set, because they run
  inside a four-worker pool and raced each other over one fixed file. Set it and a
  non-interactive run blocks on stdin forever.
- `core/clients/s3.py` hardcodes `gen-ai-textbooks-dev` as the default bucket in
  `create_presigned_url` and `download`, ignoring `S3_BUCKET`. `local_store.py` sidesteps
  this by ignoring the bucket entirely and using one tree.
- `config/courses.py::get_execution_input` mutates its course entry in place, so two calls
  with different subjects fight over one dict.
- `core/context.py::prep_content_gen_input` sets `SUBSECTION_CONTENT` to the literal string
  `"json.dumps(content, indent=4)"`. Only the stages' `__main__` blocks use it; `run.py`
  builds the placeholders correctly.
- `GEMINI_API_KEY` is read by `core/clients/gemini.py` but is absent from `.env`. Image QC
  runs on OpenAI vision instead, and the Video Gen Clips QC verdict is discarded anyway.
- `core/clients/openai.py::tts` references an undefined name and cannot run. Speech is
  `core/clients/speech.py`.

## Not here

The upstream planners — lesson plan, content plan and metadata generation — are not run by
`run.py`. A lesson run reads `lesson_plan.json` and `guidelines.json` as given. The scripts
that produce them are in `ops/authoring/`, and are run by hand, roughly once per course.
