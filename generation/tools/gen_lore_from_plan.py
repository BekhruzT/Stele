"""Draft a lore transcript from lore_video_plan.json without the stage pipeline: `--chapter 0 --video 1`."""
import json, os, re, sys, time, argparse
from pathlib import Path
import anthropic

BASE      = Path(__file__).resolve().parent.parent
LORE_PLAN = BASE / "tools" / "lore_video_plan.json"
ENV_FILE  = BASE / ".env"
DEFAULT_OUT = BASE / "artifacts" / "lore_transcripts"

# Progress lines land mid-run over a job measured in hours, and the prompts carry non-ASCII.
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

env = {}
with open(ENV_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")

# ── TFY client ──────────────────────────────────────────────────────────────
_client = anthropic.Anthropic(
    api_key="unused-tfy-gateway",
    base_url=env["TFY_BASE_URL"],
    default_headers={"x-tfy-api-key": env["TFY_API_KEY"]},
    timeout=180.0,
)
# Sonnet for every call: opus returns an empty body through the gateway.
MODEL_SLUG = "claude-group/claude-sonnet-5"

def trim_incomplete(text: str) -> str:
    """Drop a trailing sentence fragment left by a truncated response."""
    if re.search(r'[.!?]["\u201d\u2019)]?\s*$', text):
        return text
    cut = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
    return text[:cut + 1] if cut > 0 else text


def call(system: str, user: str, slug: str, tag: str, retries: int = 3, max_tokens: int = 3000) -> str:
    for attempt in range(retries):
        try:
            msg = _client.messages.create(
                model=slug, max_tokens=max_tokens,
                thinking={"type": "disabled"},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = next((b.text for b in msg.content if hasattr(b, "text")), "").strip()
            if msg.stop_reason == "max_tokens":
                print(f"    [WARN] hit max_tokens={max_tokens} — response likely truncated; retrying")
                if attempt < retries - 1:
                    time.sleep(3)
                    continue
        except Exception as e:
            if attempt < retries - 1:
                print(f"    API error (attempt {attempt+1}/{retries}): {e}  — retrying in 5s")
                time.sleep(5)
                continue
            raise
        if not raw:
            if attempt < retries - 1:
                print(f"    Empty response (attempt {attempt+1}/{retries}) — retrying in 5s")
                time.sleep(5)
                continue
            raise RuntimeError(f"empty {tag} response after {retries} attempts")
        # Try tagged extraction (case-insensitive)
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", raw, re.DOTALL | re.IGNORECASE)
        if m:
            return trim_incomplete(m.group(1).strip())
        # Fallback: if raw is non-empty prose (no tags at all or tag-stripping gives content), use it
        stripped = re.sub(r"<[^>]+>", "", raw).strip()
        if stripped:
            return trim_incomplete(stripped)
        if attempt < retries - 1:
            print(f"    Could not parse {tag} (attempt {attempt+1}/{retries}) — retrying in 5s")
            time.sleep(5)
    raise RuntimeError(f"failed to get {tag} after {retries} attempts")

# ── prompts ─────────────────────────────────────────────────────────────────

LORE_LANG = """
**Voice for a Sleep-Lore Narration**
One host, read aloud, for someone lying in the dark with their eyes closed.

1) MEDIUM, SPOKEN SENTENCES. Aim for 22-26 words on average: most sentences belong in the
   14-32 word range, with an occasional longer sentence only where one action genuinely carries
   on. HARD CEILING: 38 words. Split before a second subordinate clause starts carrying a second
   fact. After one long sentence, let the next land at 12-20 words. A sentence under 9 words is a
   rare deliberate landing point, at most one per paragraph. Continuity belongs between
   paragraphs and scenes; an individual sentence may finish cleanly without dragging the next
   sentence behind it with "and," "but," or another dependent clause.
2) PLAIN, NOT ORNATE. Plain comes from word choice, not brevity. Write like a knowledgeable
   friend talking quietly. Contractions fine. No literary similes or imagery. Any technical or
   period term a tired non-specialist may not know (sextant, escapement, interdict) gets a plain
   gloss folded into the same sentence on first use, set off with commas, not dashes ("a sextant,
   the handheld instrument sailors used to measure how high the sun sat"), or is replaced outright
   by the plain description. Ration em-dashes to at most one per paragraph — dash-heavy prose is
   itself a tell; commas, parentheses, and "called X," do the same work more quietly.
3) SPECIFICITY, NOT ABSTRACTION. Every paragraph is anchored by real people, places, years,
   quantities, or mechanisms — never "the ruler," "at this time," "a significant sum," "a major
   center." One or two plain connective sentences may carry no proper noun; a tired listener needs
   room between names. When a moment has several specifics, give each its own sentence rather than
   packing all of them into one with commas and subordinate clauses. For the single largest number
   in a segment, give one concrete
   human-scale comparison drawn from the story's own world — a named city, a known voyage, a
   worker's yearly wage. Never compare against a modern object the material doesn't mention
   (no smartphones, no tennis courts), and never state a comparison you can't verify.
4) CONFIDENT IGNORANCE. When sources are silent, say so and name what the silence means.
5) Quote primary sources wherever available.
6) SIGNPOST SPARINGLY. At most one brief orienting phrase per segment may help a listener who
   drifted and rejoined. Keep it inside the factual movement. Do not open a paragraph with "To
   understand that, we need to look at..." or turn orientation into a repeated template.
7) CURIOUS, NEVER GRIPPING. Resolve things as you go. No cliffhangers. Flat energy start
   to finish. Minute 80 should feel like Minute 5.
8) ONE NARRATOR. Quote historical figures inside the narration ("He wrote that..."), never
   as a second speaker.
9) Correcting a false assumption is one valid structural move, usable once or twice per video —
   never as a repeating rhythm, never framed as a revelation. When used: state the incorrect
   assumption, then correct it with a name or a number. Do not tell the listener the correction
   is surprising or important; let the fact itself carry that weight.
10) Avoid: "unprecedented," "revolutionary transformation," "let's dive in," "buckle up,"
    "fascinating," "stay tuned," "little did they know," "stands as a testament."
11) No lists that require memorisation. Keep the one or two items the listener needs and omit the
    rest. If a sequence genuinely matters, walk through it in separate sentences tied by cause or
    time. Never solve a list by folding every item into one comma-heavy sentence.
12) Stay inside the facts given. Light scene-setting (weather, look of a room) may be filled
    in; never invent a specific claim.
13) NEVER SELL THE STORY. Do not tell the listener a fact is important, surprising, or the
    reason the story exists ("that number is the reason this story gets told at all"), and
    write no aphoristic pivot lines that dress a fact up as a clever reversal ("It was, more
    precisely, a clock that did not exist yet"). State the fact in plain order and move on;
    if it is interesting, it will be interesting on its own.
14) SAY IT ONCE. A fact, definition, or gloss appears in full exactly once in the whole piece.
    If it was already told (check the "already told" list), touch it in half a sentence at most,
    naming the thing itself ("the wreck off Scilly", "the £20,000 prize") — never a second
    retelling, never a second gloss, and never a citation of your own narration ("as already
    covered in this account", "already described earlier"): the listener was asleep for half of
    it and the reference must read naturally either way. A person gets full name and title on
    first mention only; after that, surname alone.
15) EXACT AND CONSISTENT. Spell every name and place exactly as the material spells them, and
    keep every number and date identical each time it recurs. Never drift to a variant spelling,
    a different county, or a differently rounded figure for the same fact.
16) BANNED RHETORIC — each of these reads as generated text:
    - negation-first drama: "was not an abstraction", "This was not X. It was Y.", "Nobody had
      rescinded the Act — no clerk had misfiled it."
    - echo repetition: "It killed men, and it killed them in large numbers"; two consecutive
      sentences opening on the same negation ("No storm... No instrument..."); parallel negation
      lists inside one sentence ("was not attacked, was not caught in a storm, was not undone
      by seamanship").
    - narration about the narration: "a gap worth naming plainly", "is where this story goes
      next", "a thread this account picks up later", "a separate thread we'll pick up".
    - referring to your source or your own narration: "the material", "the concepts you were
      given", "the record before us", "this account", "this telling", "as already noted", "as
      mentioned earlier", "already described", "that will be covered later". The listener must
      never sense a document behind the voice — refer back by naming the thing itself ("the
      wreck off Scilly"), and say "no ship's log names him", never "the material doesn't say".
    - profundity that doesn't parse: "outlasted him by only two days short of nothing at all".
    Say the plain version instead, or cut the sentence.
17) HOW WE KNOW, ONCE WHERE IT HELPS. If this concept names a source, spend at most one paragraph
    on who recorded the fact and whether they witnessed it. Do not manufacture a lesson from every
    silence, repeat that records are incomplete, or turn "we do not know" into a profound-sounding
    conclusion. Most segments need no archive paragraph at all.
18) DO NOT KEEP RESTATING THE THESIS. A comparison or framing claim gets one full statement in the
    opening and may return briefly in the close. Inside the body, narrate the place and people in
    front of you. Do not repeatedly tell the listener where wealth, power, knowledge, or the
    "center" really sat unless the current facts directly require that comparison.
"""

COLD_OPEN_SYS = """You are writing the opening of a long-form (~90 minute) "sleep-lore" history video on the subject: {subject}.

Write it as four short movements in one continuous flow (no labels or numbers):
1. THE BIG PICTURE. Open wide — the whole subject, stated plainly. Plain means ordinary words at full sentence length, not short sentences — keep them the same length as the rest of the piece. Lead with a fact that establishes scale or consequence immediately, drawn from the concepts you were given — do not reach outside them for a bigger statistic, and copy every number exactly as the concepts state it (if they say "between 1,400 and 2,000", never round it to "several thousand"). State it without framing it as striking, surprising, or myth-busting. Do NOT open on a named individual on a particular afternoon.
2. THE SCENE. Descend into one specific documented moment: a named person, a real date, a real place, drawn from the concepts you were given. Sketch it, don't spend it: name the who, where, when, and the single sharpest detail, then move on — the full telling belongs to the segment that owns that moment later in the piece, and every detail you use here is one that segment must not repeat. Quote a written source only if the concepts supply one — never invent or recall a quote from outside the material, and never introduce a later-era traveller the material does not mention.
3. THE PROMISE. Name three or four specific, concrete things the listener will hear: a person, a price, a letter, a number. Not a table of contents. Do not describe them as strange, surprising, or important — name them and move on.
4. THE SETTLE-IN. Invite the listener to get comfortable. Spoken directly. Something in the spirit of "So get comfortable, dim the lights, and let's take this slowly." Then begin.

Do NOT end on a cliffhanger. End by simply starting.

{lore_lang}

Write only the opening passage inside <cold_open>...</cold_open> tags. Target length: 400-500 words."""

COLD_OPEN_USER = """Video: "{title}"

Concepts this video will cover (use these to choose an opening scene and pick concrete, specific details for the promise):
{concepts}
"""

SEGMENT_SYS = """You are the sole narrator of a long-form "sleep-lore" history video, continuing a story already in progress. You are about {pct}% of the way through the piece; {pacing}.

Your task: turn one concept into a self-contained substory that advances the larger narrative.

- OPEN CLEANLY. Continue the previous action when the connection is real; otherwise begin directly
  with this substory's person, place, object, or year. A quiet scene cut is better than an invented
  causal link. Never recap the previous passage merely to manufacture a weld, and never announce
  the new topic ("Now let's turn to...").
- CONCRETE AND PROCEDURAL. Walk through real mechanics — how a ritual was performed, how a ship was loaded, how a law was enforced — but never in the abstract: every step belongs to a named person in a named place, with the year, the cost, the distance, or the count attached. A sentence of pure process with no name and no number in it is the first thing to cut. Quote sources verbatim where available.
- {scene_note}
- Aim for {seg_words} words — a length to reach, not a ceiling. Reach it through procedure, provenance, and the human-scale texture of the facts you hold (rules 5 and 17), never through padding; if the facts genuinely cannot fill it, stop early rather than invent: never fabricate a name, date, number, or event that is not in the material. Every sentence is a fact or a step forward — never a verdict on what it all meant, and never a pre-announcement of significance. No "Here is the plainest answer", no "That single fact changes what we thought we knew about X", no "This is what matters most." State the fact; move on. The listener draws the conclusion.
- END ON A FACT. The last sentence of the segment states a fact, plainly, and stops — the next passage's weld handles the handoff. Never end by announcing what comes next in the manner of a narrator describing his own script ("What the Board made of that is where this story goes next"). A plain forward tease anchored to a thing ("We'll come back to what that prize cost.") is a different move and a welcome one — it is how this genre lets a drifting listener rejoin — but use it at most about once per lesson, mid-segment or as a closing line.

{lore_lang}

Write only the substory inside <segment>...</segment> tags. No headers, labels, or meta-commentary."""

SEGMENT_USER = """Video title: "{title}"

Already told earlier in the piece — every fact below has been narrated in full. HARD RULE: never
retell, re-explain, or re-gloss any of it; if this substory touches one, refer back in half a
sentence ("the wreck off Scilly") and keep the same spellings and numbers. Never mention this
list, the opening, or any "account" in the narration — the listener hears one continuous voice:
{covered}

The last few paragraphs as actually written (for tone and continuity):
{so_far}

The concept to turn into this substory:
{concept}

The lesson this concept belongs to (shared background for its neighboring substories — draw from it only what this concept needs, and do not retell facts that clearly belong to a sibling concept):
{lesson}

RESERVED for later substories — these facts belong to segments still to come. Do not narrate,
preview, or gloss any of them now, even in passing; if your concept brushes against one, stop
at the boundary:
{upcoming}
"""

CLOSE_SYS = """You are the sole narrator, writing the closing passage of a long-form sleep-lore history video. By now the listener may well be asleep, and that is a success.

- Introduce no new information.
- Return briefly to the opening question or scene and answer it directly, in ordinary words — no preamble, no framing of the answer as a revelation.
- Acknowledge the subject contains more than one video can hold, without teasing a sequel.
- In the final paragraph, narrow to one concrete object, place, or physical action already present
  in the opening. Introduce no comparison, new region, thesis, or historical balancing there.
- End with "Good night" — two words, on their own, as the last thing spoken.
- Do not address the listener directly in the final passage.

{lore_lang}

Write only the closing passage inside <close>...</close> tags. Target: ~280 words."""

CLOSE_USER = """Video: "{title}"

Opening image this piece began with:
{opening}

How the story arrived (for continuity — do not restate it):
{so_far}
"""

REVIEW_SYS = """You are reviewing a sleep-history narration. Check the passage for exactly four violation types:

1. FABRICATION — compare EVERY sentence clause by clause against Allowed facts and Lesson context.
Flag each person, title, place, building, date, number, event, decision, cause, outcome, quotation,
social movement, or surviving/missing-record claim that is not explicitly supported there. Generic
weather, light, and texture are allowed; model memory and plausible inference are not. Plain
arithmetic and a short everyday-language gloss of a supplied term are allowed.
2. RETELLING — a fact from the "already told earlier" list narrated again in full (more than a half-sentence callback). A passage using its OWN allowed facts is never a retelling — only repetition of the earlier narration counts.
3. META — the narration referring to itself or its sources: "this account", "this telling", "as already noted", "as mentioned earlier", "the material", "covered on its own", "is where this story goes next".
4. PROSE — overloaded sentences carrying several separate facts; a forced transition that recaps
the previous passage only to connect it; repeated thesis language; or pseudo-profundity built from
negation, missing records, or "silence". Flag only concrete instances, not general preferences.

Output rules, strict: no reasoning, no commentary, no hedging. If you find yourself explaining why something is acceptable, it is not a violation — omit it entirely. Report only violations you are confident of; a passage with nothing confidently wrong gets exactly: OK
Otherwise, one violation per line: TYPE — "exact quote" — what is wrong, in one short clause.

Reply inside <review>...</review> tags."""

REVIEW_USER = """Passage to check:
{segment}

Allowed facts (the passage's own material):
{concept}

Lesson context (also allowed):
{lesson}

Already told earlier (brief callbacks to these are allowed; full retellings are violations):
{covered}
"""

REPAIR_SYS = """You are editing one passage of a sleep-lore history narration. Remove ONLY the violations listed — keep every other sentence exactly as written, word for word, and keep the corrected passage within about 10% of the original's length: repair by replacing and smoothing, never by deleting whole sentences that were not flagged.

- FABRICATION: replace the claim with what the allowed facts explicitly support, or cut just that
claim and smooth the join. Familiar world knowledge is still forbidden. Never patch a cut with a
new claim of your own — above all, never invent an absence ("no record survives of...", "is not
something that has come down to us") unless the allowed facts state it; a clean cut beats invented
uncertainty.
- RETELLING: compress to a half-sentence callback naming the thing ("the wreck off Scilly"), and spend the freed words deeper inside this passage's own allowed facts.
- META: rephrase so the narration never refers to itself or its sources ("no ship's log names him", not "the material doesn't say").
- PROSE: split overloaded sentences, remove the forced recap or thesis commentary, and state the
supported facts in plain order. Do not add a replacement moral, interpretation, or transition.

{lore_lang}

Return the full corrected passage inside <segment>...</segment> tags."""

REPAIR_USER = """Passage:
{segment}

Violations to remove:
{violations}

Allowed facts:
{concept}

Lesson context:
{lesson}
"""


def pacing_note(pct: int) -> str:
    base = ("hold the same flat register from the first minute to the last. What stays "
            "constant is the rate at which you name people, places, dates, and numbers; "
            "what never rises is the emotional register. ")
    if pct < 25:
        return base + "Introduce people and places by full name and title on first mention."
    if pct < 60:
        return base + "The names already introduced are familiar — use them freely."
    return base + ("Most listeners are asleep. Keep naming things at exactly the same rate — "
                   "what drops away is any attempt to build toward a conclusion.")


def tail(text: str, n: int = 600) -> str:
    return " ".join(text.split()[-n:])


BANNED_RE = re.compile(
    r"this account|this telling|as already noted|as mentioned earlier|already (?:covered|described)"
    r"|the material|the concepts you|covered on its own|goes next|picks up (?:next|later)"
    r"|separate thread|stands as a testament|not an abstraction|little did"
    r"|this is not (?:a )?story|it is simply a description|visible in outline"
    r"|set (?:them|these|the facts) side by side|at its heart|crucially"
    r"|it is worth noting|the picture most of us have|and so we come to"
    r"|to understand (?:that|this),? we need to", re.I)


def word_echo(prev: str, cur: str, n: int = 6) -> str:
    """Longest-first check: does the opening of cur repeat an n-word run from the end of prev?"""
    prev_words = re.sub(r"[^\w\s]", "", prev.lower()).split()[-80:]
    cur_words = re.sub(r"[^\w\s]", "", cur.lower()).split()[:80]
    grams = {" ".join(prev_words[i:i + n]) for i in range(max(0, len(prev_words) - n + 1))}
    for i in range(max(0, len(cur_words) - n + 1)):
        g = " ".join(cur_words[i:i + n])
        if g in grams:
            return g
    return ""


def deterministic_flags(seg: str, prev_end: str) -> list[str]:
    """Return local prose violations that require no model judgment."""
    flags = []
    g = word_echo(prev_end, seg)
    if g:
        flags.append(f'ECHO — the opening repeats "{g}" from the previous passage; rewrite the weld in fresh words.')
    for m in BANNED_RE.finditer(seg):
        flags.append(f'META — banned phrase "{m.group(0)}".')
    long_sentences = [s for s in re.split(r'(?<=[.!?])\s+', seg) if len(s.split()) > 38]
    if long_sentences:
        flags.append(
            f'PROSE — {len(long_sentences)} sentence(s) exceed the 38-word spoken ceiling; '
            'split each at a natural fact boundary.')
    return flags


def check_and_repair(seg: str, concept: str, lesson: str, covered: str, prev_end: str, label: str,
                     llm_review: bool = True) -> str:
    """Run deterministic and model review, then repair remaining local violations once."""
    flags = deterministic_flags(seg, prev_end)
    if llm_review:
        review = call(REVIEW_SYS, REVIEW_USER.format(segment=seg, concept=concept, lesson=lesson, covered=covered),
                      MODEL_SLUG, "review", max_tokens=1500)
        if review.strip().upper() != "OK":
            flags.append(review.strip())
    if not flags:
        return seg
    print(f"    [review] {label}: {len(flags)} issue(s) — repairing")
    for f in flags:
        print(f"      - {f.splitlines()[0][:110]}")
    repaired = call(REPAIR_SYS.format(lore_lang=LORE_LANG),
                    REPAIR_USER.format(segment=seg, violations="\n".join(flags), concept=concept, lesson=lesson),
                    MODEL_SLUG, "segment")
    remaining = deterministic_flags(repaired, prev_end)
    if remaining:
        print(f"    [review] {label}: repair left {len(remaining)} local issue(s) — retrying once")
        repaired = call(
            REPAIR_SYS.format(lore_lang=LORE_LANG),
            REPAIR_USER.format(segment=repaired, violations="\n".join(remaining),
                               concept=concept, lesson=lesson),
            MODEL_SLUG, "segment")
    if llm_review:
        second_review = call(
            REVIEW_SYS,
            REVIEW_USER.format(segment=repaired, concept=concept, lesson=lesson, covered=covered),
            MODEL_SLUG, "review", max_tokens=1500)
        if second_review.strip().upper() != "OK":
            print(f"    [review] {label}: repaired passage still has review findings — retrying once")
            repaired = call(
                REPAIR_SYS.format(lore_lang=LORE_LANG),
                REPAIR_USER.format(segment=repaired, violations=second_review,
                                   concept=concept, lesson=lesson),
                MODEL_SLUG, "segment")
    return repaired


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:50]


def generate(chapter_idx: int, video_idx: int, out_dir: Path, plan_path: str = LORE_PLAN) -> Path:
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    chapter = plan["chapters"][chapter_idx]
    video   = chapter["videos"][video_idx]
    title   = video["title"]
    slug    = slugify(title)

    # Beats: each concept string in order, paired with its lesson name as shared fuel for the segment writer
    beats = []
    for lesson in video["lessons"]:
        for concept in lesson.get("concepts", []):
            if concept.strip():
                beats.append({"lesson": lesson["name"], "text": concept.strip()})

    n = len(beats)
    # The host voice plus inserted pauses reads ~10.5k words in roughly 74 minutes.
    # ponytail: a beat's own note caps its segment at 3x below, so the target can never force invention.
    target_words = 10500
    seg_words = max(300, (target_words - 450 - 280) // n)
    print(f"\n{'='*70}")
    print(f"Video: {title}")
    print(f"Chapter: {chapter['chapter'][:60]}")
    print(f"Lessons: {len(video['lessons'])}  |  Beats: {n}  |  Target per seg: {seg_words}w")
    print(f"{'='*70}")

    out_dir.mkdir(parents=True, exist_ok=True)
    partial = out_dir / f"{slug}_partial.txt"

    # Cold open
    concepts_sample = "\n".join(f"- {b['text']}" for b in beats[:20])
    print(f"\n[cold open]")
    intro = call(
        COLD_OPEN_SYS.format(subject=chapter["chapter"], lore_lang=LORE_LANG),
        COLD_OPEN_USER.format(title=title, concepts=concepts_sample),
        MODEL_SLUG, "cold_open",
    )
    intro = check_and_repair(intro, concepts_sample, chapter["chapter"],
                             "(nothing yet — this opens the piece)", "", "cold open")
    blocks = [intro]
    narrative = intro
    partial.write_text("\n\n".join(blocks), encoding="utf-8")

    SCENE_ON  = ("Once in this segment, let a 40-50 word passage settle into the physical world "
                 "the actors moved through: weather, terrain, sound, texture. Anchor it — the first "
                 "sentence names the place and the season or year. Never open the passage with "
                 "\"Picture\"; walk into it mid-action. Keep its sentences long and unbroken.")
    SCENE_OFF = ("Do NOT include a scene-setting or atmospheric passage in this segment — recent "
                 "segments carried one already. Stay with facts, people, and mechanics throughout.")

    for i, beat in enumerate(beats):
        pct = round(100 * i / max(1, n - 1))
        upcoming = "\n".join(f"- {b['text']}" for b in beats[i + 1:i + 4]) or "This is the final segment."
        # ponytail: covered list = full cold open + every prior beat; grows to ~2k words by the end, fine
        covered = "The opening passage (verbatim):\n" + intro
        if i:
            covered += "\n\nPrior substories, each already narrated in full:\n" + \
                       "\n".join(f"- {b['text']}" for b in beats[:i])

        source_limited_words = min(seg_words, max(300, len(beat["text"].split()) * 3))
        print(f"[segment {i+1}/{n}  {pct}%  target {source_limited_words}w] {beat['text'][:70]}...")
        seg = call(
            SEGMENT_SYS.format(pct=pct, pacing=pacing_note(pct), lore_lang=LORE_LANG,
                               seg_words=source_limited_words,
                               scene_note=SCENE_ON if i % 3 == 0 else SCENE_OFF),
            SEGMENT_USER.format(
                title=title,
                covered=covered,
                so_far=tail(narrative, 400),
                concept=beat["text"],
                lesson=beat["lesson"],
                upcoming=upcoming,
            ),
            MODEL_SLUG, "segment",
        )
        seg = check_and_repair(seg, beat["text"], beat["lesson"], covered,
                               tail(narrative, 80), f"segment {i+1}")
        blocks.append(seg)
        narrative += "\n\n" + seg
        partial.write_text("\n\n".join(blocks), encoding="utf-8")
        time.sleep(0.2)

    print(f"\n[close]")
    close = call(
        CLOSE_SYS.format(lore_lang=LORE_LANG),
        CLOSE_USER.format(
            title=title,
            opening=intro[:800],
            so_far=tail(narrative, 600),
        ),
        MODEL_SLUG, "close",
    )
    # ponytail: close introduces no new facts, so skip the LLM fact-check — banned-phrase/echo scan only
    close = check_and_repair(close, tail(narrative, 600), title, "(the whole piece precedes this)",
                             tail(narrative, 80), "close", llm_review=False)
    blocks.append(close)

    out = out_dir / f"{slug}_full.txt"
    text = "\n\n".join(blocks)
    out.write_text(text, encoding="utf-8")
    partial.unlink(missing_ok=True)
    words = len(text.split())
    wpm = 150
    print(f"\nWrote: {out}")
    print(f"Words: {words:,}  |  Est. duration: ~{words // wpm} min at {wpm} WPM")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int, default=0)
    ap.add_argument("--video",   type=int, default=0)
    ap.add_argument("--out",     default=DEFAULT_OUT)
    ap.add_argument("--plan",    default=LORE_PLAN)
    ap.add_argument("--list",    action="store_true", help="print every [chapter,video] index and exit")
    args = ap.parse_args()

    if args.list:
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
        for ci, ch in enumerate(plan["chapters"]):
            print(f"\nCh {ci}: {ch['chapter'][:60]}")
            for vi, v in enumerate(ch["videos"]):
                nc = sum(len(l["concepts"]) for l in v["lessons"])
                print(f"  [{ci},{vi}] {v['title'][:65]} | {nc} beats")
        return

    generate(args.chapter, args.video, Path(args.out), args.plan)


if __name__ == "__main__":
    main()
