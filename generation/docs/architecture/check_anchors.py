"""Verify every code anchor in the architecture docs resolves. Run from anywhere: python check_anchors.py

The docs anchor code as `path/file.py::symbol` rather than by line number, so the one thing
that can rot silently is an anchor. A broken anchor is worse than no doc, because it sends a
reader to a symbol that does not exist.

Paths are relative to generation/. Qualified anchors are checked against the exact file. Bare
`::symbol` anchors are written relative to the module under discussion, so they are checked
for existence anywhere in the tree instead.

ponytail: the bare-anchor check is tree-wide rather than per-doc, so it catches an invented
name but not one attributed to the wrong module. Tightening it means tracking each doc's
current module, which is only worth doing if a misattribution actually bites.
"""
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
GENERATION = DOCS.parents[1]

# A virtualenv is not source. Its site-packages hold tens of thousands of files.
SKIP = {"__pycache__", "site-packages", ".venv", "venv", ".tox", "node_modules"}

QUALIFIED = re.compile(r"`([\w/\.\-]+\.(?:py|json|sh))::(\w+)`")
BARE = re.compile(r"`::(\w+)`")
DEFINED = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)|^\s*(\w+)\s*[:=]", re.M)

# The convention statement in 00-overview.md, not a reference to anything.
IGNORE_QUALIFIED = {("path/file.py", "symbol")}


def defined_names(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {g for m in DEFINED.finditer(text) for g in m.groups() if g}


def sources() -> list[Path]:
    return [py for py in GENERATION.rglob("*.py") if not SKIP & set(py.parts)]


def main() -> int:
    all_names: set[str] = set()
    for py in sources():
        all_names |= defined_names(py)

    bad_files: list[tuple[str, str]] = []
    bad_symbols: list[tuple[str, str, str]] = []
    bad_bare: list[tuple[str, str]] = []
    n_qual = n_bare = 0
    docs = sorted(DOCS.glob("*.md"))

    for doc in docs:
        text = doc.read_text(encoding="utf-8")

        for rel, sym in QUALIFIED.findall(text):
            if (rel, sym) in IGNORE_QUALIFIED:
                continue
            n_qual += 1
            target = GENERATION / rel
            if not target.is_file():
                bad_files.append((doc.name, rel))
            elif target.suffix == ".py" and sym not in defined_names(target):
                bad_symbols.append((doc.name, rel, sym))

        for sym in BARE.findall(text):
            n_bare += 1
            if sym not in all_names:
                bad_bare.append((doc.name, sym))

    print(f"checked {n_qual} qualified and {n_bare} bare anchors across {len(docs)} docs\n")

    for doc, rel in bad_files:
        print(f"MISSING FILE   {doc}: {rel}")
    for doc, rel, sym in bad_symbols:
        print(f"MISSING SYMBOL {doc}: {rel}::{sym}")
    for doc, sym in sorted(set(bad_bare)):
        print(f"UNKNOWN BARE   {doc}: ::{sym}")

    total = len(bad_files) + len(bad_symbols) + len(set(bad_bare))
    print(f"\n{total} unresolved" if total else "\nall anchors resolve")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
