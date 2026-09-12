# AP video pipeline

Turns one subsection of a course lesson plan into a narrated, animated video lesson.

Everything lives in [`generation/`](generation/). Start there:

- [generation/README.md](generation/README.md) — install, run, and the local-folder mode
- [generation/docs/](generation/docs/) — the architecture set, one doc per stage
- [generation/docs/architecture/13-generation-layout.md](generation/docs/architecture/13-generation-layout.md) — the map of the tree

`generation/` is self-contained by design and by check: nothing in it imports anything
outside it, and `generation/tools/check_selfcontained.py` fails if that stops being true.
There is nothing else in this repository to know about.
