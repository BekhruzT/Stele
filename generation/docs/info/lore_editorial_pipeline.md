# Running the reference-led lore pipeline

Both `tools/gen_lore_from_plan.py` and the `Video Transcript` stage (`stages/transcript.py`) call
`core/lore_editorial.py::generate_story`. The default model is `openai-group/gpt-6-astra`, at high
reasoning, through the existing TFY gateway. Other application workloads retain their model settings.

The writer receives the research and all 45 published opening passages in its system message,
and returns five spoken openings. One chooser call sees the title, subject, research, and five
openings. It ranks the actual spoken text by whether it keeps the central story in focus, makes
that subject interesting, and has factual support. Code takes the highest-ranked opening passing
all three checks. If none passes, the run stops with `needs_hook_revision` before body drafting.
A model pass is not an editorial approval.
After selecting a hook, the engine plans the whole story, drafts it, reviews it as a whole, and
optionally revises and reviews again. Hook repairs receive the same one-call chooser check;
a clean body review cannot override a failed hook check. Approved production locks remain
unchanged. No approved topic answer is inserted into a fresh hook evaluation.

The reviewer receives the exact assembled transcript, including the separately inserted hook;
the writer's opening field begins with the sentence after that hook.
Prompt v2.5 adds concise introductions for people in the prose: a supported role or relationship,
usually one to three words embedded in the first mention, including secondary people. The reviewer
checks this under continuity and listenability and requests only the smallest necessary edit.
The first-sentence hook is exempt; clear existing introductions and later mentions need no new label.
The saved v2.4 evaluation candidates predate this change and remain unchanged; later regeneration
runs are saved separately so the comparison can be reproduced.
Prompt v2.6 keeps these shared rules and gives history its own reference excerpts and domain
guidance. History uses the Silk Roads narrative and Mansa Musa sample; science keeps the same
Meitner and Bell excerpts. `style-reference-catalog.json` selects exact passages by narration genre.
History guidance addresses chronology, agency, institutions, and attributed motives or explanations.
The v2.7 history refinement additionally targets repeated explanations and narrated research
precautions, following the first live history pilots. It changes no science reference excerpts.
Prompt v2.8 adds a shared rule for historical money: when an amount's magnitude supplies the stakes,
give one brief, supported frame of reference at its first meaningful mention, including in a hook.
Planning retains the comparison's source, method, and reference year; hook selection and review
check for missing scale or invented conversions. Missing evidence calls for supported reframing.
This applies to both history and science; it does not require converting every sum.
Prompt v3.2 separates hook guidance from prose examples. Rejected history reference openings are
excluded from prose excerpts and no prose references are sent to hook generation or selection.
It distinguishes extraordinary consequence from an ordinary mechanism or manufactured contrast,
and asks for direct actions instead of report-like wording or vague scale. The planning and body
review stages check whether the opening actually develops the hook's promise.
V3.2 additionally rejects technical puzzles that omit the discovery's significance for a general
listener. These can be useful explanatory questions after a hook, but cannot replace its premise.
For reviewed topics, the exact user-approved hook in `approved-hooks.json` is reused and
locked by default. The candidate pool remains available for comparison, but cannot replace that
choice. Musa's accepted hook is saved separately from the older history prose reference. New
topics use selection. `--fresh-hook` explicitly tests new wording on an approved topic; hook-only
runs always test fresh candidates unless an approved-hook file is explicitly supplied.

The science reference excerpts include the Meitner opening, barium explanation, and ending, plus the
Bell opening and common-cause analogy. History includes a correspondence-based account of trade,
the Musa court encounter, and a later traveller's caravan logistics. Exact text and hashes are saved with the run. Examples
teach editorial decisions; they do not establish facts for unrelated topics. References are read-only.

## CLI examples (from repository root)

```powershell
# The production pipeline, one video of a run directory holding lesson_plan.json.
python generation/run.py <directory> --video c01-v01

# Complete candidate, default target about 4600 words.
python generation/tools/gen_lore_from_plan.py --plan generation/tools/science_video_plan.json --chapter 1

# Connected Bell sample; its budget applies to the sample, not to a whole video.
python generation/tools/gen_lore_from_plan.py --plan generation/tools/science_video_plan.json --chapter 2 --cold-open-only --target-words 1800

# Inspect five hooks without generating narration.
python generation/tools/gen_lore_from_plan.py --plan generation/tools/science_video_plan.json --chapter 0 --hook-only

# A checked history comparison, with history's own reference set.
python generation/tools/gen_lore_from_plan.py --plan generation/tools/history_reference_plan.json --chapter 0 --target-words 1800

# A history treatment of a science-history topic, using the same research but history references.
python generation/tools/gen_lore_from_plan.py --plan generation/tools/science_video_plan.json --chapter 1 --profile history

# Explicit model choice; separate review model is optional.
python generation/tools/gen_lore_from_plan.py --plan generation/tools/science_video_plan.json --chapter 1 --model claude-group/claude-opus-5-5 --review-model openai-group/gpt-6-astra
```

`--approved-hook-file` overrides the registry with one user-approved first sentence. Multi-paragraph
files are rejected. `--max-revisions` allows 0–3 whole-script revision rounds (default 2); every revision
is reviewed, including the last. `--run-id` must name a new directory. `--list` reads the topic list
without credentials or API initialization. Credentials come from environment variables or
`generation/.env`; only the existing TFY gateway is used.

## Run artifacts

The run lives under `generations/<subject>/<topic>/<run-id>/` and is picked up by the rebuilt viewer.
The subject comes from the input plan, independently of a `--profile` writing-style override.
Metadata records `content_subject` and `narration_profile` separately. The viewer groups legacy runs
by `content_subject` when present, so archived files and their evidence paths need not move. Alternate
profiles are labelled within their actual subject; the subject's own latest run remains the default.
`meta.json` distinguishes generated candidates from hand-curated references and records model,
reasoning, prompt version, token usage, gateway-reported cost, scope, and status.

`editorial/` holds the input research, exact reference excerpts, prompt templates, editorial plan,
all five hooks and per-candidate checks, every narrative version, each review, and duplication
diagnostics. `calls/` records exact prompts, responses, completion status, and usage. Credentials and
request headers are not stored. `result.json` contains the final structure and review history.

`full.txt` is a complete narrative. `opening_sample.txt` is a connected excerpt, without a false
conclusion. `hook_candidates.txt` is a comparison list, not spoken narration. `selected_hook.txt`
shows the model-selected candidate first in the viewer. Hook-only output has no body and
`hook_selection_passed` does not mean user approval.
None is automatically
promoted into the hand-curated reference directory.

## Failure and quality status

Malformed JSON, invalid source IDs, missing or reordered movements, and invented review quotations
get one explicit contract retry. Truncated or empty model responses fail; incomplete prose is never
silently trimmed and published as a complete script. Gateway retries are limited to transient errors.

`candidate_model_review_passed` means only that the configured model found no remaining required
revision. It does not mean human approval, independently verified facts, equivalent quality to the
references, or tested sleep suitability. The CLI retains candidates needing review and exits 2.
The production stage saves the candidate and findings but stops before narration when required
editorial issues remain.
This includes unresolved research and hook selection, not only a failed whole-script review.

Stage `NARRATION` parameters support `model`, `review_model`, `reasoning`, `target_words` (or existing
`target_minutes` × `words_per_minute`), `max_revisions`, `approved_hook`, and `editorial_root`. Source
concepts may be regrouped into narrative movements in `TranscriptLesson.sections`. The `lore` video
type (`config/video_types.json`) turns off avatar video, text slides, infographics, overview diagrams
and the conclusion slide.

## Verification

```powershell
python generation/tools/check_lore_review.py
python generation/tools/check_subject_profiles.py
python generation/tools/check_selfcontained.py
```

The old frozen prompt snapshot is retained as historical evidence. It no longer defines the active
voice: the user explicitly approved changing the prompts. Sentence statistics in `check_lore_style.py`
remain descriptive measurements, not quality targets.

The viewer sorts custom run names by their creation time instead of alphabetic version labels, so
a newer revision appears before an older pilot. Existing timestamp-form run IDs remain supported.

The final science runs use three corrected research notes; a cleaner writing prompt does not make
erroneous research reliable. Fresh generated candidates and their body follow-through still require
editorial inspection.

The [history curation notes](../golden_references/2026-09-23/history-curation-notes.md) document the
new references and checked comparison research. The broad legacy history outlines remain research
candidates; this exercise does not certify every claim in them.

The September 24 prompt trials and their limitations are recorded in
[the prompt reevaluation](../hook_dataset/2026-09-24/prompt-reevaluation.md).
The active prompt version is `reference-editorial-v5.2-prose-first`. The Meitner plan additionally
contains a cached Department of Energy source connecting fission with reactor electricity;
that evidence addition is tracked separately from prompt changes.
