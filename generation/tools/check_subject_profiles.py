#!/usr/bin/env python3
"""Check editorial prompt/profile contracts; `--show <id>` prints a profile's prompts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from string import Formatter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.subject_profiles import PROFILES, resolve_profile  # noqa: E402
from prompts.lore_prompts import PROMPTS, render  # noqa: E402

# The pre-v2 snapshot under tools/goldens is historical evidence, not the active contract.
RUNTIME_SLOTS = {name: ({"voice"} if name in {"DRAFT_SYS", "REPAIR_SYS"} else set()) for name in PROMPTS}


def snapshot(profile_id: str) -> str:
    voice = PROFILES[profile_id].voice
    return "\n".join(f"===== {name} =====\n{render(template, voice)}" for name, template in PROMPTS.items())


def check_every_slot_is_filled() -> None:
    """A $slot left in a rendered prompt means a profile field is missing, not a runtime value."""
    for profile_id, profile in PROFILES.items():
        for name, template in PROMPTS.items():
            if "$" in render(template, profile.voice):
                raise AssertionError(f"{profile_id}/{name} still has an unfilled $slot")
    print(f"  filled     no unfilled $slots across {len(PROFILES)} lore profile(s)")


def check_runtime_slots_are_stable() -> None:
    """The {slots} a rendered prompt leaves open are the contract with the stage and the plan tool."""
    for name, template in PROMPTS.items():
        found = {field for _, field, _, _ in Formatter().parse(render(template, PROFILES["history"].voice)) if field}
        if found != RUNTIME_SLOTS[name]:
            raise AssertionError(f"{name} runtime slots changed: expected {RUNTIME_SLOTS[name]}, found {found}")
    print(f"  slots      {sum(map(len, RUNTIME_SLOTS.values()))} runtime slots across {len(PROMPTS)} prompts unchanged")


def check_resolution_refuses_to_guess() -> None:
    """An unknown subject must raise rather than silently pick a profile."""
    assert resolve_profile("World History").id == "history"
    assert resolve_profile("anything", explicit="history").id == "history"
    assert resolve_profile("anything", explicit="science").id == "science"
    assert resolve_profile("Physics 201").id == "science"
    for bad, kwargs in (("Astronomy 101", {}), ("x", {"explicit": "astronomy"})):
        try:
            resolve_profile(bad, **kwargs)
        except ValueError as e:
            assert "have: history, science" in str(e), e
        else:
            raise AssertionError(f"resolve_profile({bad!r}, {kwargs}) should have raised")
    print("  resolution alias match works, unknown subject and unknown id both refused")


def check_image_conditions_fill() -> None:
    """QC conditions are templates; every runtime slot must fill without a KeyError."""
    runtime = dict(period="1200-1450 CE", location="Samarkand", subject="history", title="Trade routes")
    filled = PROFILES["history"].images.conditions(**runtime)
    assert len(filled) == 5 and "{" not in "".join(filled), filled
    science = PROFILES["science"].images.conditions(**runtime)
    # Science conditions must not lean on {period}: it is the chapter title, which only history dates.
    assert len(science) == 5 and "{" not in "".join(science) and "1200-1450 CE" not in "".join(science), science
    assert not PROFILES["science"].images.detect_maps
    print("  images     history and science conditions fill, map detection stays history-only")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", metavar="PROFILE", help="print this profile's rendered prompts and exit")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.show:
        if args.show not in PROFILES:
            raise SystemExit(f"unknown profile {args.show!r}; have: {', '.join(sorted(PROFILES))}")
        print(snapshot(args.show))
        return 0

    for check in (check_every_slot_is_filled, check_runtime_slots_are_stable,
                  check_resolution_refuses_to_guess, check_image_conditions_fill):
        check()
    print("\nAll subject profile checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
