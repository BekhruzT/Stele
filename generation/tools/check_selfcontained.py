#!/usr/bin/env python3
"""Assert that every import in generation/ resolves inside generation/, the stdlib, or
requirements.txt.

This is what makes "this folder is the whole thing" a fact rather than an intention. It
reads the source rather than importing it, so it runs with no dependencies installed and
no credentials.

One way to fail:
  UNDECLARED an import that is not internal, not stdlib, and not in requirements.txt

An internal import with no file behind it lands here too, since nothing else can claim it.
Exits non-zero on any.
"""

from __future__ import annotations

import ast
import re
import sys
import sysconfig
from pathlib import Path

GENERATION = Path(__file__).resolve().parent.parent

# Distributions whose import name is not just the distribution name lowercased.
ALIASES = {
    "pillow": "PIL",
    "opencv-python": "cv2",
    "deepfilternet": "df",
    "beautifulsoup4": "bs4",
    "google-api-python-client": "googleapiclient",
    "google-generativeai": "google",
    "python-dotenv": "dotenv",
    "python-levenshtein": "Levenshtein",
    "boto3": "boto3",
}

# Packages that ship inside another distribution we do ask for.
BUNDLED = {"botocore": "boto3", "google": "google-generativeai"}


def declared() -> set[str]:
    """Every module name requirements.txt entitles us to import."""
    names = set()
    for line in (GENERATION / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        dist = re.split(r"[=<>!~\[]", line)[0].strip()
        names.add(ALIASES.get(dist.lower(), dist.lower().replace("-", "_")))
    names.update(BUNDLED)
    return names


def resolves_in(root: Path, dotted: str) -> bool:
    base = root / Path(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def absolute(module: str | None, level: int, path: Path) -> str:
    """A relative import spelled out, so it can be resolved like any other."""
    if not level:
        return module or ""
    package = path.relative_to(GENERATION).parent.parts
    base = ".".join(package[: len(package) - level + 1])
    return f"{base}.{module}" if module else base


def imports(path: Path):
    """Every module this file imports, as (dotted name, line number)."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            yield absolute(node.module, node.level, path), node.lineno


def main() -> int:
    stdlib = set(sys.stdlib_module_names)
    # Anything already installed alongside the interpreter is a real package, not a leak.
    site = Path(sysconfig.get_paths()["purelib"])
    allowed = declared()

    # A virtualenv inside generation/ is not part of generation/. Its site-packages hold
    # tens of thousands of files, some of them not even UTF-8.
    skip = {"__pycache__", "site-packages", ".venv", "venv", "env", ".tox"}
    problems: list[tuple[str, Path, int, str]] = []
    files = sorted(p for p in GENERATION.rglob("*.py") if not skip & set(p.parts))

    for path in files:
        for dotted, line in imports(path):
            if not dotted:
                continue
            root = dotted.split(".")[0]
            # generation/ is the package root, and a module may also import a sibling
            # by bare name from within its own folder.
            if (resolves_in(GENERATION, dotted) or resolves_in(GENERATION, root)
                    or resolves_in(path.parent, dotted)):
                continue
            if root in stdlib:
                continue
            if root in allowed or (site / root).exists():
                continue
            elif root in {p.name.split(".")[0] for p in site.glob("*")}:
                continue
            else:
                problems.append(("UNDECLARED", path, line, dotted))

    for kind, path, line, dotted in problems:
        print(f"{kind:<11} {path.relative_to(GENERATION)}:{line}  {dotted}")

    print(f"\n{len(files)} files checked, {len(problems)} problem(s).")
    if not problems:
        print("generation/ is self-contained.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
