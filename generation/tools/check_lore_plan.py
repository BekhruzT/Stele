"""Recompute estimated_concepts in lore_video_plan.json and flag near-duplicate beats across lessons of the same video."""
import json
import re
import sys
from pathlib import Path

PLAN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "lore_video_plan.json"
SHINGLE = 6  # ponytail: fixed 6-word shingles catch verbatim/near-verbatim retellings only; paraphrased dupes need an embedding pass, not this script.


def shingles(text: str, n: int = SHINGLE) -> set[str]:
    """Return the set of lowercase n-word shingles in text."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def main() -> int:
    """Recompute counts, print cross-lesson duplicate beats, rewrite the plan in place."""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    total, dup_pairs = 0, 0

    for chapter in plan["chapters"]:
        for video in chapter["videos"]:
            beats = [(li, bi, b) for li, lesson in enumerate(video["lessons"])
                     for bi, b in enumerate(lesson["concepts"]) if b.strip()]
            video["estimated_concepts"] = len(beats)
            total += len(beats)

            seen: dict[str, tuple[int, int]] = {}
            reported: set[tuple[tuple[int, int], tuple[int, int]]] = set()
            for li, bi, beat in beats:
                for sh in shingles(beat):
                    prev = seen.setdefault(sh, (li, bi))
                    pair = (prev, (li, bi))
                    if prev[0] != li and pair not in reported:
                        reported.add(pair)
                        dup_pairs += 1
                        print(f"DUP  {video['title'][:48]!r}  L{prev[0]+1}b{prev[1]+1} ~ L{li+1}b{bi+1}  \"{sh}\"")

    n_videos = sum(len(c["videos"]) for c in plan["chapters"])
    plan["_summary"]["total_videos"] = n_videos
    plan["_summary"]["total_estimated_concepts"] = total
    plan["_summary"]["avg_concepts_per_video"] = round(total / n_videos)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{n_videos} videos, {total} beats (avg {total / n_videos:.1f}/video), {dup_pairs} cross-lesson near-duplicate pairs.")
    return 1 if dup_pairs else 0


if __name__ == "__main__":
    sys.exit(main())
