"""Composite a finished lesson MP4 with ffmpeg. The local-mode stand-in for ShotStack.

ShotStack composites from public URLs: get_lesson_video_body presigns every asset before an
edit is submitted. That is the single reason local mode could not reach a video, since there
is no bucket to presign against. ffmpeg reads local paths and is already a dependency, used
for the section splits and behind every template render, so this needs no vendor at all.

The layer order is ShotStack's own, read off generate_lesson_video_edit: it builds
audio + mediaclip + text_slide + diagram + conclusion + avatar_intro + avatar and then
reverses, and track 0 is the topmost in a ShotStack timeline. So bottom to top the picture is
stills, text slides, diagrams, conclusion, avatar.

The thing to know before reading the graph: the stills are the bottom layer and the cards are
opaque and full-frame, so a still is visible *between* card windows rather than underneath
them. The Scenes Breakdown track is built that way -- its gaps line up with the card windows.
Anything filling those gaps has to preserve their length, or every later overlay is placed
against a base that is too short and lands at the wrong timestamp.

Returns the same 'lesson_video' shape as the ShotStack stage, and writes the MP4 to the same
media path, so a consumer reading lesson_video.src does not care which renderer ran.

Not implemented: the avatar inset (D-ID is skipped locally, and Avatar Clips leaves the
speaker portrait as a fal.media URL rather than storing it, so the slot is normally empty --
the geometry is here and checked, waiting for an asset), the section splits, the SRTs, and
the title overlays ShotStack draws as native text assets.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from core.clients.s3 import (does_file_exist, is_local, load_json_from_s3,
                             upload_file_to_s3)
from core.context import APVideoContext as Context
from core.helpers import exception_handler, sanitize_path
from core.log import with_logging_context
from core.types import LayerName

logger = logging.getLogger(__name__)

WIDTH, HEIGHT, FPS = 1280, 720, 30

# ShotStack's avatar placement, from generate_avatar_tracks.
AVATAR_SCALE, AVATAR_X, AVATAR_Y = 0.148, 0.41, -0.24


def place(scale: float, x: float, y: float, w: int = WIDTH, h: int = HEIGHT):
    """Convert one ShotStack asset placement into ffmpeg overlay arguments.

    The two disagree twice. ShotStack sizes an asset as a fraction of the output and
    positions it by its centre, with offsets in fractions of the output and +y pointing up;
    ffmpeg's overlay takes pixels and positions by the top-left corner with +y down.
    """
    cw, ch = round(w * scale), round(h * scale)
    cx, cy = (0.5 + x) * w, (0.5 - y) * h
    return cw, ch, round(cx - cw / 2), round(cy - ch / 2)


def ffmpeg(args: list[str], label: str) -> None:
    logger.info(f"ffmpeg: {label}")
    proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                          capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"ffmpeg failed ({label}):\n{proc.stderr[-3000:]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


def scene_segments(clips: list[dict]) -> list[tuple[str | None, float]]:
    """Flatten the scene track into (still or None, duration) covering the whole timeline.

    None is a stretch with no still scheduled, which is where a full-frame card takes over.
    """
    out: list[tuple[str | None, float]] = []
    at = 0.0
    for clip in sorted(clips, key=lambda c: c["start_time"]):
        if clip["start_time"] - at > 0.01:
            out.append((None, clip["start_time"] - at))
        out.append((clip["image_path"], clip["end_time"] - clip["start_time"]))
        at = clip["end_time"]
    return out


def build_base(segments: list[tuple[str | None, float]], out: Path) -> None:
    """Concatenate the stills into the bottom visual track.

    ShotStack fits media with 'contain', which letterboxes rather than crops, so this is
    decrease-then-pad. setsar guards against a still whose pixel aspect ratio would otherwise
    make concat refuse the join.
    """
    inputs: list[str] = []
    graph, labels = [], []
    n = 0
    for i, (image, duration) in enumerate(segments):
        if image is None:
            graph.append(f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration:.3f}[s{i}]")
        else:
            inputs += ["-loop", "1", "-t", f"{duration:.3f}", "-i", image]
            graph.append(
                f"[{n}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}[s{i}]")
            n += 1
        labels.append(f"[s{i}]")
    graph.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[v]")
    ffmpeg([*inputs, "-filter_complex", ";".join(graph), "-map", "[v]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(out)],
           f"{len(segments)} scene segments into the base track")


def build_audio(sources: list[Path], out: Path) -> None:
    """Concatenate the narration. Avatar Clips emits contiguous segments."""
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in sources), encoding="utf-8")
    try:
        ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing),
                "-c:a", "aac", "-b:a", "160k", str(out)],
               f"{len(sources)} narration segments")
    finally:
        listing.unlink(missing_ok=True)


def build_final(base: Path, audio: Path, cards: list[dict], avatars: list[dict],
                out: Path) -> None:
    """Overlay the cards and the avatar inset onto the base, then mux the narration.

    Each card has to be both moved to its slot (setpts) and confined to it (enable). Without
    enable, ffmpeg holds a clip's last frame to the end of the render, so the first card would
    cover the rest of the lesson.
    """
    inputs = ["-i", str(base)]
    graph, cur = [], "0:v"

    for i, card in enumerate(cards, start=1):
        inputs += ["-i", card["path"]]
        start, end = card["start_time"], card["end_time"]
        graph.append(f"[{i}:v]setpts=PTS-STARTPTS+{start:.3f}/TB[c{i}]")
        graph.append(f"[{cur}][c{i}]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'"
                     f":eof_action=pass[m{i}]")
        cur = f"m{i}"

    pw, ph, px, py = place(AVATAR_SCALE, AVATAR_X, AVATAR_Y)
    for j, av in enumerate(avatars, start=len(cards) + 1):
        start, end = av["start_time"], av["end_time"]
        inputs += ["-loop", "1", "-t", f"{end - start:.3f}", "-i", av["path"]]
        graph.append(f"[{j}:v]scale={pw}:{ph},setsar=1,fps={FPS},"
                     f"setpts=PTS-STARTPTS+{start:.3f}/TB[a{j}]")
        graph.append(f"[{cur}][a{j}]overlay={px}:{py}:"
                     f"enable='between(t,{start:.3f},{end:.3f})':eof_action=pass[n{j}]")
        cur = f"n{j}"

    audio_index = inputs.count("-i")  # the narration is appended next, so this is its index
    inputs += ["-i", str(audio)]

    args = [*inputs]
    if graph:
        args += ["-filter_complex", ";".join(graph), "-map", f"[{cur}]"]
    else:
        args += ["-map", "0:v"]
    args += ["-map", f"{audio_index}:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(out)]
    ffmpeg(args, f"{len(cards)} cards and {len(avatars)} avatar insets")


def collect(context: Context) -> dict:
    """Gather every asset the render needs, resolved to local paths.

    Reads the same artifacts through the same Context properties ShotStack uses, so the
    -edited.json sidecars a reviewer may have written are picked up here too. Per-image
    metadata rather than the Image Gen Clips aggregate, for the same reason: that is where a
    human_choice override lands.
    """
    from core.clients.local_store import path_for

    def local(src: str) -> str | None:
        if not src or src.startswith("http"):
            return None
        path = path_for(src)
        return str(path) if path.is_file() else None

    clips = []
    for clip in load_json_from_s3(context.clips_path)["clips"]:
        media_id = clip["media"]["id"]
        # Video Gen Clips is skipped locally, so only the still is ever available. ShotStack
        # picks between images/ and videos/ here; there is nothing to pick between.
        metadata_path = f"{context.media_path}images/{media_id}/{media_id}.json"
        if not does_file_exist(metadata_path):
            logger.warning(f"No image metadata for scene {media_id}; leaving it black")
            continue
        metadata = load_json_from_s3(metadata_path)
        choice = metadata.get("human_choice")
        if choice is None:
            choice = metadata.get("qc_choice") or 0
        path = local(metadata["image"][choice]["src"])
        if path:
            clips.append({**clip, "image_path": path})

    overlays = load_json_from_s3(context.text_overlays_path)
    cards = []
    # Text slides, then diagrams, then the conclusion: ShotStack's own stacking order.
    for group in ("text_slides", "diagrams"):
        for item in sorted(overlays.get(group) or [], key=lambda s: s["start_time"]):
            path = local(item.get("src", ""))
            if path:
                cards.append({"path": path, "start_time": item["start_time"],
                              "end_time": item["end_time"]})
    conclusion = overlays.get("conclusion_slide")
    if conclusion and local(conclusion.get("src", "")):
        cards.append({"path": local(conclusion["src"]),
                      "start_time": conclusion["start_time"],
                      "end_time": conclusion["end_time"]})

    assets = sorted(load_json_from_s3(context.avatar_assets_path)["avatar_assets"],
                    key=lambda a: a["start_time"])
    audio = [path_for(a["src"]) for a in assets if local(a["src"])]

    # avatar_clip is the D-ID video and is never produced locally; the still portrait is
    # usually a fal.media URL rather than a stored file, so this list is normally empty.
    avatars = [{"path": local(a.get("avatar_clip") or a.get("image") or ""),
                "start_time": a["start_time"], "end_time": a["end_time"]}
               for a in assets
               if local(a.get("avatar_clip") or a.get("image") or "")]

    return {"clips": clips, "cards": cards, "audio": audio, "avatars": avatars,
            "total": assets[-1]["end_time"] if assets else 0.0}


@with_logging_context(layer=LayerName.SHOTSTACK)
@exception_handler
def render_lesson(output_path: str, output_type: str, inputs: dict) -> dict:
    context = Context(**inputs)
    if not is_local():
        # Nothing stops ffmpeg compositing an S3 lesson, but it would mean downloading every
        # asset first, and on S3 the ShotStack stage already runs. Not worth building twice.
        raise RuntimeError("Local Render only runs under STORAGE=local; use ShotStack on s3")

    logger.info(f"Rendering locally: {context.subsection}")
    assets = collect(context)
    if not assets["audio"]:
        raise RuntimeError("No narration found; the Avatar Clips stage has to run first")

    segments = scene_segments(assets["clips"])
    covered = sum(duration for _, duration in segments)
    logger.info(f"{len(assets['clips'])} stills, {len(assets['cards'])} cards, "
                f"{len(assets['audio'])} narration segments, {assets['total']:.0f}s "
                f"({covered:.0f}s of stills)")
    if assets["total"] - covered > 0.5:
        # The stills stop before the narration does, so pad rather than let -shortest cut
        # the lesson off early.
        segments.append((None, assets["total"] - covered))

    # The same media path and filename the ShotStack stage writes, so lesson_video.src means
    # the same thing in both modes.
    key = f"{context.media_path}{sanitize_path(context.subsection)}.mp4"

    with tempfile.TemporaryDirectory(prefix="local_render_") as tmp:
        base = Path(tmp) / "base.mp4"
        audio = Path(tmp) / "narration.m4a"
        video = Path(tmp) / "lesson.mp4"
        build_base(segments, base)
        build_audio(assets["audio"], audio)
        build_final(base, audio, assets["cards"], assets["avatars"], video)
        duration = probe_duration(video)
        size = video.stat().st_size
        upload_file_to_s3(str(video), key)

    logger.info(f"Rendered {duration:.0f}s, {size // 1024 // 1024} MB, to {key}")
    return {"lesson_video": {
        "src": key,
        "url": None,
        "renderer": "ffmpeg",
        "duration": round(duration, 3),
        "size_bytes": size,
        "stills": len(assets["clips"]),
        "cards": len(assets["cards"]),
        "avatar_insets": len(assets["avatars"]),
    }}


def _selfcheck() -> None:
    cw, ch, cx, cy = place(AVATAR_SCALE, AVATAR_X, AVATAR_Y)
    assert (cw, ch) == (189, 107), (cw, ch)
    assert cx + cw <= WIDTH and cy + ch <= HEIGHT, (cx, cy)
    assert cx > WIDTH / 2 and cy > HEIGHT / 2, (cx, cy)
    assert place(1.0, 0.0, 0.0) == (WIDTH, HEIGHT, 0, 0)
    # +y is up for ShotStack, down for ffmpeg.
    assert place(0.5, 0.0, 0.25)[3] < place(0.5, 0.0, -0.25)[3]

    # The scene track has gaps where the cards take over. They must become filler, or every
    # overlay after the first gap is placed against a base that is too short.
    segments = scene_segments([
        {"start_time": 0.0, "end_time": 5.0, "image_path": "a.png"},
        {"start_time": 12.0, "end_time": 20.0, "image_path": "b.png"}])
    assert [s[0] for s in segments] == ["a.png", None, "b.png"], segments
    assert abs(sum(d for _, d in segments) - 20.0) < 1e-6, segments
    assert abs(segments[1][1] - 7.0) < 1e-6, segments[1]
    # Contiguous input must not gain filler.
    tight = scene_segments([{"start_time": 0.0, "end_time": 5.0, "image_path": "a.png"},
                            {"start_time": 5.0, "end_time": 9.0, "image_path": "b.png"}])
    assert [s[0] for s in tight] == ["a.png", "b.png"], tight
    assert abs(sum(d for _, d in tight) - 9.0) < 1e-6, tight


if __name__ == "__main__":
    _selfcheck()
    print("self-check ok")
