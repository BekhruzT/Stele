#!/usr/bin/env python3
"""Composite a lesson with ffmpeg instead of ShotStack, on real generated content.

ShotStack renders from public URLs -- every asset is presigned before submission -- which is
the whole reason local mode has to skip it. ffmpeg reads local paths, so it needs no bucket,
no presigning and no vendor account. This narrates two slices of the transcript we already
generated, renders two templates through the existing Playwright path, and composites them
over a generated still in one filter_complex.

This is a spike, not the stage. It stands in for stage 6 by deriving overlay data from the
speech clock itself, where the real Text Overlays stage asks an LLM to match phrases against
the whole lesson. The three numbers that decide whether the result looks alive are the same
either way, and getting them wrong is what makes a render look broken:

  * TextSlidePhrase.start_duration is how long the typewriter takes to reveal a phrase.
    It has to be the phrase's spoken length, or the text finishes early and sits there.
  * TextSlidePhrase.start_time has to be when that phrase is actually said.
  * A card's clip must outlast its last reveal, or the reveal lands past the final frame.

    python tools/spike_render.py            # the real thing, costs a few cents
    python tools/spike_render.py --check    # offline self-checks only

Writes tmp/spike/lesson.mp4.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

for _env in (ROOT / ".env", ROOT.parent / ".env"):
    if _env.is_file():
        load_dotenv(_env)
        break
os.environ.setdefault("STORAGE", "local")

from core.clients.local_store import path_for, storage_root  # noqa: E402
from core.media.html_to_video import convert_html_to_video, staged_page  # noqa: E402

logger = logging.getLogger("spike")

WIDTH, HEIGHT, FPS = 1280, 720, 30

LESSON = ("college_board/AP US History: Video Lessons/AP US History - v2"
          "/contents/subsection/Video Transcript/1c156641.json")

# ShotStack's placement for the talking head, copied from ::generate_avatar_tracks.
AVATAR_SCALE, AVATAR_X, AVATAR_Y = 0.148, 0.41, -0.24

# ElevenLabs' host voice, the default stages/avatar_clips.py uses for the narrator.
HOST_VOICE = "IKne3meq5aSn9XLyUdCD"

# Sentences narrated per segment. Bounds both the spend and the render: html_to_mov takes one
# screenshot per frame, so a card costs its duration * 30 screenshots.
MAX_SENTENCES = 3

# Seconds of image-only lead-in before the first card. Without a gap the cards are opaque
# full-frame and the still would never be seen -- which is how the real pipeline works too,
# where the visual track shows between overlay windows rather than under them.
LEAD_IN = 3.5


def place(scale: float, x: float, y: float, w: int = WIDTH, h: int = HEIGHT):
    """Convert one ShotStack asset placement into ffmpeg overlay arguments.

    The two systems disagree twice. ShotStack sizes an asset as a fraction of the output and
    positions it by its centre, with offsets in fractions of the output and +y pointing up;
    ffmpeg's overlay takes pixels and positions by the top-left corner with +y pointing down.

    Returns (width, height, x, y) in pixels.
    """
    cw, ch = round(w * scale), round(h * scale)
    cx, cy = (0.5 + x) * w, (0.5 - y) * h
    return cw, ch, round(cx - cw / 2), round(cy - ch / 2)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def time_sentences(lines: list[str], timings) -> list[tuple[str, float, float]]:
    """Pair each sentence with when it starts and how long it is spoken for.

    The duration is the point of this function. A phrase whose start_duration is a flat 1.0
    types itself out in one second and then waits, which reads as a pop rather than as
    narration; using the spoken span makes the typewriter track the voice.

    ponytail: aligns by word count rather than by matching text, sound only because the
    timings come from synthesising these exact sentences. The real stage matches on
    WordTiming.text because it works against the whole lesson transcript.
    """
    out, i = [], 0
    for line in lines:
        if i >= len(timings):
            break
        words = len(line.split())
        last = timings[min(i + words, len(timings)) - 1]
        out.append((line, timings[i].start_time, last.end_time - timings[i].start_time))
        i += words
    return out


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


def build_text_slide(title: str, timed: list[tuple[str, float, float]], end: float,
                     visual: dict | None = None) -> dict:
    """The shape templates/text_slide.html expects, i.e. TextSlide.model_dump()."""
    return {
        "title": title,
        "start_time": 0.0,
        "end_time": end,
        "start_index": 0,
        "end_index": 0,
        "visuals": [visual] if visual else None,
        "elements": [
            {"type": "text",
             "contents": [{"content": line, "phrase": line, "start_index": 0,
                           "start_time": round(start, 3),
                           "start_duration": round(span, 3)}]}
            for line, start, span in timed
        ],
    }


def build_mind_map(slide: dict, span: float) -> dict:
    """The shape templates/diagrams/mind_map.html expects, from the conclusion slide the
    transcript stage wrote. The template lays out 2 to 5 categories.

    The start times are spread across the whole clip rather than crammed into its first
    seconds, which is what made the map look frozen: it finished building in 3 seconds of a
    10 second card. The real stage derives these from the narration's word timings.
    """
    bullets = slide.get("bullets", [])[:5]
    if not bullets:
        raise SystemExit("conclusion_slide has no bullets to build a mind map from")
    # Leave a beat at the end so the finished map is readable before the card cuts.
    step = max(span - 1.5, 0.5) / len(bullets)
    return {
        "start_phrase": "",
        "start_time": 0,
        "visuals": None,
        "is_section": False,
        "root": {"title": slide.get("title", "Summary"), "icon": "landmark"},
        "categories": [
            {"title": {"text": b["text"], "icon": "flag", "phrase": "",
                       "start_time": round(i * step, 2)},
             "points": [{"text": p["text"], "icon": "", "phrase": "",
                         "start_time": round(i * step + step * (j + 1) / 4, 2)}
                        for j, p in enumerate(b.get("sub_points", [])[:3])]}
            for i, b in enumerate(bullets)
        ],
    }


def render(template: str, data: dict, out: Path, duration: float) -> None:
    """Render a template to a clip, the same pair of calls stages 5 and 6 make."""
    with staged_page(template, data, out.stem) as page:
        convert_html_to_video(page, str(out), duration)


def composite(still: Path, slide: Path, mind_map: Path, audio: list[Path],
              first: float, total: float, out: Path) -> None:
    """One filter_complex doing what ShotStack's seven track builders do.

    The still runs underneath for the whole lesson; each card covers it during its own
    window; the avatar inset sits in ShotStack's exact position; the segment narrations are
    concatenated into the single audio track.
    """
    pw, ph, px, py = place(AVATAR_SCALE, AVATAR_X, AVATAR_Y)
    graph = (
        f"[0:v]scale={WIDTH}:{HEIGHT},fps={FPS}[bg];"
        # setpts moves a clip to its slot; enable gates it there. Without enable the clip's
        # last frame would persist to the end of the render.
        f"[1:v]setpts=PTS-STARTPTS+{LEAD_IN}/TB[slide];"
        f"[bg][slide]overlay=0:0:enable='between(t,{LEAD_IN},{first})'[a];"
        f"[2:v]split=2[mm][pip];"
        f"[mm]setpts=PTS-STARTPTS+{first}/TB[mmd];"
        f"[a][mmd]overlay=0:0:enable='gte(t,{first})'[b];"
        # Nothing has generated a talking head locally, so the inset is the mind map standing
        # in for one. The placement is what is under test, not the content.
        f"[pip]scale={pw}:{ph},setpts=PTS-STARTPTS[pips];"
        f"[b][pips]overlay={px}:{py}:enable='between(t,{LEAD_IN},{first})'[v];"
        f"[3:a][4:a]concat=n=2:v=0:a=1[aout]"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-loop", "1", "-t", str(total), "-i", str(still),
           "-i", str(slide), "-i", str(mind_map),
           *sum((["-i", str(a)] for a in audio), []),
           "-filter_complex", graph,
           "-map", "[v]", "-map", "[aout]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
           "-c:a", "aac", "-shortest", str(out)]
    subprocess.run(cmd, check=True)


def narrate(text: str, out: Path) -> tuple[list, float]:
    from core.clients.speech import generate_speech_via_elevenlabs

    timings, _ = generate_speech_via_elevenlabs(text, str(out), HOST_VOICE)
    return timings, probe_duration(out)


def make_still(prompt: str, out: Path) -> None:
    import requests

    from core.clients.images import generate_flux_image

    url = generate_flux_image(prompt, width=WIDTH, height=HEIGHT)
    if url == "NSFW":
        raise SystemExit("FLUX refused the prompt")
    out.write_bytes(requests.get(url, timeout=120).content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run the self-checks and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _selfcheck()
    if args.check:
        print("self-check ok")
        return 0

    transcript_path = path_for(LESSON)
    if not transcript_path.is_file():
        logger.error(f"No transcript at {transcript_path}\n"
                     f"Run: python run.py --until 'Video Transcript'")
        return 1

    breakdown = json.loads(transcript_path.read_text(encoding="utf-8"))["lesson_transcript_breakdown"]
    out_dir = storage_root() / "spike"
    out_dir.mkdir(parents=True, exist_ok=True)

    intro = sentences(breakdown["introduction"])[:MAX_SENTENCES]
    outro = sentences(breakdown["conclusion"])[:MAX_SENTENCES]

    logger.info("Narrating the introduction")
    intro_audio = out_dir / "intro.mp3"
    intro_timings, d1 = narrate(" ".join(intro), intro_audio)

    logger.info("Narrating the conclusion")
    outro_audio = out_dir / "outro.mp3"
    _, d2 = narrate(" ".join(outro), outro_audio)

    total = round(d1 + d2, 2)
    timed = time_sentences(intro, intro_timings)
    last_reveal = timed[-1][1] + timed[-1][2]
    logger.info(f"Intro {d1:.1f}s, conclusion {d2:.1f}s, last reveal ends {last_reveal:.1f}s")
    if last_reveal > d1 + 0.5:
        logger.warning("Last reveal runs past the intro audio; the card will outlast it")

    still = out_dir / "still.png"
    logger.info("Generating the establishing still with FLUX")
    make_still(
        "Cinematic oil painting, 16th century European sailing caravels on the open Atlantic "
        "at golden hour, dramatic clouds, antique nautical chart tones, highly detailed, "
        "no text, no lettering",
        still)

    # The in-slide image: the same still, shown inside the card. This is the visuals mechanism
    # the real Text Overlays stage fills from Image Gen Clips.
    from core.helpers import image_to_data_uri

    visual = {"src": image_to_data_uri(str(still)),
              "caption": "European caravels crossing the Atlantic",
              "fact": "", "phrase": "",
              "start_time": round(timed[-1][1], 2) if len(timed) > 1 else 1.0,
              "end_time": round(d1 - LEAD_IN, 2)}

    slide_mov, mind_mov = out_dir / "text_slide.mov", out_dir / "mind_map.mov"
    title = next(iter(breakdown["sections"]), "Introduction")

    logger.info(f"Rendering the text slide, {LEAD_IN}s to {d1:.1f}s")
    render("text_slide.html",
           build_text_slide(title, timed, d1 - LEAD_IN, visual),
           slide_mov, d1 - LEAD_IN)

    logger.info(f"Rendering the mind map, {d1:.1f}s to {total:.1f}s")
    render("diagrams/mind_map.html",
           build_mind_map(breakdown["conclusion_slide"], d2),
           mind_mov, d2)

    out = out_dir / "lesson.mp4"
    logger.info("Compositing")
    composite(still, slide_mov, mind_mov, [intro_audio, outro_audio], round(d1, 2), total, out)

    logger.info(f"\n{out}  ({probe_duration(out):.1f}s, {out.stat().st_size // 1024} KB)")
    return 0


def _check_staging() -> None:
    """staged_page writes into templates/, so it must not be able to eat a template.

    It could: naming the scratch page after the asset id meant an id of 'text_slide'
    overwrote text_slide.html and then deleted it on the way out.
    """
    from core.media.html_to_video import SCRATCH, TEMPLATES, staged_page

    real = Path(TEMPLATES) / "text_slide.html"
    assert real.is_file(), f"{real} is missing"
    before = real.read_bytes()

    data = build_text_slide("t", [("a", 0.0, 1.0)], 1.0)
    with staged_page("text_slide.html", data, "text_slide") as page:
        assert Path(page).name.startswith(SCRATCH), page
        assert Path(page).resolve() != real.resolve()
        assert real.read_bytes() == before
    assert not Path(page).exists(), "scratch page left behind"
    assert real.read_bytes() == before

    try:
        with staged_page("text_slide.html", data, "x") as first:
            Path(first).touch()
            with staged_page("text_slide.html", data, "x"):
                raise AssertionError("reused a live scratch name")
    except FileExistsError:
        pass


def _check_timings() -> None:
    """The reveal numbers, which is what made the first render look broken."""
    class T:
        def __init__(self, start, end):
            self.start_time, self.end_time = start, end

    lines = ["One two three.", "Four five."]
    timings = [T(0.0, 1.0), T(1.0, 2.0), T(2.0, 3.0), T(3.0, 4.0), T(4.0, 5.5)]
    timed = time_sentences(lines, timings)
    assert len(timed) == 2, timed
    # Each sentence starts when its first word does and lasts until its last word ends, so
    # the typewriter spans the speech instead of finishing in a flat second.
    assert timed[0] == ("One two three.", 0.0, 3.0), timed[0]
    assert timed[1] == ("Four five.", 3.0, 2.5), timed[1]
    assert all(span > 0 for _, _, span in timed)

    slide = build_text_slide("t", timed, 5.5)
    phrases = [e["contents"][0] for e in slide["elements"]]
    assert [p["start_duration"] for p in phrases] == [3.0, 2.5]
    # Every reveal has to finish inside the clip, or it never reaches a frame.
    assert all(p["start_time"] + p["start_duration"] <= slide["end_time"] + 1e-6
               for p in phrases), phrases

    # The mind map has to keep animating across its whole card, not just the opening seconds.
    conclusion = {"title": "T", "bullets": [{"text": f"b{i}", "sub_points": [{"text": "p"}]}
                                            for i in range(3)]}
    span = 12.0
    starts = [c["title"]["start_time"] for c in build_mind_map(conclusion, span)["categories"]]
    assert starts == sorted(starts) and starts[0] == 0.0, starts
    assert starts[-1] > span / 2, f"map finishes building in the first half: {starts}"
    assert starts[-1] < span, starts


def _selfcheck() -> None:
    _check_staging()
    _check_timings()

    cw, ch, cx, cy = place(AVATAR_SCALE, AVATAR_X, AVATAR_Y)
    assert (cw, ch) == (189, 107), (cw, ch)
    # x=0.41 is right of centre and y=-0.24 is below it, so the head sits bottom-right and
    # stays inside the frame.
    assert cx + cw <= WIDTH and cy + ch <= HEIGHT, (cx, cy)
    assert cx > WIDTH / 2 and cy > HEIGHT / 2, (cx, cy)
    # A full-frame asset is the identity case: no scaling, no offset.
    assert place(1.0, 0.0, 0.0) == (WIDTH, HEIGHT, 0, 0)
    # +y is up in ShotStack, so a positive y must land above centre in ffmpeg's coordinates.
    assert place(0.5, 0.0, 0.25)[3] < place(0.5, 0.0, -0.25)[3]


if __name__ == "__main__":
    sys.exit(main())
