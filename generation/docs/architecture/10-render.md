# 10 - Render

> Stage 9 of nine ([00](00-overview.md)). It composites every artifact the earlier stages wrote into one MP4 with ffmpeg, and writes it to the lesson's media path.

`stages/local_render.py::render_lesson` is the only renderer. The ShotStack integration that used to hold this slot was removed along with its SDK and its API keys; compositing never needed a vendor, and the AP delivery pipeline that depended on ShotStack's hosted URLs is now unsupported ([12](12-operator-tooling.md)).

## Contract

**Reads**

| artifact | used for |
| --- | --- |
| `clips_path` | the scene list, and the per-clip `media.id` that resolves to a still |
| `media/{key}/images/{id}/{id}.json` | `human_choice`, else `qc_choice`, else index 0 |
| `text_overlays_path` | text slides, diagrams and the conclusion slide, with their windows |
| `avatar_assets_path` | narration segments, and any D-ID clip for the picture-in-picture inset |

**Writes** `{media_path}{subsection}.mp4`, and returns `{"lesson_video": {...}}` carrying `src`, `duration`, `size_bytes` and the asset counts.

**Requires** `STORAGE=local`. ffmpeg reads paths, not presigned URLs, so the stage refuses to run against S3 rather than downloading the whole lesson first.

## Flow

1. `::collect` resolves every artifact to a local path, dropping anything that is an `http` URL or missing from disk.
2. `::scene_segments` turns the clip list into `(image, duration, media_id)` triples, inserting black filler where the stills do not cover the narration.
3. `::build_base` concatenates the stills into the bottom visual track. With `LAYER_PROGRAMMATIC_MOTION` on, `::build_base_animated` renders each segment separately under a camera move instead.
4. `::build_audio` concatenates the narration segments, which `Avatar Clips` emits contiguous.
5. `::build_final` overlays the cards and the avatar inset onto the base and muxes the narration.

Bottom to top the picture is: still, text slide, diagram, conclusion slide, avatar inset.

## Design decisions

- **Camera motion is a `perspective` filter, not `zoompan`.** `::camera_motion` writes the four corners of the sampled quad as per-frame expressions, so the crop moves in fractional pixels. `zoompan` rounds its crop to whole pixels, which makes a slow move visibly step. `::motion_for` seeds the move from the still's media id, so a re-render picks the same one.
- **`LAYER_PROGRAMMATIC_MOTION_PARAMS` tunes the feel without code.** `zoom_min`, `zoom_max`, `pan_drift`, `bias_min`, `bias_max` and `motions` all default to the module constants; `config/video_types.json` overrides them per video type ([13](13-generation-layout.md)).
- **Animated segments render one at a time.** One filter graph holding every still at source resolution exhausts memory on a long lesson, so `::build_base_animated` writes each segment to its own file and concatenates them.
- **`::place` positions by an asset's centre with +y up**, matching the geometry the overlay manifests are written in, and converts to ffmpeg's top-left corner with +y down.

## Seams

- **`lesson_video` has no `output_data`.** The AP delivery tooling — `ops/delivery/delivery_sheet.py`, `core/media/thumbnails.py`, `ops/quality/questions.py` — reads `lesson_video['output_data']['url']` and `['sheet_link']`, which only the hosted renderer ever produced. Those tools raise against a locally rendered lesson.
- **Nothing is published.** Subtitles, per-section splits and the copy to `S3_BUCKET_UI` were part of the removed stage. `core/media/subtitles.py` still builds subtitles on demand and takes its split indexes from `core/media/clip_timings.py`.
- **`Video Gen Clips` is skipped locally**, so `::collect` only ever looks under `images/`; there is no video alternative to choose.
- **A missing still is black, not an error.** `::collect` logs a warning and leaves the gap, so a partial image stage yields a watchable but holed video rather than a failed run.
- **`_selfcheck` runs offline.** `python -m stages.local_render` asserts the avatar geometry, the segment durations and that every motion expression is per-frame; it renders nothing.
