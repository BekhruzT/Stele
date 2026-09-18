# 11 — Support layer

> Not a stage ([00](00-overview.md)). This is `core/`, the cross-cutting layer every stage reaches sideways into: storage, model access, cost, logging, notification, and the key scheme.

## What it does

Provides the one implementation of each thing every stage needs: a storage surface, the model clients, a cost ledger, a lesson-scoped logger that survives thread pools, a notification channel, and the hash that names every artifact.

## Contract

- **A stage may reach into `core/`. Nothing else.**
  - `core/` holds the models, the LLM and QC wrappers, the HTML renderer and the vendor clients — everything more than one stage needs.
  - `core/clients/` is one module per external service. `core/media/` is asset manufacture. Everything else sits directly under `core/`.
  - Nothing under `ops/` is importable from a stage, and no stage imports another stage.
- **Storage has two backends and one interface.**
  - `core/clients/s3.py` is the only artifact path any caller names. Under `STORAGE=local` the module rebinds its own functions onto `core/clients/local_store.py` at import time, so every caller keeps working unchanged; `core/clients/s3.py::is_local` reports which backend won ([13](13-generation-layout.md)).
  - `core/local.py` handles scratch files under `/tmp` only, and is reached mainly by `core/clients/s3.py::upload_dir`.
  - Under `STORAGE=s3` a run without working credentials fails at the first read, which is `run.py::load_plan` loading the lesson plan. Under `STORAGE=local` it needs no credentials at all.

## The key scheme

- **`{key}` is derived once and used everywhere.**
  - `core/path.py::get_key` joins the four titles with hyphens: `"-".join(titles)`.
  - `core/hash.py::hash_code` takes SHA-256 of that and truncates to eight hex characters. It also accepts a dict, which it dumps with sorted keys first.
  - `core/context.py::Context.key` is the property every stage uses.
- **There is no normalisation.** Case, whitespace and punctuation in a title all change the hash.
- **Media ids are separate.** `core/hash.py::hash_image_description` lowercases and underscores a description before hashing, so identical visuals across lessons share an id.
- **The path builders are all in `core/path.py`.**
  - `::get_lesson_plan_path`, `::get_lesson_plan_content_path`, `::get_content_path`, `::get_content_prompt_path`, `::get_fixed_content_path`, `::get_guidelines_path`, `::get_full_guidelines_path`.
  - `::get_content_path` appends `.txt` when the filename has no suffix, which is why every stage passes `{key}.json` explicitly.

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

- **Three functions default to a hardcoded bucket instead of `S3_BUCKET`.**
  - `::create_presigned_url` and `::download` default to `gen-ai-textbooks-dev`.
  - `core/clients/openai.py::generate_openai_image` uploads to `gen-ai-textbooks-media`.
  - A run pointed at another bucket will therefore read presigned URLs and downloads from dev without any log line saying so. This is the quietest environment bug in the repo.
- **`::list_files_in_directory` builds its own `boto3.client('s3')`** rather than going through `::get_s3_client`, so it does not share the session the rest of the module uses.
- **`::save_json_to_s3` takes a `save=True` flag** that also mirrors the file into `./functions/fixers/` locally. That folder does not exist here, so passing the flag raises. No caller in this pipeline does.
- **`core/aws.py`** builds the boto3 session, and selects the `default` AWS profile when `ENV=local`.

## Model access

Every chat completion goes to the TrueFoundry gateway. Two clients, and every text generation goes through the first.

- **`core/clients/openai.py` is the only path for text.**
  - `::gateway_slug` resolves an `::LLM` member to its entry in `::GATEWAY_MODEL_SLUGS` and raises `ValueError` if `TFY_API_KEY` or `TFY_BASE_URL` is missing, or if the model has no mapping. A model absent from that table cannot be called at all, which is the point: there is no direct-to-vendor fallback.
  - `::llm_complete` resolves the slug before its `try` deliberately: the handler below it swallows every exception and returns `None`, so a guard raised inside would become the silent failure it exists to prevent. The retry decorator excludes `ValueError` for the same reason — a config error retried thirty times with backoff stalls for about twenty-five minutes before giving up.
  - `::LLM` is the enum every stage names a model from. Three are in live use: `LLM.GPT_5` for the GPT calls, `LLM.CLAUDE_5_SONNET` for most transcript and QC work, and `LLM.CLAUDE_5_OPUS` where a reasoning tier is wanted.
  - `::chat_complete` splits on the slug's vendor group. `claude-group/` goes to `::claude_complete`, the gateway's native Anthropic route, which wants the system prompt separate from the messages and drops it when it is blank, because `::llm_call` is called with `''` all over the stages. Everything else goes to `::openai_complete`, the OpenAI-compatible route.
  - **`temperature` is accepted and never sent, and `max_tokens` reaches the Claude route only.** The reasoning models behind the other slugs reject a temperature and count their own thinking against an output cap, so a caller's 4000 truncates them.
  - `::ensure_json` repairs malformed JSON with an `LLM.GPT_5` call, which is how stages tolerate a model that ignored its schema.
  - Also here: `::call_openai_vision`, which takes the OpenAI-compatible route and retries once with every image inlined as a data URI, plus `::generate_image_dalle`, `::generate_openai_image` and `::OpenaiAssistantConversation`. Those three are not chat and use `OPENAI_API_KEY` directly.
  - Retries are tenacity, thirty attempts with exponential backoff.
- **`core/clients/gemini.py`** is `::gemini_media_analysis` for video and image analysis, plus `::delete_old_gemini_files` to clean up uploads older than thirty minutes. It needs Google's file upload API, which the gateway does not carry, so it talks to Google directly with its own client.
- **Every LLM call is transcribed to a file, and the file is in the working directory.**
  - `core/clients/openai.py::log_llm_message` appends every prompt and response to `./prompts.txt`, tagged with the calling function.
  - It is never rotated or truncated, and on a shared machine it is a plaintext record of everything the pipeline has asked a model.
- **The video pipeline's own wrapper sits on top.**
  - `core/helpers.py::llm_call` is what stages call; `::llm_call_with_qc` and `::qc_llm_call` add the finder-and-fixer QC pattern described in [03](03-video-plan.md).
  - `::concurrency_slots` is the named-semaphore decorator that caps [06](06-text-overlays.md) at two and [09](09-videos.md) at three.

## Cost

- **`core/cost_tracker.py` is two functions over DynamoDB.**
  - `::init_cost(pk, sk)` writes `{prompt: 0, completion: 0}`.
  - `::update_cost(pk, sk, prompt_cost, completion_cost)` increments via `core/clients/ddb.py::incrby`.
  - The table is `DDB_TABLE_NAME`.
- **Keys are built by `core/misc.py::pk`, which is `"#".join(args)`.**
  - The partition key is always `pk(course, curriculum, subject)`.
  - Sort keys seen in this pipeline: `cost#subsection#content`, `cost#subsection#content-plan`, `cost#lesson_plan#clustering`, `cost#lesson_plan#categorization`, `cost#key_concepts`, `cost#images`.
  - `core/pricing.py` computes token costs.
- **Cost is attributed by a callback threaded into the LLM call**, so a stage that does not pass one is not counted.
  - Nothing in the nine stages initialises a cost row; `core/cost_tracker.py::init_cost` is called only from `ops/authoring/`. A pipeline run therefore increments rows that may not exist yet.

## Logging

- **Two modules, and the pipeline uses the second.**
  - `core/logger.py::Logger` is a named wrapper that nothing constructs. Most modules carry a commented-out line where it used to be, replaced by a plain `logging.getLogger(__name__)`; `stages/avatar_clips.py` still imports it without using it.
  - `core/log.py` is the real one.
- **`::setup_logging` is called once per process, by `run.py`.**
  - It always adds a console handler, and adds `::CloudWatchHandler` when `CLOUDWATCH_LOG_GROUP` is set.
  - `run.py` asks for CloudWatch only when the run is neither a dry run nor local, so a local run logs to the console and nowhere else.
  - Every stage module calls it again in its own `__main__` block, which is how a stage can be run alone.
  - `::CloudWatchHandler` emits structured JSON with `metadata.lesson_id`, `metadata.layer`, the filepath and the line.
- **The lesson id travels in a ContextVar, and that is what makes per-lesson logs possible.**
  - `::LoggingContext` and `::with_logging_context` set `lesson_id` and `layer`.
  - `run.py::main` wraps each lesson's `run.py::run_lesson` in `with_logging_context(lesson_id=key)` before handing it to the worker pool.
  - `::ContextAwareThreadPoolExecutor` copies the parent's contextvars into each worker through an initializer, so a stage's own thread pool does not lose the lesson id. Stages that use a plain `ThreadPoolExecutor` do lose it.
  - The payoff is a CloudWatch filter of the form `{$.metadata.lesson_id="<hash>"}`, which is what the notification links point at.

## Notification

- **`core/notification_system.py` posts to Google Chat, not Slack.**
  - `::send_gchat_message` posts to `GOOGLE_CHAT_WEBHOOK_URL` and supports threaded replies via a `thread_id`, which is how a batch's messages stay together.
  - `::send_email` uses SES with `SENDER_EMAIL` and `RECIPIENT_EMAIL`, and is not used by the class below.
- **`::NotificationSystem` is constructed once per batch in `run.py::main`**, and only under `STORAGE=s3`. A local run gets `run.py::_Silent` instead, which accepts the same calls and does nothing, so no code path has to ask whether notifications are on.
  - `::send_initial_message` opens the thread with the lesson list, a CloudWatch filter link per lesson and an S3 folder link.
  - `::send_success_message` reads the lesson's render artifact for the finished video URL and the delivery sheet link ([10](10-render.md)). Neither field survives the move to ffmpeg, so this path is AP-only and unsupported.
  - `::send_error_message` posts the error and its traceback in a code block.
- **`::get_cloudwatch_stream` reads the handler to build those links**, and it reads `AWS_REGION` from the environment, while `core/constants.py::AWS_REGION` reads `AWS_DEFAULT_REGION`. They are two different variable names for the same thing, and setting only one leaves the other empty.

## Environment

`run.py` loads `.env` before importing anything else, looking in `generation/` first and the repository root second. It has to happen there, because `core/constants.py` reads `os.getenv` at module scope.

`core/constants.py` loads the same two files itself, for the two entry points that are not `run.py`: a stage's own `__main__` block, and the scripts under `ops/`. Neither gets a chance to load anything before importing it. `load_dotenv` does not override what is already set, so for a normal run this second load changes nothing.

**Required for any run.**

| Variable | Read by |
| --- | --- |
| `TFY_API_KEY`, `TFY_BASE_URL` | `core/clients/openai.py`, for every chat completion |
| `OPENAI_API_KEY`, `OPENAI_ORGANIZATION_ID` | `core/clients/openai.py`, for the image and speech endpoints only |
| `ELEVENLABS_API_KEY` | [05](05-avatar-clips.md) |
| `ELEVENLABS_MODEL_ID` | `core/clients/speech.py`, defaulting to `eleven_multilingual_v2` |
| `FAL_KEY` | [05](05-avatar-clips.md), [08](08-images.md), [09](09-videos.md) |
| `GOOGLE_PROJECT_ID`, `GOOGLE_PRIVATE_KEY_ID`, `GOOGLE_PRIVATE_KEY`, `GOOGLE_CLIENT_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_X509_CERT_URL` | `core/google_api_utils.py::construct_service_account_dict`, which assembles the service account in memory. [02](02-knowledge-graph.md) reads Sheets with it. |
| `STORAGE`, `LOCAL_STORAGE_ROOT` | `core/clients/s3.py`, to pick the backend and where a local one lives |

**Required under `STORAGE=s3` only.** A local run needs none of these ([13](13-generation-layout.md)).

| Variable | Read by |
| --- | --- |
| `AWS_DEFAULT_REGION` | `core/constants.py::AWS_REGION` |
| `AWS_PROFILE`, `ENV` | `core/aws.py` |
| `S3_BUCKET`, `S3_BUCKET_UI` | `core/constants.py`, and [10](10-render.md) for publication |
| `S3_MEDIA_BUCKET` | `core/constants.py`, for presenter portraits and character bundles. A separate, publicly readable bucket, because Stele fetches those by URL |
| `DID_API_KEY` | [05](05-avatar-clips.md), whose D-ID block is skipped locally |
| `LUMAAI_API_KEY` | [09](09-videos.md), skipped entirely under local |
| `DDB_TABLE_NAME` | `core/cost_tracker.py` via `core/clients/ddb.py` |
| `GOOGLE_CHAT_WEBHOOK_URL`, `SENDER_EMAIL`, `RECIPIENT_EMAIL`, `AWS_REGION` | `core/notification_system.py` |
| `CLOUDWATCH_LOG_GROUP` | `core/log.py` |

**Optional, and read where noted.**

| Variable | Read by |
| --- | --- |
| `GEMINI_API_KEY` | `core/clients/gemini.py`. Absent in practice; see Seams. |
| `ASSEMBLYAI_API_KEY` | `core/clients/speech.py` transcription |
| `GCP_API_KEY`, `GCP_SEARCH_CXID` | [08](08-images.md) web search |
| `GOOGLE_API_KEY`, `GOOGLE_CSE_ID` | `core/constants.py` |
| `TIKTOK_AWS_ACCESS_KEY_ID`, `TIKTOK_AWS_SECRET_ACCESS_KEY` | `core/constants.py`, for the Midjourney and Mermaid lambdas |
| `GUIDELINES_PATH`, `GUIDELINES_API_URL` | `core/constants.py` |
| `DISABLE_TREE_DESCRIPTION` | [06](06-text-overlays.md) diagram behaviour |
| `REVIEW_TIMINGS` | [06](06-text-overlays.md), to re-enable the interactive timing gates |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `ops/media/character_bundle.py` |
| `STELE_UPLOAD_USERNAME`, `STELE_UPLOAD_PASSWORD`, `STELE_UPLOAD_AWS_CLIENT_ID` | `ops/delivery/stele.py`, to authenticate against Stele before publishing |

## What `core/` holds

| Group | Modules |
| --- | --- |
| Storage and identity | `clients/s3.py`, `clients/local_store.py`, `path.py`, `hash.py`, `context.py`, `local.py` |
| Models | `clients/openai.py`, `clients/gemini.py`, `clients/image_qc.py`, `helpers.py` |
| Vendors | `clients/speech.py`, `clients/did.py`, `clients/images.py`, `clients/sheets.py`, `clients/gsheet.py`, `clients/ddb.py` |
| Media manufacture | `media/clip_timings.py`, `media/html_to_video.py`, `media/media_assets.py`, `media/thumbnails.py`, `media/subtitles.py`, `media/lesson_report.py` |
| Plumbing | `types.py`, `stage_constants.py`, `constants.py`, `log.py`, `logger.py`, `misc.py`, `parsers.py`, `aws.py`, `pricing.py`, `cost_tracker.py`, `guidelines.py`, `lesson_plan.py`, `google_api_utils.py`, `notification_system.py`, `content_analysis.py`, `post_evaluations.py` |

## Seams

- **`core/clients/openai.py::tts` references an undefined name** and cannot run. TTS in this pipeline is `core/clients/speech.py`.
- **`GEMINI_API_KEY` has never been valid here.** `core/clients/gemini.py` reads it and the package is installed, but the key is absent, which is why `core/clients/image_qc.py::absolute_image_qc` runs on OpenAI vision instead ([08](08-images.md)).
- **`config/courses.py::data_list` is a hardcoded catalogue of eleven course presets**, and `config/courses.py::get_execution_input` indexes it by a two-entry dict, `{"AP World History": 0, "AP US History": 2}`. A subject not in that dict raises `KeyError`.
- **`core/context.py::render_template` is not the renderer the video stages use.** It loads from `./templates` and rewrites asset `src` attributes into presigned URLs. The overlay path uses `core/media/html_to_video.py::render_template` instead.
- **`core/context.py::EMathContext`** is a sibling context for a Grade 5 maths pipeline, unrelated to AP video.
- **`core/misc.py::round_robin` has no callers, and does not round-robin.** It calls `random.choice`. Its one caller spread Bedrock quota across regions, and went with the Anthropic route.
