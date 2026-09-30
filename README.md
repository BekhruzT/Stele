# Stele

An AI video pipeline for turning a lesson plan into long-form narrated history and science videos.

Point it at a directory, local or `s3://bucket/prefix`, that holds a `lesson_plan.json`, and it
writes every video's artifacts and a rendered MP4 back into that directory, one folder per video.

Everything lives in [`generation/`](generation/). Start there:

- [generation/README.md](generation/README.md) — install, credentials, running, storage
- [generation/docs/](generation/docs/) — the architecture set, one doc per stage
- [generation/docs/lore_input_spec.md](generation/docs/lore_input_spec.md) — the `lesson_plan.json` format
- [generation/docs/architecture/13-generation-layout.md](generation/docs/architecture/13-generation-layout.md) — the map of the tree

`generation/` is self-contained by design and by check: nothing in it imports anything
outside it, and `generation/tools/check_selfcontained.py` fails if that stops being true.
There is nothing else in this repository to know about.
