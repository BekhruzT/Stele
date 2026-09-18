#!/usr/bin/env python3
"""Check deterministic narration pause safety and tiers."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.clients.speech import _BREAK_RE, _SENTENCE_END_RE, add_narration_pauses  # noqa: E402


def main() -> int:
    """Verify pause placement, duration tiers, idempotence, and word preservation."""
    paragraphs = [
        "[Host]: " + " ".join(["harbor clock sailor voyage"] * 30) + ".",
        " ".join(["harbor clock sailor voyage"] * 30) + ".",
        " ".join(["distant orchard manuscript kingdom"] * 25) + ".",
        " ".join(["harbor clock sailor voyage"] * 30) + ".",
        "In 1759, " + " ".join(["Harrison watch London trial"] * 20) + ".",
    ]
    raw = "\n\n".join(paragraphs)
    paced = add_narration_pauses(raw)
    tags = [match.group(0) for match in _BREAK_RE.finditer(paced)]
    assert tags
    assert all(_SENTENCE_END_RE.search(paced[:match.start()].rstrip())
               for match in _BREAK_RE.finditer(paced))
    assert " ".join(_BREAK_RE.sub("", paced).split()) == " ".join(raw.split())
    assert add_narration_pauses(paced) == paced
    assert set(float(tag.split('"')[1][:-1]) for tag in tags) <= {1.0, 1.5, 2.0, 2.5}
    incomplete = ("unfinished phrase " * 250).strip() + "\n\nA complete sentence."
    assert not _BREAK_RE.search(add_narration_pauses(incomplete))
    print(f"pause check ok: {len(tags)} sentence-boundary breaks, words unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
