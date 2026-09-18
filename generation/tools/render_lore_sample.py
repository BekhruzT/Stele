#!/usr/bin/env python3
"""Render a lore narration sample locally with ffmpeg: `--topic silkroad`, or `--check` for wiring only."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

for _env in (ROOT / ".env", ROOT.parent / ".env"):
    if _env.is_file():
        load_dotenv(_env)
        break

import os  # noqa: E402
os.environ.setdefault("STORAGE", "local")

from core.clients.local_store import storage_root  # noqa: E402
from stages.local_render import camera_motion, motion_for, WIDTH, HEIGHT, FPS  # noqa: E402

logger = logging.getLogger("lore_sample")

# Alternate: George (audition #4) — JBFqnCBsd6RMkjVDRZzb
HOST_VOICE = "PIGsltMj3gFMR34aFDI3"          # Jarnathan Livingston (audition #10)
XFADE = 1.2                                   # crossfade between stills, seconds
SECONDS_PER_STILL = 24                        # a new establishing shot roughly this often

TRANSCRIPT_DIR = ROOT / "artifacts" / "lore_transcripts"


def transcript_path(topic: str, full: bool, override: str | None = None) -> Path:
    """Narration text for a topic: --transcript wins, else <topic>_full.txt / <topic>_cold_open.txt."""
    if override:
        return Path(override)
    name = f"{topic}_full.txt" if full else f"{topic}_cold_open.txt"
    candidates = [TRANSCRIPT_DIR / name, storage_root() / "lore_sample" / name]
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit(f"no transcript for {topic!r}: pass --transcript, or write {name} to "
                     + " or ".join(str(path.parent) for path in candidates))


# Establishing-shot prompts keyed to each cold open's imagery. FLUX; period, no lettering.
STYLE = ("Cinematic, painterly, muted natural light, shallow depth of field, historically "
         "accurate, atmospheric, highly detailed, no text, no lettering, no watermark, no people "
         "facing camera")

PROMPTS = {
    "silkroad": [
        "A ruined Han dynasty mud-brick watchtower half-buried in the pale sand of the Gobi "
        "desert at dawn, long shadows, empty vast landscape",
        "A bundle of ancient folded paper letters tied with cord, resting on weathered wood, "
        "close up, soft archival light",
        "A distant Bactrian camel caravan crossing an immense empty desert under a huge sky, "
        "tiny figures, golden afternoon haze",
        "An oasis town of flat mud-brick buildings beside a green strip of poplar trees on the "
        "edge of a desert, late day",
        "A dim carved Buddhist cave shrine at Dunhuang, faded murals on the walls, shaft of "
        "light through the entrance",
        "A quiet Tang dynasty market street at dusk with bolts of silk stacked under awnings, "
        "lanterns just lit",
    ],
    "blackdeath": [
        "Twelve medieval Genoese galleys riding low in a Sicilian harbour at grey dawn, still "
        "water, October 1347, overcast sky",
        "A narrow deserted medieval stone street in a southern Italian town, shuttered windows, "
        "pale morning light",
        "A snow-dusted Central Asian mountain valley with marmot burrows among rocks and sparse "
        "grass, cold clear light",
        "A medieval Italian town square seen from above, empty, long shadows, terracotta roofs, "
        "still and quiet",
        "An old parchment town ordinance document with a wax seal on a wooden table, candlelight, "
        "close up",
        "A walled medieval hilltop town in Tuscany at dusk, cypress trees, muted colours, no "
        "people",
    ],
    "mongol": [
        "The vast green Mongolian steppe under an enormous sky, distant felt yurts, herds of "
        "horses, summer light",
        "An ornate silver fountain shaped like a tree inside a grand medieval hall, dim golden "
        "light, richly detailed metalwork",
        "A lone Mongol relay rider galloping across open grassland at speed, low sun, dust "
        "trailing behind",
        "A carved medieval metal passport tablet with inscription resting on dark cloth, close "
        "up, museum lighting",
        "A large medieval Central Asian walled city on a plain seen from a distance at golden "
        "hour, walls and towers",
        "A cluster of white felt gers on the steppe at dusk with smoke rising, mountains behind, "
        "calm evening",
    ],
}


def cold_open(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    m = re.search(r"-+COLD OPEN-+(.*?)(?=\n-{2,}[A-Z]|\Z)", raw, re.S)
    body = (m.group(1) if m else raw).strip()
    return " ".join(body.split())


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


def chunk_text(text: str, limit: int = 2400) -> list[str]:
    """Split on sentence boundaries into pieces under the TTS per-request limit."""
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur.strip())
            cur = ""
        cur += s + " "
    if cur.strip():
        out.append(cur.strip())
    return out


def concat_audio(parts: list[Path], out: Path) -> None:
    lst = out.with_suffix(".lst")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(out)], check=True)
    lst.unlink(missing_ok=True)


def narrate(text: str, out: Path) -> float:
    """ElevenLabs, chunked past the per-request limit, with each chunk cached so a failed run resumes."""
    from core.clients.speech import add_narration_pauses, generate_speech_via_elevenlabs
    text = add_narration_pauses(text)
    chunks = chunk_text(text)
    if len(chunks) == 1:
        generate_speech_via_elevenlabs(text, str(out), HOST_VOICE, speed=0.9)
        return probe_duration(out)
    parts = []
    for i, chunk in enumerate(chunks):
        part = out.with_name(f"{out.stem}_c{i:03d}.mp3")
        if not (part.is_file() and part.stat().st_size > 1000):
            logger.info(f"  narrating chunk {i+1}/{len(chunks)}")
            generate_speech_via_elevenlabs(chunk, str(part), HOST_VOICE, speed=0.9)
        parts.append(part)
    concat_audio(parts, out)
    return probe_duration(out)


def narrate_sapi(text: str, out: Path) -> float:
    """Offline Windows SAPI stand-in, used when ElevenLabs is unavailable so visuals can still be previewed."""
    txt = out.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "try { $s.SelectVoice('Microsoft Hazel Desktop') } catch {};"
        "$s.Rate = -2;"                                   # slower, for the sleep register
        f"$s.SetOutputToWaveFile('{out}');"
        f"$t = Get-Content -Raw -Encoding UTF8 '{txt}';"
        "$s.Speak($t); $s.Dispose()"
    )
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                          capture_output=True, text=True)
    if proc.returncode or not out.is_file():
        raise RuntimeError(f"SAPI failed: {proc.stderr[-1500:]}")
    return probe_duration(out)


def _openai():
    import openai
    from core.constants import OPENAI_API_KEY, OPENAI_ORGANIZATION_ID
    return openai.OpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORGANIZATION_ID)


def make_still(prompt: str, out: Path) -> None:
    """FLUX is the production path; fall back to OpenAI images when the FAL key cannot reach it."""
    import requests
    from core.clients.images import generate_flux_image
    try:
        url = generate_flux_image(f"{prompt}. {STYLE}", width=WIDTH, height=HEIGHT)
        if url != "NSFW":
            out.write_bytes(requests.get(url, timeout=180).content)
            return
        logger.warning("FLUX refused the prompt; falling back to OpenAI")
    except Exception as exc:
        logger.warning(f"FLUX unavailable ({type(exc).__name__}); falling back to OpenAI")
    make_still_openai(prompt, out)


def make_still_openai(prompt: str, out: Path) -> None:
    import base64
    r = _openai().images.generate(model="gpt-image-1", prompt=f"{prompt}. {STYLE}",
                                  n=1, size="1536x1024", quality="low")
    d = r.data[0]
    if getattr(d, "b64_json", None):
        out.write_bytes(base64.b64decode(d.b64_json))
    else:
        import requests
        out.write_bytes(requests.get(d.url, timeout=180).content)


def narrate_openai(text: str, out: Path, voice: str = "onyx") -> float:
    """OpenAI neural TTS, chunked under the API's input limit and concatenated."""
    client = _openai()
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    chunks, cur = [], ""
    for s in sents:
        if len(cur) + len(s) + 1 > 3500:
            chunks.append(cur.strip())
            cur = ""
        cur += s + " "
    if cur.strip():
        chunks.append(cur.strip())

    parts = []
    for i, chunk in enumerate(chunks):
        part = out.with_name(f"{out.stem}_p{i}.mp3")
        with client.audio.speech.with_streaming_response.create(
                model="tts-1-hd", voice=voice, input=chunk) as resp:
            resp.stream_to_file(str(part))
        parts.append(part)

    if len(parts) == 1:
        parts[0].replace(out)
    else:
        lst = out.with_suffix(".txt")
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(out)], check=True)
    return probe_duration(out)


def pick_reuse_images(topic: str, n: int, out_dir: Path) -> list[Path]:
    """Stills already on disk, newest-first, preferring this topic; stands in for paid image generation."""
    root = storage_root()
    topical = sorted(out_dir.glob(f"{topic}_*.png"))
    other_prefixes = tuple(f"{t}_" for t in PROMPTS if t != topic)
    pool = [p for p in root.rglob("*.png")
            if p not in topical
            and not p.name.startswith(other_prefixes)  # don't borrow another topic's stills
            and p.stat().st_size > 200_000          # skip UI crops and thumbnails
            and "slide" not in p.name               # skip rendered text cards
            and p.name != "verify_frame.png"]
    pool.sort(key=lambda p: p.stat().st_size, reverse=True)
    picked = topical + pool
    if not picked:
        raise SystemExit("no reusable stills found under LOCAL_STORAGE_ROOT")
    while len(picked) < n:                          # repeat rather than fail on a small pool
        picked += picked
    return picked[:n]


def clip_durations(total: float, n: int) -> list[float]:
    """Split the audio span across n stills, each overlapping the next by XFADE."""
    base = (total + XFADE * (n - 1)) / n
    return [base] * n


def render(topic: str, params: dict, voice: str = "eleven",
           images: str = "generate", transcript: str | None = None) -> Path:
    out_dir = storage_root() / "lore_sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    text = cold_open(transcript_path(topic, full=False, override=transcript))
    logger.info(f"[{topic}] narrating {len(text.split())} words ({voice})")
    audio = out_dir / (f"{topic}.wav" if voice == "sapi" else f"{topic}.mp3")
    if audio.is_file() and audio.stat().st_size > 100_000:
        # Narration already synthesised in an earlier run -- reuse rather than pay again.
        dur = probe_duration(audio)
        logger.info(f"[{topic}] reusing existing narration {audio.name}")
    elif voice == "sapi":
        dur = narrate_sapi(text, audio)
    elif voice == "openai":
        dur = narrate_openai(text, audio)
    else:
        dur = narrate(text, audio)
    logger.info(f"[{topic}] audio {dur:.1f}s")

    prompts = PROMPTS[topic]
    n = max(3, min(len(prompts), round(dur / SECONDS_PER_STILL)))
    prompts = prompts[:n]
    durs = clip_durations(dur, n)

    if images == "reuse":
        stills = pick_reuse_images(topic, n, out_dir)
        logger.info(f"[{topic}] reusing {len(stills)} stills already on disk")
    else:
        stills = []
        for i, prompt in enumerate(prompts):
            img = out_dir / f"{topic}_{i}.png"
            if not img.is_file():
                logger.info(f"[{topic}] still {i+1}/{n}")
                make_still(prompt, img)
            stills.append(img)
    n = len(stills)
    durs = clip_durations(dur, n)

    # One pass: animate each still for its span, xfade the chain, mux the narration.
    inputs: list[str] = []
    for img, d in zip(stills, durs):
        inputs += ["-loop", "1", "-t", f"{d:.3f}", "-i", str(img)]
    inputs += ["-i", str(audio)]

    parts = []
    for i, (img, d) in enumerate(zip(stills, durs)):
        move = motion_for(f"{topic}-{i}", d, params)
        parts.append(f"[{i}:v]{camera_motion(move)},format=yuv420p[v{i}]")
    chain = ""
    prev = "v0"
    offset = 0.0
    for i in range(1, n):
        offset += durs[i - 1] - XFADE
        label = f"x{i}" if i < n - 1 else "vout"
        chain += (f"[{prev}][v{i}]xfade=transition=fade:duration={XFADE}:"
                  f"offset={offset:.3f}[{label}];")
        prev = label
    filt = ";".join(parts) + ";" + chain.rstrip(";")
    if n == 1:
        filt = f"[0:v]{camera_motion(motion_for(topic, durs[0], params))},format=yuv420p[vout]"

    out = out_dir / f"{topic}.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs,
           "-filter_complex", filt,
           "-map", "[vout]", "-map", f"{n}:a",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)]
    logger.info(f"[{topic}] compositing {n} stills")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr[-3000:])
    logger.info(f"[{topic}] wrote {out} ({probe_duration(out):.1f}s)")
    return out


FULL_STILL_SECONDS = 10       # 540 visual cuts over 90 minutes; unique assets are reused below
FADE = 0.6                    # gentle dip between stills
MAX_FULL_STILLS = 100
MIN_REUSE_SECONDS = 180


def timeline_chunks(text: str, n: int) -> list[str]:
    """Split narration into equal timeline slots for image prompting and comparison."""
    words = text.split()
    return [" ".join(words[round(i * len(words) / n):round((i + 1) * len(words) / n)])
            for i in range(n)]


def cosine(a: list[float], b: list[float]) -> float:
    """Return cosine similarity for two embedding vectors."""
    denominator = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else 0.0


def assign_timeline_assets(vectors: list[list[float]], asset_vectors: list[list[float]],
                           duration: float) -> tuple[list[int], list[dict]]:
    """Match every visual cut to the best available asset outside the reuse cooldown."""
    assignments: list[int] = []
    slots = []
    uses = [0] * len(asset_vectors)
    last_seen = [-float("inf")] * len(asset_vectors)
    slot_seconds = duration / len(vectors)
    for index, vector in enumerate(vectors):
        start = index * slot_seconds
        eligible = [(cosine(vector, candidate) - 0.005 * uses[asset_id], asset_id)
                    for asset_id, candidate in enumerate(asset_vectors)
                    if start - last_seen[asset_id] >= MIN_REUSE_SECONDS]
        _, asset_id = max(eligible)
        similarity = cosine(vector, asset_vectors[asset_id])
        reused = uses[asset_id] > 0
        uses[asset_id] += 1
        last_seen[asset_id] = start
        assignments.append(asset_id)
        slots.append({"index": index, "start_seconds": round(start, 3), "duration_seconds": round(slot_seconds, 3),
                      "asset_id": asset_id, "reused": reused, "similarity": round(similarity, 4)})
    verified: dict[int, float] = {}
    for index, asset_id in enumerate(assignments):
        start = index * slot_seconds
        assert asset_id not in verified or start - verified[asset_id] >= MIN_REUSE_SECONDS
        verified[asset_id] = start
    return assignments, slots


def semantic_image_schedule(topic: str, text: str, duration: float,
                            out_dir: Path) -> tuple[list[Path], list[int]]:
    """Reuse semantically matching stills while enforcing count and spacing limits."""
    images_dir = out_dir / f"{topic}_full_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / f"{topic}_full_image_manifest.json"
    transcript_hash = hashlib.sha256(text.encode()).hexdigest()
    old_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    if (old_manifest.get("transcript_sha256") == transcript_hash
            and old_manifest.get("assets")
            and all((images_dir / f"{asset['id']:03d}.png").is_file() for asset in old_manifest["assets"])):
        asset_prompts = [asset["prompt"] for asset in old_manifest["assets"]]
        logger.info(f"[{topic}] reusing {len(asset_prompts)} generated GPT stills")
    else:
        asset_prompts = timeline_chunks(text, min(MAX_FULL_STILLS, max(1, round(duration / FULL_STILL_SECONDS))))
    chunks = timeline_chunks(text, max(1, round(duration / FULL_STILL_SECONDS)))
    embedded = _openai().embeddings.create(
        model="text-embedding-3-small", input=asset_prompts + chunks, dimensions=256).data
    asset_vectors = [item.embedding for item in embedded[:len(asset_prompts)]]
    vectors = [item.embedding for item in embedded[len(asset_prompts):]]
    assignments, slots = assign_timeline_assets(vectors, asset_vectors, duration)
    assets = [{"id": asset_id, "prompt": prompt} for asset_id, prompt in enumerate(asset_prompts)]
    assert len(assets) <= MAX_FULL_STILLS

    def render_asset(asset: dict) -> Path:
        path = images_dir / f"{asset['id']:03d}.png"
        if not (path.is_file() and path.stat().st_size > 100_000):
            prompt = ("Create one quiet, non-graphic historical establishing shot from the narration excerpt below. "
                      "Choose its single most concrete named person, place, object, or action; do not combine different "
                      f"moments into a collage. Narration excerpt: {asset['prompt']}")
            logger.info(f"[{topic}] GPT still {asset['id'] + 1}/{len(assets)}")
            make_still_openai(prompt, path)
        return path

    with ThreadPoolExecutor(max_workers=4) as pool:
        unique_paths = list(pool.map(render_asset, assets))
    manifest = {
        "transcript_sha256": transcript_hash,
        "duration_seconds": round(duration, 3),
        "visual_clip_seconds": FULL_STILL_SECONDS,
        "slot_count": len(chunks),
        "unique_image_count": len(assets),
        "max_unique_images": MAX_FULL_STILLS,
        "minimum_reuse_seconds": MIN_REUSE_SECONDS,
        "assets": assets,
        "slots": slots,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return [unique_paths[asset_id] for asset_id in assignments], assignments


def render_full(topic: str, params: dict, transcript: str | None = None) -> Path:
    out_dir = storage_root() / "lore_sample"
    parts_dir = out_dir / f"{topic}_full_parts_{FULL_STILL_SECONDS}s"
    parts_dir.mkdir(parents=True, exist_ok=True)
    full_txt = transcript_path(topic, full=True, override=transcript)
    text = "\n\n".join(" ".join(paragraph.split()) for paragraph in re.split(
        r"\n\s*\n+", full_txt.read_text(encoding="utf-8")) if paragraph.strip())
    logger.info(f"[{topic}] full narration {len(text.split())} words")

    audio = out_dir / f"{topic}_full_paced.mp3"
    dur = audio_or_narrate(topic, text, audio)
    logger.info(f"[{topic}] audio {dur/60:.1f} min")

    stills, _ = semantic_image_schedule(topic, text, dur, out_dir)
    n = len(stills)
    durs = [dur / n] * n
    rendered: dict[Path, Path] = {}
    unique_stills = list(dict.fromkeys(stills))
    for i, img in enumerate(unique_stills):
        d = durs[0]
        clip = parts_dir / f"{img.stem}.mp4"
        rendered[img] = clip
        if clip.is_file() and clip.stat().st_size > 1000:
            continue
        move = motion_for(f"{topic}-{img.stem}", d, params)
        frames = move["n"]
        vf = (camera_motion(move) +
              f",fade=t=in:st=0:d={FADE},fade=t=out:st={d - FADE:.3f}:d={FADE}")
        ffmpeg_run(["-loop", "1", "-t", f"{d:.3f}", "-i", str(img),
                    "-vf", vf, "-frames:v", str(frames),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-pix_fmt", "yuv420p", "-r", str(FPS), str(clip)],
                   f"[{topic}] still {i+1}/{len(unique_stills)}")

    clips = [rendered[img] for img in stills]
    concat_lst = parts_dir / "concat.lst"
    concat_lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    silent = out_dir / f"{topic}_full_silent.mp4"
    ffmpeg_run(["-f", "concat", "-safe", "0", "-i", str(concat_lst), "-c", "copy", str(silent)],
               f"[{topic}] concat {n} clips")

    out = out_dir / f"{topic}_full.mp4"
    ffmpeg_run(["-i", str(silent), "-i", str(audio), "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)],
               f"[{topic}] mux audio")
    logger.info(f"[{topic}] wrote {out} ({probe_duration(out)/60:.1f} min)")
    return out


def audio_or_narrate(topic: str, text: str, audio: Path) -> float:
    if audio.is_file() and audio.stat().st_size > 100_000:
        logger.info(f"[{topic}] reusing existing narration {audio.name}")
        return probe_duration(audio)
    return narrate(text, audio)


def ffmpeg_run(args: list[str], label: str) -> None:
    logger.info(label)
    proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                          capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"ffmpeg failed ({label}):\n{proc.stderr[-2000:]}")


def lore_params() -> dict:
    cfg = json.loads((ROOT / "config" / "video_types.json").read_text(encoding="utf-8"))
    return cfg["lore"]["params"]["LAYER_PROGRAMMATIC_MOTION"]


def _check() -> None:
    p = lore_params()
    assert {"zoom_min", "zoom_max", "pan_drift"} <= p.keys(), p
    for t, prompts in PROMPTS.items():
        assert len(prompts) >= 3, t
    move = motion_for("x", 24.0, p)
    assert "perspective=" in camera_motion(move)
    durs = clip_durations(120.0, 5)
    assert abs(sum(durs) - XFADE * 4 - 120.0) < 0.01, durs
    print("self-check ok; lore motion params:", p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", action="append",
                    help=f"names the transcript and the still prompts; cold open needs one of "
                         f"{', '.join(sorted(PROMPTS))}")
    ap.add_argument("--transcript", help="narration text to read, overriding the --topic lookup")
    ap.add_argument("--voice", choices=["eleven", "openai", "sapi"], default="eleven")
    ap.add_argument("--images", choices=["generate", "reuse"], default="generate")
    ap.add_argument("--full", action="store_true",
                    help="render the complete ~60 min narration, not just the cold open")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _check()
    if args.check:
        return 0
    params = lore_params()
    for topic in (args.topic or ["silkroad"]):
        if args.full:
            render_full(topic, params, args.transcript)
        else:
            if topic not in PROMPTS:
                ap.error(f"{topic} has no still prompts; use --full or pick one of {', '.join(sorted(PROMPTS))}")
            render(topic, params, args.voice, args.images, args.transcript)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
