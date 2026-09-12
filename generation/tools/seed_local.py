#!/usr/bin/env python3
"""Copy S3 keys or prefixes into the local artifact tree, for STORAGE=local runs.

Local mode can generate every stage artifact but not its inputs: the course lesson plan
comes from S3, and run.py reads it before it can list a single lesson. This pulls those
inputs down, resolving each key through local_store.path_for so the on-disk name carries
the same reserved-character encoding a local run will look for.

Reads S3 through core.aws.get_session(), the same path the pipeline uses, so if this works
the pipeline's credentials work too.

    python tools/seed_local.py                      # the lesson plan for the default subject
    python tools/seed_local.py --prefix "some/s3/prefix/"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

for _env in (Path(__file__).resolve().parent.parent / ".env",
             Path(__file__).resolve().parent.parent.parent / ".env"):
    if _env.is_file():
        load_dotenv(_env)
        break

from config.courses import get_execution_input  # noqa: E402
from core.aws import get_session  # noqa: E402
from core.clients.local_store import path_for, storage_root  # noqa: E402
from core.constants import S3_BUCKET  # noqa: E402
from core.path import get_lesson_plan_path  # noqa: E402


def fetch(client, key: str) -> bool:
    destination = path_for(key)
    if destination.is_file():
        print(f"  have  {key}")
        return True
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(S3_BUCKET, key, str(destination))
    except Exception as error:
        print(f"  FAIL  {key}\n          {type(error).__name__}: {str(error)[:120]}")
        return False
    print(f"  got   {key}  ({destination.stat().st_size:,} bytes)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", default="AP US History - v2")
    parser.add_argument("--prefix", action="append", default=[],
                        help="repeatable; copy every key under this S3 prefix")
    parser.add_argument("--key", action="append", default=[], help="repeatable; one exact key")
    args = parser.parse_args()

    client = get_session().client("s3")
    print(f"bucket {S3_BUCKET}  ->  {storage_root()}")

    keys = list(args.key)
    if not args.prefix and not args.key:
        execution_input = get_execution_input(args.subject)["ExecutionInput"]
        keys.append(get_lesson_plan_path(execution_input["course"],
                                         execution_input["curriculum"],
                                         execution_input["subject"]))

    for prefix in args.prefix:
        pages = client.get_paginator("list_objects_v2").paginate(Bucket=S3_BUCKET, Prefix=prefix)
        found = [obj["Key"] for page in pages for obj in page.get("Contents", [])]
        print(f"{len(found)} key(s) under {prefix}")
        keys.extend(found)

    failures = sum(not fetch(client, key) for key in keys)
    print(f"\n{len(keys) - failures}/{len(keys)} seeded")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
