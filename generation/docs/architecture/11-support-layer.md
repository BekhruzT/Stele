# 11 — Support layer

> Not a stage ([00](00-overview.md)). This is `core/`, the cross-cutting layer every stage reaches sideways into: storage, model access, logging, notification, and the artifact paths.

## What it does

Provides the one implementation of each thing every stage needs: a storage surface, the model clients, a video-scoped logger that survives thread pools, a notification channel, the per-video artifact paths, and the hash that names media.

## Contract

- **A stage may reach into `core/`. Nothing else.**
  - `core/` holds the models, the LLM and QC wrappers, the lore editorial pipeline, the HTML renderer and the vendor clients — everything more than one stage needs.
  - `core/clients/` is one module per external service. `core/media/` is asset manufacture. Everything else sits directly under `core/`.
  - No stage imports another stage.
- **Storage has two backends and one interface.**
  - `core/clients/s3.py` is the only artifact path any caller names. Under `STORAGE=local` the module rebinds its own functions onto `core/clients/local_store.py` at import time, so every caller keeps working unchanged; `core/clients/s3.py::is_local` reports which backend won ([13](13-generation-layout.md)).
  - `core/local.py::list_files` walks a local folder, and is reached only by `core/clients/s3.py::upload_dir`.
  - Under `STORAGE=s3` a run without working credentials fails at the first read, which is `run.py::load_plan` loading `lesson_plan.json`. Under `STORAGE=local` it needs no credentials at all.

## Keys and paths

- **A video's key is its folder name.** `core/context.py::Context.key` returns `folder`, which `run.py::videos` builds as `c{ci:02d}-v{vi:02d}-{slug}`. It names the log context and the notification lines.
- **Every artifact path comes from `core/context.py::Context`.**
  - `::Context.artifact_path` is `{root}{folder}/{stage}.json`, where `run.py::run_stage` saves.
  - `::Context.reviewed_path` returns the `-edited.json` sidecar when it exists, else the artifact; `video_plan_path`, `transcripts_path`, `avatar_assets_path`, `text_overlays_path` and `clips_path` all go through it.
  - `::Context.media_path` is `{root}{folder}/media/`.
- **Media ids are hashes.** `core/hash.py::hash_image_description` lowercases and underscores a description, then `core/hash.py::hash_code` takes SHA-256 and truncates to eight hex characters, so identical visuals share an id. There is no other normalisation.

## Storage

- **`core/clients/s3.py` is the whole surface**, and the bucket comes from `core/constants.py::S3_BUCKET`. `core/clients/local_store.py` implements the same names against a folder, and swapping between them is the whole of local mode.

| Group | Functions |
| --- | --- |
| Clients | `::get_s3_resource`, `::get_s3_client` |
| Read | `::read_content_from_s3`, `::read_file_from_s3`, `::load_json_from_s3` |
| Write | `::save_file_to_s3`, `::save_json_to_s3`, `::save_content_to_s3`, `::upload_file_to_s3`, `::upload_dir` |
| Existence | `::does_file_exist`, `::does_path_exist`, `::check_folder_exists`, `::get_last_modified_time` |
| List | `::list_files_in_directory`, `::filter_s3_files`, `::filter_dict_keys` |
| Copy and move | `::copy_s3_object`, `::copy_s3_folder`, `::rename_s3_file` |
| Delete | `::delete_file_from_s3` |
| Download | `::download`, `::download_directory` |
| URLs | `::create_presigned_url`, `::get_folder_link` |

- **The bucket is `S3_BUCKET`, which `run.py::storage_for` sets from an `s3://` directory.** The one hardcoded bucket left is `core/clients/openai.py::generate_openai_image`, which uploads to `gen-ai-textbooks-media`.
- **`::list_files_in_directory`, `::copy_s3_folder` and `::check_folder_exists` build their own `boto3.client('s3')`** rather than going through `::get_s3_client`, so they do not share the session the rest of the module uses.
- **`::save_json_to_s3` takes a `save=True` flag** that also mirrors the file into `./functions/fixers/` locally. That folder does not exist here, so passing the flag raises. No caller in this pipeline does.
- **`core/aws.py::get_session`** is a bare `boto3.Session()`, so `AWS_PROFILE` picks the profile.

## Model access

Every chat completion goes to the TrueFoundry gateway. Three clients: the general one, the lore one, and Gemini.

- **`core/clients/openai.py` is the path for every stage's text except the transcript.**
  - `::gateway_slug` resolves an `::LLM` member to its entry in `::GATEWAY_MODEL_SLUGS` and raises `ValueError` if `TFY_API_KEY` or `TFY_BASE_URL` is missing, or if the model has no mapping. A model absent from that table cannot be called at all, which is the point: there is no direct-to-vendor fallback.
  - `::llm_complete` resolves the slug before its `try` deliberately: the handler below it swallows every exception and returns `None`, so a guard raised inside would become the silent failure it exists to prevent. The retry decorator excludes `ValueError` for the same reason — a config error retried thirty times with backoff stalls for about twenty-five minutes before giving up.
  - `::LLM` is the enum every stage names a model from. Three are in live use: `LLM.GPT_5` for the GPT calls, `LLM.CLAUDE_5_SONNET` for most transcript and QC work, and `LLM.CLAUDE_5_OPUS` where a reasoning tier is wanted.
  - `::chat_complete` splits on the slug's vendor group. `claude-group/` goes to `::claude_complete`, the gateway's native Anthropic route, which wants the system prompt separate from the messages and drops it when it is blank, because `::llm_call` is called with `''` all over the stages. Everything else goes to `::openai_complete`, the OpenAI-compatible route.
  - **`temperature` is accepted and never sent, and `max_tokens` reaches the Claude route only.** The reasoning models behind the other slugs reject a temperature and count their own thinking against an output cap, so a caller's 4000 truncates them.
  - `::ensure_json` repairs malformed JSON with an `LLM.GPT_5` call, which is how stages tolerate a model that ignored its schema.
  - Also here: `::call_openai_vision`, which takes the OpenAI-compatible route and retries once with every image inlined as a data URI, plus `::generate_image_dalle` and `::generate_openai_image`. Those two are not chat and use `OPENAI_API_KEY` directly.
  - Retries are tenacity, thirty attempts with exponential backoff.
- **`core/clients/lore.py::LoreClient` is the transcript's client** ([04](04-transcript.md)).
  - It posts straight to the gateway's `/chat/completions` with `requests`, reads `TFY_BASE_URL` and `TFY_API_KEY` from the environment or `.env` at construction, and raises `ValueError` if either is missing.
  - Models are gateway slugs (`core/clients/lore.py::model_slug`): `DEFAULT_MODEL` for drafting, a separate review model, and `DEFAULT_CHOICE_MODEL` for the `hook-choice` call. GPT slugs get `reasoning_effort` and `max_completion_tokens`.
  - One retry on 429, 5xx, timeout or connection error; any `finish_reason` other than `stop` or an empty reply raises. With a `trace_dir`, every call is written there as JSON; `::LoreClient.provenance` sums usage.
- **The lore editorial pipeline sits on that client.** `core/lore_editorial.py::generate_story` runs plan, hooks, draft, review and repair; `core/hook_examples.py::youtube_hook_examples` loads the hook corpus it quotes; `core/lore_review.py::diagnostics` is the prose metrics the lore tools use. See `docs/info/lore_editorial_pipeline.md`.
- **`core/clients/gemini.py`** is `::gemini_media_analysis` for video and image analysis, plus `::delete_old_gemini_files` to clean up uploads older than thirty minutes. It needs Google's file upload API, which the gateway does not carry, so it talks to Google directly with its own client.
- **Every LLM call is transcribed to a file, and the file is in the working directory.**
  - `core/clients/openai.py::log_llm_message` appends every prompt and response to `./prompts.txt`, tagged with the calling function.
  - It is never rotated or truncated, and on a shared machine it is a plaintext record of everything the pipeline has asked a model.
- **The video pipeline's own wrapper sits on top.**
  - `core/helpers.py::llm_call` is what stages call; `::llm_call_with_qc` and `::qc_llm_call` add the finder-and-fixer QC pattern described in [03](03-video-plan.md).
  - `::concurrency_slots` is the named-semaphore decorator that caps [06](06-text-overlays.md) at two and [09](09-videos.md) at three.

## Cost

- **There is no cost ledger.** `core/clients/openai.py::chat_complete` accepts a `cost_callback`, and `core/clients/openai.py::openai_complete` calls it with `core/pricing.py::gpt4_cost` of the token usage. No stage passes one, so pipeline calls are not costed.
- **Lore calls report usage instead.** `core/clients/lore.py::LoreClient.provenance` sums the gateway's `usage` block, including `costInUSD`, across the client's calls.

## Logging

- **`core/log.py` is the only logging module.** Every other module uses a plain `logging.getLogger(__name__)`.
- **`::setup_logging` is called once per process, by `run.py::main`.**
  - It always adds a console handler, and adds `::CloudWatchHandler` when `CLOUDWATCH_LOG_GROUP` is set.
  - `run.py` asks for CloudWatch only when the run is neither a dry run nor local, so a local run logs to the console and nowhere else.
  - `::CloudWatchHandler` emits structured JSON with `metadata.lesson_id`, `metadata.layer`, the filepath and the line.
- **The video key travels in a ContextVar, and that is what makes per-video logs possible.**
  - `::LoggingContext` and `::with_logging_context` set `lesson_id` and `layer`. Each stage entry point is decorated with its `layer`.
  - `run.py::main` wraps each video's `run.py::run_video` in `with_logging_context(lesson_id=key)` before handing it to the worker pool.
  - `::ContextAwareThreadPoolExecutor` copies the parent's contextvars into each worker through an initializer, so a stage's own thread pool does not lose the key. Stages that use a plain `ThreadPoolExecutor` do lose it.
  - The payoff is a CloudWatch filter of the form `{$.metadata.lesson_id=<key>}`, which is what the notification links point at.

## Notification

- **`core/notification_system.py` posts to Google Chat, not Slack.**
  - `::send_gchat_message` posts to `GOOGLE_CHAT_WEBHOOK_URL` and supports threaded replies via a `thread_id`, which is how a batch's messages stay together.
  - `::send_email` uses SES with `SENDER_EMAIL` and `RECIPIENT_EMAIL`, and is not used by the class below.
- **`::NotificationSystem` is constructed once per batch in `run.py::main`** with the run directory and the selected contexts, and only under `STORAGE=s3`. A local run gets `run.py::_Silent` instead, which accepts the same calls and does nothing, so no code path has to ask whether notifications are on.
  - `::send_initial_message` opens the thread with the video list, a CloudWatch filter link per video and an S3 folder link for the run directory.
  - `::send_success_message` links the video's folder in the S3 console; it reads no artifact, so it also holds when `--until` stopped before `Local Render`.
  - `::send_error_message` posts the error and its traceback in a code block.
- **`::get_cloudwatch_stream` reads the handler to build those links**, and it reads `AWS_REGION` from the environment, while `core/constants.py::AWS_REGION` reads `AWS_DEFAULT_REGION`. They are two different variable names for the same thing, and setting only one leaves the other empty.

## Environment

`run.py` loads `.env` before importing anything else, looking in `generation/` first and the repository root second. It has to happen there, because `core/constants.py` reads `os.getenv` at module scope.

`core/constants.py` loads the same two files itself, for entry points that are not `run.py`, such as the scripts under `tools/`. `load_dotenv` does not override what is already set, so for a normal run this second load changes nothing.

**Required for any run.**

| Variable | Read by |
| --- | --- |
| `TFY_API_KEY`, `TFY_BASE_URL` | `core/clients/openai.py` and `core/clients/lore.py`, for every chat completion |
| `OPENAI_API_KEY`, `OPENAI_ORGANIZATION_ID` | `core/clients/openai.py`, for the image endpoints only |
| `ELEVENLABS_API_KEY` | `core/clients/speech.py` ([05](05-avatar-clips.md)) |
| `ELEVENLABS_MODEL_ID` | `core/clients/speech.py`, defaulting to `eleven_multilingual_v2` |
| `FAL_KEY` | `fal_client`, for [05](05-avatar-clips.md), [08](08-images.md), [09](09-videos.md) |
| `STORAGE`, `LOCAL_STORAGE_ROOT` | `core/clients/s3.py`, to pick the backend and where a local one lives. `run.py::storage_for` sets both from the run directory |

**Required under `STORAGE=s3` only.** A local run needs none of these ([13](13-generation-layout.md)).

| Variable | Read by |
| --- | --- |
| `AWS_DEFAULT_REGION` | `core/constants.py::AWS_REGION` |
| `AWS_PROFILE` | `boto3`, through `core/aws.py::get_session` |
| `S3_BUCKET` | `core/constants.py`. `run.py::storage_for` sets it from an `s3://` directory |
| `DID_API_KEY` | `core/clients/did.py` ([05](05-avatar-clips.md)), whose D-ID block is skipped locally |
| `LUMAAI_API_KEY` | [09](09-videos.md), skipped entirely under local and by the `lore` video type |
| `GOOGLE_CHAT_WEBHOOK_URL`, `SENDER_EMAIL`, `RECIPIENT_EMAIL`, `AWS_REGION` | `core/notification_system.py` |
| `CLOUDWATCH_LOG_GROUP` | `core/log.py` |

**Optional, and read where noted.**

| Variable | Read by |
| --- | --- |
| `GEMINI_API_KEY` | `core/clients/gemini.py`. Absent in practice; see Seams. |
| `GCP_API_KEY`, `GCP_SEARCH_CXID` | `core/clients/images.py`, for [08](08-images.md) web search |
| `TIKTOK_AWS_ACCESS_KEY_ID`, `TIKTOK_AWS_SECRET_ACCESS_KEY` | `core/clients/images.py`, for the Midjourney and Mermaid lambdas |
| `DISABLE_TREE_DESCRIPTION` | `prompts/overlay_prompts.py`, [06](06-text-overlays.md) diagram behaviour |
| `REVIEW_TIMINGS` | [06](06-text-overlays.md), to re-enable the interactive timing gates |

## What `core/` holds

| Group | Modules |
| --- | --- |
| Storage and identity | `clients/s3.py`, `clients/local_store.py`, `hash.py`, `context.py`, `local.py`, `aws.py` |
| Models | `clients/openai.py`, `clients/lore.py`, `clients/gemini.py`, `clients/image_qc.py`, `helpers.py` |
| Lore editorial | `lore_editorial.py`, `hook_examples.py`, `lore_review.py` |
| Vendors | `clients/speech.py`, `clients/did.py`, `clients/images.py` |
| Media manufacture | `media/clip_timings.py`, `media/html_to_video.py`, `media/media_assets.py` |
| Plumbing | `types.py`, `stage_constants.py`, `constants.py`, `log.py`, `misc.py`, `parsers.py`, `pricing.py`, `notification_system.py` |

## Seams

- **`GEMINI_API_KEY` has never been valid here.** `core/clients/gemini.py` reads it and the package is installed, but the key is absent, which is why `core/clients/image_qc.py::absolute_image_qc` runs on OpenAI vision instead ([08](08-images.md)). Its one caller, [09](09-videos.md), is skipped by the `lore` video type.