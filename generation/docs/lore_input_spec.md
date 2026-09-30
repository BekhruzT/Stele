# Lore research input

A run directory's `lesson_plan.json` provides the research for every video `run.py` builds; the
same format feeds `tools/gen_lore_from_plan.py`. Research notes are selected and grouped into a
story; one note does not become one fixed-length passage. The writer sees the whole plan and
drafts the connected narrative in one context. A passing input is not a guarantee of quality or
runtime.

## File contract

```json
{
  "_meta": {"subject": "World History", "subject_profile": "history"},
  "chapters": [
    {"chapter": "Chapter 1: The Medieval World",
     "videos": [
       {"title": "The World in 1200",
        "lessons": [{"name": "Song China in 1200", "concepts": ["One research passage.", "..."]}]}
     ]}
  ]
}
```

- `_meta.subject` names the subject; `_meta.subject_profile` optionally names the profile
  (`history` or `science`) outright. `config/subject_profiles.py::resolve_profile` refuses an
  unknown profile or a subject no profile's aliases match. `tools/gen_lore_from_plan.py --profile`
  overrides the writing profile.
- `chapters[].chapter` gives the subject context and becomes the video's `chapter`.
- `chapters[].videos[].title` states the actual story being told. It also names the video's
  folder, `c{chapter:02d}-v{video:02d}-{slug}`, so reordering or retitling videos moves their
  artifacts.
- `lessons[].name` identifies a research grouping and is required; `concepts[]` contains the
  research passages. Blank passages are dropped, and a video with none fails the Video Plan stage.
- Other keys (`_meta.purpose`, `chapter_notes`, `hook_idea`, `estimated_concepts`) are carried for
  the authoring tools and not read by `run.py`. The hook stage selects from the research and
  editorial brief rather than copying a proposed `hook_idea`.

In the pipeline, the Video Plan stage arranges a video's passages into sections and concepts, and
the transcript stage takes `VideoPlan.sections[].concepts[]` as its research. Lore may regroup
those concepts into narrative movements; its output uses `TranscriptLesson` and one Host voice.

## Research quality

Give the story a central question, a person or investigation to follow, and an honest resolution.
Provide the evidence needed to understand the question, not just a list of memorable objects.

For each useful event or experiment, include the situation, action, observation, and what the
evidence does and does not establish. Explain a comparison or mechanism before recording optional
dimensions and reagent quantities. Distinguish the observed result from an interpretation and its
later confirmation. Supply necessary prerequisites a non-specialist would otherwise have to guess.

Keep sources and uncertainty close to the claims they support. Attribute recollections and disputes;
preserve ranges and qualifications. Include exact quotations only when their wording has been
checked. State contradictory evidence rather than silently picking a convenient version. Do not
invent an absence of evidence, undocumented scene details, or a historical person's private thoughts.

Useful human details should show something about the people or investigation. They do not need to
be startling. Select distressing details for relevance to the bedtime experience. Administrative
chronology, biographies, apparatus specifications, and source provenance can stay in research when
they do not help the listener understand the story.

## Hooks

The first sentence establishes the subject, any necessary premise, and a real reason to listen.
A consequence can supply interest without giving away its explanation. There is no required hard
number, shock, superlative, myth-bust, or 15-word ceiling. Necessary qualifications remain.
The body follows directly; it does not have to repeat a promise inventory or restart the story.

See [the curation notes](golden_references/2026-09-23/curation-notes.md) and
[the approved hooks](golden_references/2026-09-23/approved-hooks.json) for the approved and
rejected examples from the actual editing session.

## What is checked

The editorial plan assigns every source ID to selected material or an explicit omission. A note may
support different details in more than one movement, but a scene should not be retold without new
understanding. Source-ID coverage measures an explicit editorial decision, not compulsory narration.

Mechanical checks validate structure and report exact duplication. Whole-script model review checks
clarity, selection, explanation, development, joins, source fidelity, and conclusions. Neither is a
substitute for checking the underlying research or listening to the result.

There is no mandatory note inventory, per-note word minimum, or claim that input counts guarantee a
runtime. Request a word budget appropriate to the story and inspect actual output. If useful source
material is insufficient, gather more evidence or make a shorter video. Never fill the gap with
repeated conclusions or atmosphere. `tools/check_lore_plan.py` is a research inventory diagnostic;
its counts are not generation acceptance criteria.
