# generation/

The AP video pipeline, self-contained. Nine stages turn one subsection of a course lesson
plan into a rendered video, and `run.py` is the only entry point.

Nothing here imports anything outside this folder. `tools/check_selfcontained.py` enforces
that, which is what makes the rest of the repository deletable.

## Where things are

| folder | what it holds |
| --- | --- |
| `stages/`, `core/`, `prompts/`, `config/` | the pipeline: what `run.py` runs |
| `ops/` | human-driven tooling — review, feedback, repair, authoring, delivery. Not wired into `run.py`, and not verified. See [ops/README.md](ops/README.md). |
| `tools/` | the check suites and the ffmpeg compositing spike |
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
| `--until STAGE` | stop after a stage instead of running the rest |
| `--force` | run a stage even where its JSON already exists |
| `--dry-run` | print keys, artifact paths and which already exist; touch nothing |
| `--workers N` | lessons in parallel, default 3 |
| `--storage s3\|local` | where artifacts live, default `s3`; also settable as `STORAGE` in `.env` |

`--dry-run` is worth using first every time: it shows the `{key}` each lesson hashes to and
marks each of the nine artifacts `HAVE` or `MISS`, so you can see what a real run would
actually buy.

## Running against a local folder

`--storage local` puts every artifact under `LOCAL_STORAGE_ROOT` (default `artifacts/`)
instead of S3, and needs no AWS credentials at all. The tree mirrors the S3 keys, so a file
can be copied straight in by hand, with one wrinkle: characters S3 allows but Windows
forbids in a path are percent-encoded, so `AP US History: Video Lessons` becomes
`AP US History%3A Video Lessons` on disk.

The switch happens once, at the bottom of `core/clients/s3.py`, which rebinds its own names
onto `core/clients/local_store.py`. All 25 modules that do `from core.clients.s3 import ...`
pick it up untouched.

Local mode cannot run everything, because three vendors fetch an asset from a URL over the
internet and a folder cannot serve one:

- **Video Gen Clips** (Luma/Kling) and **ShotStack** are dropped from the pipeline.
- **D-ID** is skipped inside Avatar Clips, but the ElevenLabs half still runs. That matters:
  it produces the `lesson_timings` word-level clock that Text Overlays reads, so stages 5
  through 7 still work. What you get is everything up to the images, never a rendered video.

`stages/local_render.py` closes that last gap, and it is wired into the pipeline rather than
being a side tool: in local mode `run.py` substitutes it for ShotStack in place, so a local
run ends in a watchable MP4 with no bucket and no vendor account. Two different mechanisms do
that, and the distinction is the point:

- `LOCAL_SKIP` drops a stage entirely. Only Video Gen Clips is in it, because Luma and Kling
  need a URL per still and nothing downstream of them runs locally anyway.
- `LOCAL_SWAP` substitutes one. ShotStack is in it, because compositing is not the part that
  needs a vendor — only the presigned URLs were. Substituting rather than adding an entry
  means the renderer inherits ShotStack's position in `config/stages.json`, which is last.

The stage writes the MP4 to the same media path and returns the same `lesson_video` shape as
ShotStack, so a consumer reading `lesson_video.src` does not care which renderer ran. It
reads its inputs through the same `Context` properties too, which is what picks up the
`-edited.json` sidecars, and it reads per-image metadata rather than the Image Gen Clips
aggregate because that is where a `human_choice` override lands.

It reproduces ShotStack's layer order, read off `stages/shotstack.py`, which builds
`audio + mediaclip + text_slide + diagram + conclusion + avatar_intro + avatar` and then
reverses — and since track 0 is topmost in a ShotStack timeline, bottom to top the picture is
stills, text slides, diagrams, conclusion, avatar.

The one thing to understand before reading that code: the stills are the bottom layer and the
cards are opaque and full-frame, so an image is visible *between* overlay windows, not
underneath them. The Scenes Breakdown track proves it — its eight gaps line up one for one
with the ten card windows. Anything that fills those gaps must preserve their length, or
every overlay after the first gap lands at the wrong timestamp.

What it does not do: the avatar inset. D-ID is skipped, so there is no talking head, and
Avatar Clips leaves the speaker portrait as a fal.media URL rather than storing it, so the
slot is usually empty. The geometry is implemented and checked, waiting for an asset.

Section splits, SRTs and the title overlays ShotStack draws as native text assets are also
not implemented.

Only the stage's JSON is cached, never its media, so re-running a lesson whose Local Render
artifact exists is a no-op. To re-render, delete `contents/subsection/Local Render/{key}.json`
and run again; `--force` would redo every stage and re-buy every vendor asset.

`tools/spike_render.py` is the smaller argument that got there first. ShotStack is a
compositor, and ffmpeg — already a dependency, already used for the section splits and for
every template render — can do the same job against local paths. The spike narrates the
introduction and the conclusion of a generated transcript, renders a text slide and a mind
map through the existing Playwright path, generates one FLUX still, and composites the lot
into a watchable MP4 with a single `filter_complex`. `place()` converts ShotStack's
centre-origin normalised geometry into ffmpeg's top-left pixels, which is the part worth
getting right.

It also documents what makes a render look broken, because the first version got all three
wrong. The templates animate off `performance.now()`, which `html_to_mov` overrides and
steps per frame, so the animation is entirely driven by the numbers in the overlay data:

- `TextSlidePhrase.start_duration` is how long the typewriter takes to reveal a phrase. A
  flat `1.0` types any sentence out in one second and then waits; it has to be the phrase's
  spoken length or the text does not track the voice.
- A card's clip has to outlast its final reveal. Ending the clip at the last phrase's onset
  put that reveal on the last frame, so one of three sentences never appeared at all.
- A diagram's `start_time` values have to span its card. Crammed into the opening seconds,
  the map finishes building and then sits frozen for the rest of the clip.
- Cards are opaque and full-frame, so an image is only visible where no card covers it, or
  inside one through `TextSlide.visuals`. The spike does both.

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
  clients/        s3 local_store openai gemini speech did shotstack sheets gsheet images
  media/          html_to_video clip_timings media_assets thumbnails subtitles lesson_report
prompts/          the video prompts; prompts/images/ are the ones the image client uses
templates/        the HTML slides and diagrams, rendered by Playwright
tools/            the checks, and the ffmpeg compositing spike
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
9. **ShotStack** — the final render

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

Everything goes to OpenAI. Anthropic is retired, but the four `LLM.CLAUDE_*` and
`LLM.ANTHROPIC_CLAUDE_*` names still exist in `core/clients/openai.py` as enum aliases
carrying `gpt-4.1` and `gpt-4o` values, so the ~58 call sites that spell them keep working
and nothing reaches the anthropic SDK. `llm_complete` raises on any model that is not
`gpt-*` or `o1` rather than silently routing elsewhere. Gemini is unaffected; it never went
through `llm_complete` and has its own client.

The one thing lost: `CLAUDE_3_7_SONNET_THINKING` used to buy an extra reasoning tier and now
resolves to the same model as the non-thinking calls.

## The checks

All of these are offline and free. None needs credentials.

```bash
python tools/check_selfcontained.py       # nothing imports out of this folder
python tools/check_orchestration.py       # run.py's stage order, skip, retry and filters
python tools/check_local_store.py         # the local backend, the rebinding and the stage skips
python tools/spike_render.py --check      # the compositing geometry, reveal timings and staging
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
