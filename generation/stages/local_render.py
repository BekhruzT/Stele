"""Composite a finished lesson MP4 with ffmpeg over the artifacts on local disk."""

from __future__ import annotations

import logging
import random
import subprocess
import tempfile
from pathlib import Path

from core.clients.s3 import (does_file_exist, is_local, load_json_from_s3,
                             upload_file_to_s3)
from core.context import Context
from core.helpers import exception_handler, sanitize_path
from core.log import with_logging_context
from core.types import LayerName

logger = logging.getLogger(__name__)

WIDTH, HEIGHT, FPS = 1280, 720, 30

# Talking-head inset, as fractions of the output frame, measured from its centre.
AVATAR_SCALE, AVATAR_X, AVATAR_Y = 0.148, 0.41, -0.24

# The camera moves a still can carry; no vertical pan since 720px of height quantises first.
MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right")

# Magnification added over the whole clip, kept small and calm rather than cinematic.
ZOOM_MIN, ZOOM_MAX = 0.10, 0.16

# A pan's own zoom, resizing the crop every frame so no two frames come out identical.
PAN_DRIFT = 0.08

# How far off centre a zoom may sit, as a fraction of the slack. 0.5 is dead centre.
BIAS_MIN, BIAS_MAX = 0.35, 0.65

# Keep enough source detail for the largest zoom, then resample fractional camera coordinates.
SOURCE_W, SOURCE_H = 1536, 864

# The longest scene the clip splitter produces, the worst case for the rounding above.
MAX_CLIP_SECONDS = 20


def place(scale: float, x: float, y: float, w: int = WIDTH, h: int = HEIGHT):
    """Convert a centre-anchored fractional placement into ffmpeg overlay arguments."""
    cw, ch = round(w * scale), round(h * scale)
    cx, cy = (0.5 + x) * w, (0.5 - y) * h
    return cw, ch, round(cx - cw / 2), round(cy - ch / 2)


def motion_for(media_id: str, duration: float, params: dict | None = None) -> dict:
    """Pick a deterministic camera move for a still, seeded from its media id; params override the defaults."""
    p = params or {}
    rng = random.Random(media_id)
    motions = p.get("motions", list(MOTIONS))
    kind = rng.choice(motions)
    a = rng.uniform(p.get("zoom_min", ZOOM_MIN), p.get("zoom_max", ZOOM_MAX))
    bx = rng.uniform(p.get("bias_min", BIAS_MIN), p.get("bias_max", BIAS_MAX))
    by = rng.uniform(p.get("bias_min", BIAS_MIN), p.get("bias_max", BIAS_MAX))
    n = max(1, round(duration * FPS))
    return {"kind": kind, "a": a, "bx": bx, "by": by, "n": n,
            "pan_drift": p.get("pan_drift", PAN_DRIFT)}


def camera_motion(move: dict) -> str:
    """Build fractional-coordinate camera motion with cubic resampling."""
    kind, a, bx, by, n = move["kind"], move["a"], move["bx"], move["by"], move["n"]
    pan_drift = move.get("pan_drift", PAN_DRIFT)
    denom = max(1, n - 1)
    if kind == "zoom_in":
        extra, x_bias, y_bias = f"{a}*on/{denom}", bx, by
    elif kind == "zoom_out":
        extra, x_bias, y_bias = f"{a}-{a}*on/{denom}", bx, by
    elif kind == "pan_right":
        extra, x_bias, y_bias = str(pan_drift), f"on/{denom}", 0.5
    elif kind == "pan_left":
        extra, x_bias, y_bias = str(pan_drift), f"1-on/{denom}", 0.5
    else:
        raise ValueError(kind)
    left, right = f"-({x_bias})*({extra})*W", f"W+(1-({x_bias}))*({extra})*W"
    top, bottom = f"-({y_bias})*({extra})*H", f"H+(1-({y_bias}))*({extra})*H"
    return (
        f"scale={SOURCE_W}:{SOURCE_H}:force_original_aspect_ratio=increase,"
        f"crop={SOURCE_W}:{SOURCE_H},setsar=1,fps={FPS},"
        f"perspective=x0='{left}':y0='{top}':x1='{right}':y1='{top}':"
        f"x2='{left}':y2='{bottom}':x3='{right}':y3='{bottom}':"
        f"interpolation=cubic:sense=destination:eval=frame,scale={WIDTH}:{HEIGHT}")


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


def scene_segments(clips: list[dict]) -> list[tuple[str | None, float, str | None]]:
    """Flatten the scene track into (still or None, duration, media id); None is a filler gap."""
    out: list[tuple[str | None, float, str | None]] = []
    at = 0.0
    for clip in sorted(clips, key=lambda c: c["start_time"]):
        if clip["start_time"] - at > 0.01:
            out.append((None, clip["start_time"] - at, None))
        out.append((clip["image_path"], clip["end_time"] - clip["start_time"],
                    clip.get("media_id")))
        at = clip["end_time"]
    return out


def build_base(segments: list[tuple[str | None, float, str | None]], out: Path,
               animate: bool = False, motion_params: dict | None = None) -> None:
    """Concatenate the stills into the bottom visual track, optionally with a camera move on each."""
    if animate:
        build_base_animated(segments, out, motion_params)
        return
    inputs: list[str] = []
    graph, labels = [], []
    n = 0
    for i, (image, duration, _) in enumerate(segments):
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


# Every segment is encoded identically so the concat can stream-copy them into the base track.
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def build_base_animated(segments: list[tuple[str | None, float, str | None]],
                        out: Path, motion_params: dict | None = None) -> None:
    """Render each segment on its own, then join them, rather than holding every still in one graph."""
    with tempfile.TemporaryDirectory(prefix="lr_anim_") as tmp:
        parts: list[str] = []
        listing = Path(tmp) / "parts.txt"
        for i, (image, duration, media_id) in enumerate(segments):
            part = Path(tmp) / f"seg{i:04d}.mp4"
            if image is None or media_id is None:
                ffmpeg(["-f", "lavfi",
                        "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration:.3f}",
                        *ENCODE, str(part)],
                       f"filler segment {i}")
            else:
                move = motion_for(media_id, duration, motion_params)
                ffmpeg(["-loop", "1", "-t", f"{duration:.3f}", "-i", image,
                        "-vf", camera_motion(move), "-frames:v", str(move["n"]),
                        *ENCODE, str(part)],
                       f"animated segment {i} ({move['kind']})")
            parts.append(f"file '{part.as_posix()}'\n")
        listing.write_text("".join(parts), encoding="utf-8")
        ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c:v", "copy", str(out)],
               f"{len(segments)} animated segments joined")


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
    """Overlay the cards and the avatar inset onto the base, then mux the narration."""
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
        args += ["-filter_complex", ";".join(graph), "-map", f"[{cur}]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    else:
        # Nothing to composite, so copy the base through instead of re-encoding it a second time.
        args += ["-map", "0:v", "-c:v", "copy"]
    args += ["-map", f"{audio_index}:a", "-c:a", "copy", "-shortest", str(out)]
    ffmpeg(args, f"{len(cards)} cards and {len(avatars)} avatar insets")


def collect(context: Context) -> dict:
    """Gather every asset the render needs, resolved to local paths."""
    from core.clients.local_store import path_for

    def local(src: str) -> str | None:
        if not src or src.startswith("http"):
            return None
        path = path_for(src)
        return str(path) if path.is_file() else None

    clips = []
    for clip in load_json_from_s3(context.clips_path)["clips"]:
        media_id = clip["media"]["id"]
        # Video Gen Clips is skipped locally, so there is no videos/ alternative to choose.
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
            clips.append({**clip, "image_path": path, "media_id": media_id})

    overlays = load_json_from_s3(context.text_overlays_path)
    cards = []
    # Text slides, then diagrams, then the conclusion: later entries stack over earlier ones.
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

    # avatar_clip is the D-ID video and is never produced locally; normally an empty list.
    avatars = [{"path": local(a.get("avatar_clip") or a.get("image") or ""),
                "start_time": a["start_time"], "end_time": a["end_time"]}
               for a in assets
               if local(a.get("avatar_clip") or a.get("image") or "")]

    return {"clips": clips, "cards": cards, "audio": audio, "avatars": avatars,
            "total": assets[-1]["end_time"] if assets else 0.0}


@with_logging_context(layer=LayerName.RENDER)
@exception_handler
def render_lesson(output_path: str, output_type: str, inputs: dict) -> dict:
    context = Context(**inputs)
    if not is_local():
        # ffmpeg reads paths, not presigned URLs, so every asset would have to come down first.
        raise RuntimeError("Local Render only runs under STORAGE=local")

    animate = bool(inputs.get("LAYER_PROGRAMMATIC_MOTION", False))
    motion_params = inputs.get("LAYER_PROGRAMMATIC_MOTION_PARAMS") or {}
    logger.info(f"Rendering locally: {context.title}")
    assets = collect(context)
    if not assets["audio"]:
        raise RuntimeError("No narration found; the Avatar Clips stage has to run first")

    segments = scene_segments(assets["clips"])
    covered = sum(duration for _, duration, _ in segments)
    logger.info(f"{len(assets['clips'])} stills, {len(assets['cards'])} cards, "
                f"{len(assets['audio'])} narration segments, {assets['total']:.0f}s "
                f"({covered:.0f}s of stills)")
    if assets["total"] - covered > 0.5:
        # Pad so -shortest doesn't cut the lesson off before the narration ends.
        segments.append((None, assets["total"] - covered, None))

    # The media path and filename the delivery tooling looks for.
    key = f"{context.media_path}{sanitize_path(context.title)}.mp4"

    with tempfile.TemporaryDirectory(prefix="local_render_") as tmp:
        base = Path(tmp) / "base.mp4"
        audio = Path(tmp) / "narration.m4a"
        video = Path(tmp) / "lesson.mp4"
        build_base(segments, base, animate=animate, motion_params=motion_params)
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
    # +y is up in the placement convention, down in ffmpeg.
    assert place(0.5, 0.0, 0.25)[3] < place(0.5, 0.0, -0.25)[3]

    # scene_segments must produce 3-tuples with correct durations and filler gaps.
    segments = scene_segments([
        {"start_time": 0.0, "end_time": 5.0, "image_path": "a.png", "media_id": "x"},
        {"start_time": 12.0, "end_time": 20.0, "image_path": "b.png", "media_id": "y"}])
    assert [s[0] for s in segments] == ["a.png", None, "b.png"], segments
    assert abs(sum(d for _, d, _ in segments) - 20.0) < 1e-6, segments
    assert abs(segments[1][1] - 7.0) < 1e-6, segments[1]
    tight = scene_segments([
        {"start_time": 0.0, "end_time": 5.0, "image_path": "a.png", "media_id": "x"},
        {"start_time": 5.0, "end_time": 9.0, "image_path": "b.png", "media_id": "y"}])
    assert [s[0] for s in tight] == ["a.png", "b.png"], tight
    assert abs(sum(d for _, d, _ in tight) - 9.0) < 1e-6, tight

    # Camera motion must use per-frame fractional sampling rather than integer crop coordinates.
    for kind in MOTIONS:
        for dur in (1.0, MAX_CLIP_SECONDS):
            n = max(1, round(dur * FPS))
            expr = camera_motion({"kind": kind, "a": ZOOM_MIN, "bx": 0.5, "by": 0.5, "n": n})
            assert "perspective=" in expr and "eval=frame" in expr and "zoompan=" not in expr, expr

    # No move may hold constant zoom across a clip, or frames come back bit-identical.
    assert ZOOM_MIN > 0 and ZOOM_MAX > ZOOM_MIN and PAN_DRIFT > 0

    # Zoom never drops below 1.0, and the crop window stays inside the source for every move.
    for kind in MOTIONS:
        for dur in (1.0, 5.0, MAX_CLIP_SECONDS):
            n = max(1, round(dur * FPS))
            for frame in (0, n // 2, max(0, n - 1)):
                if kind == "zoom_in":
                    z = 1 + ZOOM_MAX * frame / max(1, n - 1)
                elif kind == "zoom_out":
                    z = 1 + ZOOM_MAX - ZOOM_MAX * frame / max(1, n - 1)
                else:
                    z = 1 + PAN_DRIFT
                assert z >= 1.0 - 1e-9, (kind, dur, frame, z)
                assert SOURCE_W / z <= SOURCE_W + 1e-6 and SOURCE_H / z <= SOURCE_H + 1e-6

    # Same id always produces the same motion (deterministic seed).
    assert motion_for("abc", 5.0) == motion_for("abc", 5.0)


if __name__ == "__main__":
    _selfcheck()
    print("self-check ok")
