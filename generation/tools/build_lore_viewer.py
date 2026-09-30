#!/usr/bin/env python3
"""Build a self-contained HTML viewer over the generations tree.

Layout it reads, three levels deep, with nothing else assumed:

    generations/<subject>/<video>/<run-id>/
        full.txt            the complete transcript shown in this viewer
        full.mp3            narration, matched to the transcript
        meta.json           optional: title, chapter, note, content_subject, narration_profile

Folders supply defaults; content_subject can correct legacy filing without moving archived runs.
Hook trials, opening samples and review notes stay on disk but do not create viewer run tabs.
Topics that only have samples remain visible with an explicit missing-full-transcript state.
The writing profile does not determine the subject tab. Transcripts are embedded because file:// may not fetch a
sibling file; audio stays a relative path, which file:// does allow for media elements.

    build_lore_viewer.py                 build once
    build_lore_viewer.py --watch         rebuild whenever anything under the tree changes
    build_lore_viewer.py --selftest      build a throwaway tree and check the scan
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "generations"
AUDIO_SUFFIXES = (".mp3", ".m4a", ".wav", ".ogg", ".opus")
WPM = 150
STOPWORDS = {"a", "an", "the", "of", "in", "on", "at", "was", "were", "that", "is", "and", "to",
             "for", "with", "from", "by", "it", "its", "as", "into", "this"}


def short_slug(title: str, words: int = 2) -> str:
    """A 1-2 word folder name for a video, from its title: "The Letter That Split the Atom" -> letter-split."""
    kept = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOPWORDS]
    return "-".join((kept or ["untitled"])[:words])


def run_dir(subject: str, title: str, root: Path = ROOT, run_id: str | None = None) -> Path:
    """Where one generation run belongs: generations/<subject>/<video>/<run-id>/."""
    return root / short_slug(subject, 1) / short_slug(title) / (
        run_id or datetime.now().strftime("%Y%m%d-%H%M%S"))


def titleize(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").strip().title()


def paragraphs(text: str) -> list[str]:
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n+", text) if p.strip()]


def relative_url(path: Path, root: Path) -> str:
    """A file:// safe relative href from the viewer, which is written at the root."""
    return "/".join(quote(part) for part in path.relative_to(root).parts)


def read_documents(run: Path, root: Path) -> list[dict]:
    """Only the complete transcript; auxiliary text files never become document tabs."""
    audio = sorted(p for p in run.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)
    transcripts = [run / "full.txt"] if (run / "full.txt").is_file() else []
    # One transcript and one recording can only mean each other. With more of either, a recording
    # goes to the transcript whose stem it shares and to no other, or it would play under the wrong one.
    lone = audio[0] if len(audio) == 1 and len(list(run.glob("*.txt"))) == 1 else None
    documents = []
    for path in transcripts:
        body = paragraphs(path.read_text(encoding="utf-8", errors="replace"))
        words = sum(len(p.split()) for p in body)
        match = next((a for a in audio if a.stem == path.stem), lone)
        documents.append({
            "name": titleize(path.stem),
            "words": words,
            "minutes": max(1, round(words / WPM)),
            "paragraphs": body,
            "audio": relative_url(match, root) if match else None,
            "expected_audio": f"{path.stem}.mp3",
        })
    return documents


def run_timestamp(run: Path, meta: dict) -> float:
    """Custom run names must not sort an older pilot above a later revision."""
    if value := meta.get("created_at"):
        try:
            return datetime.fromisoformat(value).timestamp()
        except (TypeError, ValueError):
            pass
    if match := re.match(r"^(\d{8}-\d{6})(?:$|-)", run.name):
        try:
            return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").timestamp()
        except ValueError:
            pass
    return run.stat().st_ctime


def collect(root: Path) -> list[dict]:
    """Group by content subject, keeping alternate writing profiles visibly labelled."""
    grouped = {}
    for subject_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for video_dir in sorted(p for p in subject_dir.iterdir() if p.is_dir()):
            for run in sorted((p for p in video_dir.iterdir() if p.is_dir()), reverse=True):
                if not any(run.glob("*.txt")):
                    continue
                documents = read_documents(run, root)
                meta = {}
                if (meta_path := run / "meta.json").is_file():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        meta = {}
                subject = short_slug(meta.get("content_subject") or subject_dir.name, 1)
                profile = short_slug(meta.get("narration_profile") or subject_dir.name, 1)
                alternate = profile != subject
                videos = grouped.setdefault(subject, {})
                video = videos.setdefault(video_dir.name, {
                    "title": titleize(video_dir.name), "chapter": "", "runs": []})
                video["title"] = meta.get("title", video["title"])
                video["chapter"] = meta.get("chapter", video["chapter"])
                if not documents:
                    continue
                note = meta.get("note", "")
                if alternate:
                    note = f"Alternate version using the {titleize(profile)} writing profile. " + note
                video["runs"].append({
                    "_sort": run_timestamp(run, meta),
                    "alternate_profile": alternate,
                    "id": run.name,
                    "label": run.name + (f" ({titleize(profile)} style)" if alternate else ""),
                    "note": note,
                    "when": datetime.fromtimestamp(run.stat().st_mtime).strftime("%d %b %H:%M"),
                    "documents": documents,
                })
    subjects = []
    for subject, videos in sorted(grouped.items()):
        for video in videos.values():
            # Keep the subject's own latest run as the default; experiments remain available.
            video["runs"].sort(key=lambda r: (r["alternate_profile"], -r["_sort"]))
            for item in video["runs"]:
                del item["_sort"]
        subjects.append({"label": titleize(subject),
                         "videos": [video for _, video in sorted(videos.items())]})
    return subjects


CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#0f1115; --panel:#161922; --panel-2:#1c2029; --line:#272c38;
  --ink:#e8e6e1; --dim:#9aa1ae; --accent:#c9a227; --accent-soft:#c9a2271a;
  --radius:10px;
}
html,body{margin:0;height:100%}
body{
  background:var(--bg); color:var(--ink);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  display:flex; justify-content:center; padding:32px 20px 64px;
}
.app{width:100%; max-width:860px}
header{margin-bottom:20px; display:flex; justify-content:space-between; align-items:flex-start; gap:16px}
h1{font-size:20px; font-weight:600; margin:0 0 4px}
.sub{color:var(--dim); font-size:13.5px; margin:0}
.live{color:var(--dim); font-size:12.5px; display:flex; align-items:center; gap:6px; white-space:nowrap}
.live input{accent-color:var(--accent)}
.tabs{display:flex; gap:4px; flex-wrap:wrap}
.tab{
  appearance:none; border:1px solid transparent; background:transparent; color:var(--dim);
  font:inherit; font-size:14px; padding:8px 14px; border-radius:var(--radius);
  cursor:pointer; transition:background .15s,color .15s,border-color .15s;
}
.tab:hover{color:var(--ink); background:var(--panel)}
.tab[aria-selected=true]{color:var(--ink); background:var(--panel); border-color:var(--line)}
.tabs.subject{margin-bottom:12px}
.tabs.subject .tab[aria-selected=true]{
  color:var(--accent); border-color:var(--accent); background:var(--accent-soft);
}
.tab:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.tabs.video{
  background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
  padding:4px; margin-bottom:14px;
}
.tabs.video .tab{flex:1 1 auto; text-align:center; font-size:13.5px}
.tabs.video .tab[aria-selected=true]{background:var(--panel-2)}
.tabs.run{margin-bottom:14px}
.tabs.run .tab{font-size:12.5px; padding:5px 10px; font-family:ui-monospace,Menlo,Consolas,monospace}
.meta{display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; margin-bottom:6px}
h2{font-size:18px; font-weight:600; margin:0}
.chapter{color:var(--dim); font-size:13px; margin:0 0 14px}
.stats{color:var(--dim); font-size:12.5px; letter-spacing:.02em}
.note{color:var(--accent); font-size:12.5px; margin:0 0 12px}
.player{
  background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
  padding:12px; margin-bottom:22px;
}
.player audio{width:100%; display:block}
.player.empty{color:var(--dim); font-size:13px; padding:14px 16px}
.player.empty code{
  color:var(--ink); background:var(--panel-2); border-radius:4px; padding:1px 5px; font-size:12px;
}
article{font-family:Georgia,"Iowan Old Style",'Times New Roman',serif; font-size:17px; line-height:1.78}
article p{margin:0 0 1.15em; text-wrap:pretty}
article p:first-of-type::first-letter{
  font-size:2.6em; line-height:.9; float:left; padding:4px 10px 0 0; color:var(--accent);
}
.empty-state{color:var(--dim); padding:40px 0}
footer{margin-top:40px; color:var(--dim); font-size:12px; border-top:1px solid var(--line); padding-top:14px}
@media (max-width:640px){
  body{padding:20px 14px 48px}
  header{flex-direction:column}
  .tabs.video{flex-direction:column}
  article{font-size:16px}
}
@media (prefers-reduced-motion:reduce){.tab{transition:none}}
"""

JS = """
const DATA = __DATA__, BUILT = "__BUILT__";
const app = document.getElementById('app');

const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// The path lives in the hash so the auto-reload below lands back where you were reading.
let at = (location.hash.slice(1).split('/').map(Number).filter(n => !isNaN(n)).concat([0,0,0,0])).slice(0,4);

function clampPath() {
  const sub = DATA[at[0] = Math.max(0, Math.min(at[0], DATA.length - 1))];
  const vid = sub.videos[at[1] = Math.max(0, Math.min(at[1], sub.videos.length - 1))];
  if (!vid.runs.length) {
    at[2] = at[3] = 0;
    return [sub, vid, null, null];
  }
  const run = vid.runs[at[2] = Math.max(0, Math.min(at[2], vid.runs.length - 1))];
  at[3] = 0;
  return [sub, vid, run, run.documents[at[3]]];
}

function tabs(kind, labels, active, onPick) {
  const wrap = document.createElement('div');
  wrap.className = 'tabs ' + kind;
  wrap.role = 'tablist';
  wrap.setAttribute('aria-label', kind);
  labels.forEach((label, i) => {
    const b = document.createElement('button');
    b.className = 'tab';
    b.type = 'button';
    b.role = 'tab';
    b.textContent = label;
    b.setAttribute('aria-selected', String(i === active));
    b.setAttribute('aria-controls', 'panel');
    b.tabIndex = i === active ? 0 : -1;
    b.addEventListener('click', () => onPick(i));
    wrap.append(b);
  });
  wrap.addEventListener('keydown', e => {
    const step = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[e.key];
    if (!step) return;
    e.preventDefault();
    const all = [...wrap.querySelectorAll('.tab')];
    all[(active + step + all.length) % all.length].click();
  });
  return wrap;
}

function go(level, i) {
  at[level] = i;
  for (let d = level + 1; d < 4; d++) at[d] = 0;
  render();
}

function render() {
  if (!DATA.length) {
    app.innerHTML = '<p class="empty-state">No generations yet. Run a transcript and rebuild.</p>';
    return;
  }
  const [sub, vid, run, doc] = clampPath();
  location.replace('#' + at.join('/'));
  app.replaceChildren();

  const head = document.createElement('header');
  head.innerHTML = '<div><h1>Full transcripts</h1><p class="sub">Built ' + esc(BUILT) + '</p></div>'
    + '<label class="live"><input type="checkbox" id="live"> auto-refresh</label>';
  app.append(head);

  if (__HOOK_RESEARCH__) {
    const research = document.createElement('p');
    research.className = 'sub';
    research.innerHTML = '<a style="color:var(--accent)" href="hook-research.html">Hook research: 45 references and six-topic comparison</a>';
    app.append(research);
  }

  app.append(tabs('subject', DATA.map(s => s.label), at[0], i => go(0, i)));
  app.append(tabs('video', sub.videos.map(v => v.title), at[1], i => go(1, i)));
  if (vid.runs.length > 1)
    app.append(tabs('run', vid.runs.map((r, i) => r.label + (i ? '' : '  \\u2190 default')), at[2], i => go(2, i)));
  const panel = document.createElement('section');
  panel.id = 'panel';
  panel.role = 'tabpanel';
  panel.tabIndex = 0;
  panel.innerHTML = !run
    ? '<h2>' + esc(vid.title) + '</h2><p class="empty-state">No full transcript has been generated for this topic yet.</p>'
    :
      '<div class="meta"><h2>' + esc(vid.title) + '</h2><span class="stats">'
    + doc.words.toLocaleString() + ' words \\u00b7 ~' + doc.minutes + ' min \\u00b7 '
    + esc(run.id) + ' \\u00b7 ' + esc(run.when) + '</span></div>'
    + (vid.chapter ? '<p class="chapter">' + esc(vid.chapter) + '</p>' : '')
    + (run.note ? '<p class="note">' + esc(run.note) + '</p>' : '')
    + (doc.audio
        ? '<div class="player"><audio controls preload="none" src="' + esc(doc.audio) + '"></audio></div>'
        : '<div class="player empty">No narration yet. Drop <code>' + esc(doc.expected_audio)
          + '</code> into the run folder and rebuild.</div>')
    + '<article>' + doc.paragraphs.map(p => '<p>' + esc(p) + '</p>').join('') + '</article>';
  app.append(panel);

  const foot = document.createElement('footer');
  foot.textContent = 'tools/build_lore_viewer.py --watch keeps this current';
  app.append(foot);

  // file:// cannot poll the disk, so staying current means reloading the page the watcher rewrote.
  const live = document.getElementById('live');
  live.checked = localStorage.getItem('live') === '1';
  live.addEventListener('change', () => {
    localStorage.setItem('live', live.checked ? '1' : '0');
    schedule();
  });
  schedule();
}

let timer;
function schedule() {
  clearTimeout(timer);
  if (localStorage.getItem('live') === '1' && !document.querySelector('audio:not([paused])'))
    timer = setTimeout(() => location.reload(), 3000);
}

render();
"""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Full transcripts</title>
<style>{css}</style>
</head>
<body>
<div class="app" id="app"></div>
<script>{js}</script>
</body>
</html>
"""


def build(root: Path = ROOT, quiet: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subjects = collect(root)
    out = root / "viewer.html"
    payload = json.dumps(subjects, ensure_ascii=False).replace("</", "<\\/")
    body = JS.replace("__DATA__", payload).replace("__BUILT__", datetime.now().strftime("%d %b %H:%M:%S"))
    body = body.replace('__HOOK_RESEARCH__', 'true' if (root/'hook-research.html').exists() else 'false')
    out.write_text(PAGE.format(css=CSS, js=body), encoding="utf-8")
    if not quiet:
        for s in subjects:
            runs = sum(len(v["runs"]) for v in s["videos"])
            audio = sum(1 for v in s["videos"] for r in v["runs"] for d in r["documents"] if d["audio"])
            print(f"  {s['label']:<12} {len(s['videos'])} videos, {runs} runs, {audio} with audio")
        if not subjects:
            print(f"  (nothing under {root} yet)")
        print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")
    return out


def signature(root: Path) -> set:
    """What the tree looks like now, so a change can be noticed without a filesystem watcher."""
    return {(str(p), p.stat().st_mtime_ns, p.stat().st_size)
            for p in root.rglob("*") if p.is_file() and p.name != "viewer.html"}


def watch(root: Path, interval: float) -> None:
    build(root)
    # Flushed, because this is usually left running with its output redirected to a log.
    print(f"watching {root} every {interval:g}s — Ctrl+C to stop", flush=True)
    last = signature(root)
    while True:
        time.sleep(interval)
        if (now := signature(root)) != last:
            last = now
            build(root, quiet=True)
            print(f"[{datetime.now():%H:%M:%S}] rebuilt", flush=True)


def selftest() -> None:
    """Build a throwaway tree and check the scan derives everything from the folders."""
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="lore-viewer-test-")).resolve()
    try:
        run = tmp / "science" / "letter-split" / "20260101-101500"
        run.mkdir(parents=True)
        (run / "full.txt").write_text("One paragraph.\n\nTwo words here.", encoding="utf-8")
        (run / "full.mp3").write_bytes(b"")
        (run / "cold open.txt").write_text("Just this.", encoding="utf-8")
        older = tmp / "science" / "letter-split" / "20251231-090000"
        older.mkdir(parents=True)
        (older / "full.txt").write_text("Older run.", encoding="utf-8")
        (tmp / "history" / "coldest-place" / "20260101-120000").mkdir(parents=True)
        (tmp / "history" / "coldest-place" / "20260101-120000" / "full.txt").write_text("x", encoding="utf-8")
        (tmp / "history" / "coldest-place" / "20260101-120000" / "meta.json").write_text(
            '{"title": "The Coldest Place", "note": "v3 prompt"}', encoding="utf-8")
        (tmp / "history" / "empty-video" / "20260101-000000").mkdir(parents=True)

        data = collect(tmp)
        assert [s["label"] for s in data] == ["History", "Science"], [s["label"] for s in data]

        science = data[1]["videos"][0]
        assert science["title"] == "Letter Split", science["title"]
        assert [r["id"] for r in science["runs"]] == ["20260101-101500", "20251231-090000"], "newest run first"
        docs = {d["name"]: d for d in science["runs"][0]["documents"]}
        assert set(docs) == {"Full"}, set(docs)
        assert docs["Full"]["audio"] == "science/letter-split/20260101-101500/full.mp3", docs["Full"]["audio"]
        assert docs["Full"]["words"] == 5, docs["Full"]["words"]
        assert "Cold Open" not in docs, "opening sample leaked into full-transcript tabs"

        history = data[0]["videos"][0]
        assert len(data[0]["videos"]) == 1, "a video whose only run has no transcript must be dropped"
        assert history["title"] == "The Coldest Place", "meta.json must win over the folder name"
        assert history["runs"][0]["note"] == "v3 prompt"

        assert short_slug("The Letter That Split the Atom") == "letter-split"
        assert short_slug("Ten Sheets of Glass in a Berkeley Basement") == "ten-sheets"
        assert run_dir("science", "The Letter That Split the Atom", tmp, "id").parts[-3:] == \
            ("science", "letter-split", "id")

        out = build(tmp, quiet=True)
        page = out.read_text(encoding="utf-8")
        assert "</script>" not in page.split("<script>")[1][:-20], "embedded json closed the script tag"
        assert "The Coldest Place" in page
        custom = tmp / "science" / "letter-split" / "a-later-revision"
        custom.mkdir()
        (custom / "full.txt").write_text("Later revision.", encoding="utf-8")
        (custom / "meta.json").write_text('{"created_at":"2026-01-02T12:00:00"}', encoding="utf-8")
        assert collect(tmp)[1]["videos"][0]["runs"][0]["id"] == custom.name
        misplaced = tmp / "history" / "letter-split" / "20260103-120000"
        misplaced.mkdir(parents=True)
        (misplaced / "full.txt").write_text("Science with a history voice.", encoding="utf-8")
        (misplaced / "full.mp3").write_bytes(b"")
        (misplaced / "meta.json").write_text(json.dumps({
            "content_subject": "science", "narration_profile": "history"}), encoding="utf-8")
        corrected = collect(tmp)
        assert len(corrected[0]["videos"]) == 1, "science leaked into History"
        assert len(corrected[1]["videos"]) == 1, "same topic must merge across legacy folders"
        merged = corrected[1]["videos"][0]["runs"]
        assert len(merged) == 4 and merged[0]["id"] == custom.name, "alternate replaced the default"
        alternate = next(r for r in merged if r["id"] == misplaced.name)
        assert alternate["alternate_profile"] and "History style" in alternate["label"]
        assert "History writing profile" in alternate["note"]
        assert alternate["documents"][0]["audio"] == "history/letter-split/20260103-120000/full.mp3"
        assert misplaced.exists(), "archived source must not move"
        hook_run = tmp / "science" / "letter-split" / "20260104-120000"
        hook_run.mkdir()
        (hook_run / "selected_hook.txt").write_text("A short hook.", encoding="utf-8")
        (hook_run / "hook_candidates.txt").write_text("Alternative hooks.", encoding="utf-8")
        assert len(collect(tmp)[1]["videos"][0]["runs"]) == 4, "hook trial created a run tab"
        sample = tmp / "history" / "sample-only" / "20260104-130000"
        sample.mkdir(parents=True)
        (sample / "opening_sample.txt").write_text("An unfinished opening.", encoding="utf-8")
        sample_video = next(v for v in collect(tmp)[0]["videos"] if v['title'] == 'Sample Only')
        assert sample_video['runs'] == [], "sample must show a missing-full-transcript state"
        (run / "full.mp3").unlink()
        (run / "selected_hook.mp3").write_bytes(b"")
        assert read_documents(run, tmp)[0]['audio'] is None, "hook audio attached to full transcript"
        print("  scan       2 subjects, newest run first, audio matched by stem, meta.json honoured")
        print("  full only  hook trials and openings excluded; sample-only topics remain visible")
        print("  subjects   legacy science runs regrouped; alternate profile labelled; source audio retained")
        print("  slug       titles fold to 1-2 word folder names")
        print("  page       transcripts embedded, script tag intact")
        print("\nAll viewer checks passed.")
    finally:
        assert tmp.parent == Path(tempfile.gettempdir()).resolve() and tmp.name.startswith("lore-viewer-test-")
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help=f"generations tree (default {ROOT})")
    ap.add_argument("--watch", nargs="?", type=float, const=2.0, metavar="SECONDS",
                    help="rebuild whenever the tree changes, polling every SECONDS (default 2)")
    ap.add_argument("--selftest", action="store_true", help="check the scan against a throwaway tree")
    args = ap.parse_args()

    if args.selftest:
        selftest()
    elif args.watch:
        try:
            watch(args.root, args.watch)
        except KeyboardInterrupt:
            print("\nstopped")
    else:
        build(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
