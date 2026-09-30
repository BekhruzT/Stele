# 10 - Render

> Stage 8 of eight ([00](00-overview.md)). It composites every artifact the earlier stages wrote into one MP4 with ffmpeg, and writes it to the video folder's media path.

`stages/local_render.py::render_lesson` is the only renderer. It needs no vendor.

## Contract

**Reads**

| artifact | used for |
| --- | --- |
| `clips_path` | the scene list, and the per-clip `media.id` that resolves to a still |
| `media/images/{id}/{id}.json` | `human_choice`, else `qc_choice`, else index 0 |
| `text_overlays_path` | text slides, diagrams and the conclusion slide, with their windows |
| `avatar_assets_path` | narration segments, and any local `avatar_clip` or `image` for the inset |

**Writes** `{video folder}/media/{sanitize_path(title)}.mp4` (`core/helpers.py::sanitize_path`), and returns `{"lesson_video": {...}}` carrying `src`, `url` (always `null`), `renderer: "ffmpeg"`, `duration`, `size_bytes` and the `stills`, `cards` and `avatar_insets` counts; `run.py` saves that as `{video folder}/Local Render.json`.

**Requires** `STORAGE=local`. ffmpeg reads paths, not presigned URLs, so the stage refuses to run against S3 rather than downloading the whole video first.

## Flow

1. `::collect` resolves every artifact to a local path through `core/clients/local_store.py::path_for`, dropping anything that is an `http` URL or missing from disk.
2. `::scene_segments` turns the clip list into `(image, duration, media_id)` triples, inserting black filler where the stills do not cover the timeline; `::render_lesson` pads the end with filler up to the last narration segment's `end_time`.
3. `::build_base` concatenates the stills into the bottom visual track. With `LAYER_PROGRAMMATIC_MOTION` on (the `lore` default), `::build_base_animated` renders each segment separately under a camera move instead.
4. `::build_audio` concatenates the narration segments, which Avatar Clips emits contiguous.
5. `::build_final` overlays the cards and the avatar inset onto the base and muxes the narration with `-shortest`. With nothing to overlay, the base is stream-copied.

Bottom to top the picture is: still, text slides, diagrams, conclusion slide, avatar inset.

## Design decisions

- **Camera motion is a `perspective` filter, not `zoompan`.** `::camera_motion` writes the four corners of the sampled quad as per-frame expressions over a 1536x864 source, so the crop moves in fractional pixels. `zoompan` rounds its crop to whole pixels, which makes a slow move visibly step. `::motion_for` seeds the move from the still's media id, so a re-render picks the same one.
- **`LAYER_PROGRAMMATIC_MOTION_PARAMS` tunes the feel without code.** `zoom_min`, `zoom_max`, `pan_drift`, `bias_min`, `bias_max` and `motions` default to the module constants; `config/video_types.json` overrides them per video type ([13](13-generation-layout.md)).
- **Animated segments render one at a time.** One filter graph holding every still at source resolution exhausts memory on a long video, so `::build_base_animated` writes each segment to its own file and stream-copies them together.
- **`::place` positions by an asset's centre with +y up**, matching the geometry the overlay manifests are written in, and converts to ffmpeg's top-left corner with +y down. The inset is `AVATAR_SCALE`, `AVATAR_X`, `AVATAR_Y` of the frame.

## Seams

- **Only stills reach the picture.** `::collect` looks under `media/images/` only; [09](09-videos.md) output is never read.
- **The avatar inset is empty in practice.** D-ID clips are not generated locally, and a guest `image` is a presigned URL, which `::collect` drops.
- **`title_overlays` and `video_splits` from [06](06-text-overlays.md) are ignored.** No title card is drawn and the video is not cut into sections.
- **A missing still is black, not an error.** `::collect` logs a warning and leaves the gap, so a partial image stage yields a watchable but holed video rather than a failed run.
- **No subtitles and no publishing.** The MP4 in the video folder is the deliverable.
- **`_selfcheck` runs offline.** `python -m stages.local_render` asserts the avatar geometry, the segment durations and that every motion expression is per-frame; it renders nothing.
