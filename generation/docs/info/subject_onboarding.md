# Onboarding a subject

Subject vocabulary and visual settings live in `config/subject_profiles.py`. Narration also needs
an appropriate reference set; domain-specific editorial guidance can live in the shared prompt module.

## Steps

1. Add a `SubjectProfile` to `config/subject_profiles.py` and list it in `PROFILES`.
   For a new narration genre, add a reference set keyed by `genre_noun` in
   `docs/golden_references/2026-09-23/style-reference-catalog.json`. Missing sets fail explicitly.
2. Run `python tools/check_subject_profiles.py --show <id>` and read the prompts the model will actually see.
3. Point the plan at it with `_meta.subject_profile: "<id>"`, or give the profile an alias that appears in the subject name; `gen_lore_from_plan.py --profile <id>` overrides both for a one-off run.
4. Run `python tools/check_subject_profiles.py` — profile resolution and all active template slots must pass.

## Fields

`id` and `aliases` are the resolution keys. `images` is required; `lore` is only needed to narrate the subject.

### `lore` — the narration voice

The active reference-led narration uses `genre_noun`, `jargon_examples`, and `figure_noun`.
Editorial, evidence, and continuity rules are shared in `prompts/lore_prompts.py`; see
[the operating guide](lore_editorial_pipeline.md). History additionally receives `HISTORY_GUIDANCE`
and its own style-reference set. Other `LoreVoice` fields are retained for
compatibility with older profiles and do not control the current narrator.

### `images` — the visual style

| field | where it lands |
| --- | --- |
| `tuning_instructions` | the image description prompt |
| `qc_accuracy`, `qc_instructions`, `qc_must` | the image QC prompts |
| `qc_conditions` | the per-image pass/fail list; `{period}` (the chapter), `{location}`, `{subject}` and `{title}` fill at runtime |
| `detect_maps` | whether a clip may be a web-sourced map instead of a generated still |

## Worth knowing

- **Resolution never guesses.** An unknown subject or id raises listing the known ids. First alias match wins in `PROFILES` order, so a narrower alias must come before a broader one.
- **A profile without `lore` still works for images** and refuses loudly for narration.
- **Reference excerpts teach form, not facts.** They are labeled and recorded separately from the current topic research.
- **A field may carry a line break.** Read the rendered prompts when adding a voice.
- **`{period}` is the plan's chapter title.** It names an era only when the chapters do, so a subject whose chapters are not dated should not lean on it in `qc_conditions`.
- **Shared editorial changes belong in the shared prompts.** Subject-specific vocabulary belongs in the profile. Run the checks and inspect generated prose after either change.
