# Lore Video Input Spec — the quality bar

This document defines what must be true of a video entry in `tools/lore_video_plan.json` — its title, `hook_idea`, lessons, and concept beats — for it to be an ideal input to the lore generation pipeline (`tools/gen_lore_from_plan.py`, `stages/transcript.py` with `style: lore_sleep`). The contract: an input that passes every gate here contains everything the pipeline needs to produce a great 75–110 minute sleep-lore video. If a video generated from a passing input is weak, the fault is in the pipeline, not the input.

Every numeric threshold below derives from pipeline mechanics, not taste: one beat becomes one segment of roughly 300–400 words, the segment writer is forbidden to invent facts, and it sees only the beat text, the lesson name, and the last ~600 words of narration. The selected slower voice and inserted pauses add runtime after the word count.

---

## 1. Video level

**V1 — One argument.** The video makes a single claim with tension in it, and the whole video is the resolution of that claim. Test: you can complete the sentence "This video argues that…" in one line, and the final lesson visibly lands it. ("The wealthiest, most connected world of 1200 was everywhere except Europe." "One county's drainage problem built the machine that changed everything.")

**V2 — A hook that startles and resolves.** `hook_idea` leads with scale, paradox, or a myth-bust, contains at least one hard number, and answers itself rather than teasing. It is the seed of the cold open, which is the most-heard passage of the entire video — listeners replay openings and rarely reach the end.

**V3 — Shape: 4–6 lessons, 24–30 beats.** Each beat becomes roughly 300–400 words; with the slower voice and pauses, 24–30 beats yields the target range without forcing any beat to inflate. Below 24 the video needs unusually rich beats; above ~32 segments become too shallow.

**V4 — One visible spine, not merely traversable neighbors.** One person, journey, object, place, investigation, or tightly bounded chain of events recurs through at least three lessons and gives the listener something stable to follow. Adjacent beats still connect by cause, geography, or time, but adjacency alone is insufficient: a sequence of well-bridged regional surveys remains a survey. The opening establishes the spine before the cast grows; the final lesson resolves it. The last beat is an ending, never a setup for another video.

**V5 — Single-home facts.** Every marquee fact (a famous event, number, or person-moment) is *told* exactly once in the video. Any later use is written as an explicit callback ("the caravan we followed through Cairo") or approaches from a genuinely different angle with new specifics. This must be true in the input because the generator cannot enforce it: a segment can see only ~600 words behind itself. Mechanically checked by `tools/check_lore_plan.py` (zero cross-lesson shingle duplicates).

**V6 — Promise fuel.** At least three beats contain something concrete and strange enough to be named in the cold open's promise: an undelivered letter, a specific price, a nine-story tower that still stands. "Concrete and strange" means it can be named in under ten words and would make a stranger say "wait, really?"

---

## 2. Lesson (sub-lesson) level

**L1 — A chapter, not a category.** A lesson is a chapter of the story with its own micro-arc: it opens one question and settles it across its beats. Test: the lesson name can be restated as a sentence with an actor and a verb ("a shipping clerk noticed the cargo manifests didn't balance"), and the beats read in order as development of that sentence.

**L2 — 4–6 beats per lesson.** This gives each chapter 12–20 minutes of narration — enough to develop a micro-arc, short enough that the flat-energy rule holds.

**L3 — The name is fuel.** The lesson `name` is written as a 30–80 word mini-brief: the framing claim, the anchor (L4), and the strangest detail, with real facts in it. The generator passes the lesson name to every one of its segments as shared context, so everything in the name is free additional material — facts placed there raise the honest word budget of all 4–6 segments at once.

**L4 — An anchor.** At least one named person, documented artifact, or standing object recurs across the lesson's beats and can carry its bridges. A lesson anchored in Morel's shipping ledgers, Radcliffe's burned maps, or the Kaiping towers coheres by itself; the anchor gives the bridge writer its proper nouns.

**L5 — Continuity budget.** Each beat shares at least one entity, place, or causal link with an adjacent beat, and the lesson introduces at most ~3 new major characters. A half-asleep listener can hold one small cast per chapter; continuity between neighboring beats is what lets attention drop and rejoin without loss.

---

## 3. Beat (concept) level — the atomic unit

A beat is one declarative passage of 90–150 words that becomes one segment. Its text is quoted verbatim into the segment prompt.

**B1 — Fact load: 6–10 independently verifiable specifics.** Named people with roles, exact dates, quantities, prices, distances, places, quoted phrases — each checkable on its own. Honest narration expands source prose only about 2.5–3×; asking 60 words of notes to become 500 words forces either repetition or invention. A 90–150 word beat plus its lesson context can genuinely fill a 300–400 word segment. This is the single most load-bearing gate.

**B2 — A complete micro-story.** Situation, action, and outcome are all present or clearly implied, and the outcome is stated inside the beat. The register this format needs is curious-but-resolved: the segment writer can only resolve-as-it-goes if the beat hands it the resolution.

**B3 — The strange-true test.** The beat contains at least one thing a well-read adult would not expect. The selection question for every beat is: *what is the strangest, most specific true thing inside this topic?* Wonder, dark irony, and scale inversions all qualify; the emotion must come from the fact itself, not from withholding it.

**B4 — A quotable source where one exists.** If the topic has a surviving letter, chronicle, inscription, ledger, or traveller's account, the beat carries a verbatim quote with author and rough date ("I am utterly ruined… no caravan from Samarkand for three years"). This is the highest-value single attribute a beat can have — the prompts instruct the narrator to quote primary sources directly, and it costs the beat a dozen words.

**B5 — Mechanism, told procedurally.** Where the subject is a system — a trade, a law, a ritual, a machine — the beat carries the procedural specifics: who did which step, in what order, at what cost or distance. Process narrated step-by-step, with names and numbers attached to each step, is the format's most reliable substance and expands honestly without drama.

**B6 — One number with a handle.** If a beat depends on scale, its single most important number includes or trivially supports a human-scale comparison. Secondary numbers may stand plainly; comparing every quantity creates clutter.

**B7 — Verifiable, and self-hedged where soft.** Every claim is checkable against mainstream sources, and any superlative or contested figure carries its hedge inside the beat text ("reportedly", "estimated between X and Y", "by some accounts"). This genre's audience abandons channels over catchable errors more than over anything else, and the myth-busting register raises the bar for whichever claim does the busting.

**B8 — Survives being heard once, half-asleep.** No enumerations or mappings that require retention (at most one or two items of any parallel set, folded into prose). Beats destined for the final third of a video introduce at most 2–3 unfamiliar proper nouns — late-piece listeners have no headroom for a new cast.

**B9 — Written as narration-ready prose.** Declarative sentences, past tense, no instructional or meta framing ("students should understand…", "this concept covers…"). The beat text flows into the prompt as-is; whatever voice it is written in leaks into the video.

**B10 — Provenance is material.** Where the topic's evidence has a story — a chronicler writing secondhand from another city, records that burned or drowned, an archive that survives, a modern researcher who reconstructed a number — the beat carries it. At least one beat per lesson should let the narrator say *how we know*, not just *what happened*: this historiographic layer is the strongest human-feel signal in the reference channels, and the narrator can only weigh sources the input hands it. (Corollary of the fabrication ban: provenance the beat omits is provenance the video cannot have.)

---

## 4. Coverage rules

**C1 — Merge 3–8 AP topics per video.** A single topic supplies too few seed facts for a full video; density comes from combination. Syllabus completeness is measured at the video level.

**C2 — A topic is covered when its memorable core is dramatized.** Not when its term list is enumerated. One person can carry an entire topic — Petrov covers the entire logic of mutually assured destruction better than four named policies do. If a topic's only available material is taxonomy, find the person, document, object, or price inside it and cover the topic through that.

**C3 — Repetition scope.** Across videos, repetition is acceptable (viewers do not binge in sequence; each video must stand alone). Within a video, only V5-style callbacks.

---

## 5. Acceptance checklist

Mechanical gates (run `tools/check_lore_plan.py`):

- [ ] 20–30 beats, 4–6 lessons, 4–6 beats per lesson
- [ ] Zero cross-lesson near-duplicate pairs
- [ ] `estimated_concepts` matches actual beat count

Judgment gates (reviewable by a human or an LLM pass, per item):

- [ ] V1–V6 hold for the video
- [ ] L1–L5 hold for every lesson
- [ ] B1–B9 hold for every beat; B1 (4–8 verifiable specifics) and B7 (verifiability) are hard requirements, the rest allow rare justified exceptions

---

## 6. A passing beat, annotated

From the WWII video, "The Symphony in a Starving City":

> "On August 9, 1942 — the exact date Hitler had once planned to celebrate the city's fall with a banquet at the Astoria Hotel — the Leningrad Radio Orchestra performed Dmitri Shostakovich's Seventh Symphony inside the Philharmonic Hall, its windows shattered by shelling, while Soviet artillery fired suppressive barrages to silence German guns during the broadcast."

- **B1**: six verifiable specifics (date, Astoria banquet plan, orchestra, composer and work, shattered hall, artillery cover).
- **B2**: complete micro-story — siege (situation), concert under barrage (action), broadcast happens (outcome stated).
- **B3**: strange-true twice over — the date coincidence and artillery as concert security.
- **B5**: mechanism — how the concert was physically made possible.
- **B8**: two proper-noun clusters, both already familiar from the lesson's earlier beats.

The surrounding lesson passes L1–L5: its name is a mini-brief carrying the bread-ration number and the broadcast fact (L3), Shostakovich's symphony is the anchor (L4), and every beat shares the siege as connective tissue (L5).
