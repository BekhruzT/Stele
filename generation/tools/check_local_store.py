#!/usr/bin/env python3
"""Exercise STORAGE=local: the filesystem backend, the rebinding, and the stage skips.

core/clients/local_store.py has to behave like core/clients/s3.py closely enough that the
25 modules importing from s3.py cannot tell the difference, and the swap has to actually
take effect, which it does through a rebinding that is easy to break silently. This asserts
both, plus the two places local mode deliberately diverges: create_presigned_url hands back
a data URI, and the pipeline drops the stages whose vendors must fetch a URL.

Needs no credentials and buys nothing. Run it after any change to the storage layer.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Both must be set before the first core import: s3.py picks its backend at module scope.
_ROOT = tempfile.mkdtemp(prefix="check_local_store_")
os.environ["STORAGE"] = "local"
os.environ["LOCAL_STORAGE_ROOT"] = _ROOT

from core.clients import local_store  # noqa: E402

# A 1x1 PNG, small enough to inline and real enough for mimetypes to classify.
PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
KEY = "college_board/AP US History: Video Lessons/AP US History - v2/contents/subsection"


def check_json_round_trip():
    path = f"{KEY}/Video Plan/abc123.json"
    assert not local_store.does_file_exist(path), "temp root was not empty"

    local_store.save_json_to_s3({"title": "Taxation", "clips": [1, 2]}, path)
    assert local_store.does_file_exist(path)
    assert local_store.load_json_from_s3(path) == {"title": "Taxation", "clips": [1, 2]}
    assert local_store.read_file_from_s3(path).startswith("{")
    assert isinstance(local_store.read_content_from_s3(path), bytes)

    # The key must land on disk mirroring itself, so an artifact can be copied straight in
    # from S3 by hand. The one transformation is the reserved-character encoding below.
    assert local_store.path_for(path).is_file(), sorted(Path(_ROOT).rglob("*"))

    local_store.delete_file_from_s3(path)
    assert not local_store.does_file_exist(path)


def check_windows_reserved_characters():
    """Every real course name contains a colon, which Windows forbids in a path component."""
    assert ":" in KEY, "the fixture stopped covering the case this guards"
    on_disk = local_store.path_for(KEY)
    assert ":" not in str(on_disk)[2:], on_disk  # skip the drive letter
    assert "AP US History%3A Video Lessons" in on_disk.parts, on_disk.parts

    # Reversible, including for a key that already contains a percent sign.
    for key in (KEY, "a/b%3Ac/d.json", 'weird/<>:"|?*/x.json'):
        local_store.save_json_to_s3({"k": key}, f"{key}/probe.json")
        assert local_store.load_json_from_s3(f"{key}/probe.json") == {"k": key}
        assert f"{key}/probe.json" in local_store.list_files_in_directory(key), key


def check_prefix_listing():
    for name in ("a.json", "b.json"):
        local_store.save_json_to_s3({}, f"{KEY}/Images/{name}")
    local_store.save_json_to_s3({}, f"{KEY}/Other/c.json")

    listed = local_store.list_files_in_directory(f"{KEY}/Images")
    assert listed == [f"{KEY}/Images/a.json", f"{KEY}/Images/b.json"], listed
    assert local_store.list_files_in_directory(f"{KEY}/Images", "name") == ["a.json", "b.json"]

    assert local_store.check_folder_exists(f"{KEY}/Images")
    assert local_store.does_path_exist(f"{KEY}/Images")
    assert not local_store.check_folder_exists(f"{KEY}/Nothing")
    # S3 returns an empty page rather than raising, and callers rely on that.
    assert local_store.list_files_in_directory(f"{KEY}/Nothing") == []

    local_store.copy_s3_folder(f"{KEY}/Images", f"{KEY}/ImagesCopy")
    assert len(local_store.list_files_in_directory(f"{KEY}/ImagesCopy")) == 2


def check_file_transfers():
    with tempfile.TemporaryDirectory() as scratch:
        source = Path(scratch) / "clip.png"
        source.write_bytes(PNG)

        # Returns the key, not a URL. stages/image_clips.py branches on `'http' in src` and
        # falls through to create_presigned_url, so a URL here would break that path.
        key = local_store.upload_file_to_s3(str(source), f"{KEY}/media/clip.png")
        assert key == f"{KEY}/media/clip.png", key
        assert "http" not in key
        assert local_store.read_content_from_s3(key) == PNG

        copied = local_store.copy_s3_object(key, f"{KEY}/media/clip-copy.png")
        assert local_store.read_content_from_s3(copied) == PNG

        # download must create the destination directory; callers pass /tmp paths freely.
        out = Path(scratch) / "nested" / "again.png"
        local_store.download(key, str(out))
        assert out.read_bytes() == PNG

        local_store.rename_s3_file(copied, f"{KEY}/media/renamed.png")
        assert not local_store.does_file_exist(copied)
        assert local_store.does_file_exist(f"{KEY}/media/renamed.png")

        local_store.save_file_to_s3("plain text", f"{KEY}/media/note.txt")
        assert local_store.read_file_from_s3(f"{KEY}/media/note.txt") == "plain text"
        local_store.save_content_to_s3(b"raw", f"{KEY}/media/raw.bin")
        assert local_store.read_content_from_s3(f"{KEY}/media/raw.bin") == b"raw"

        assert local_store.get_last_modified_time(key).tzinfo is not None, "must be aware"


def check_presigned_url_is_a_data_uri():
    key = f"{KEY}/media/clip.png"
    url = local_store.create_presigned_url(key)
    assert url.startswith("data:image/png;base64,"), url[:40]
    assert base64.b64decode(url.split(",", 1)[1]) == PNG, "data URI lost the bytes"

    # Audio and video cannot be inlined, and the stages that presign them are skipped, so
    # asking for one is a mistake worth naming rather than a silent broken URL.
    local_store.save_content_to_s3(b"not audio", f"{KEY}/media/voice.mp3")
    try:
        local_store.create_presigned_url(f"{KEY}/media/voice.mp3")
        raise AssertionError("presigning an mp3 should have raised")
    except ValueError as error:
        assert "local" in str(error).lower(), error

    assert local_store.create_presigned_url(f"{KEY}/media/missing.png") is None


def check_rebinding_took_effect():
    from core.clients import s3

    assert s3.is_local()
    for name in local_store.OVERRIDES:
        assert getattr(s3, name) is getattr(local_store, name), f"{name} still points at boto3"

    # The real test is the import form every caller uses, which binds at import time.
    from core.clients.s3 import does_file_exist, save_json_to_s3

    save_json_to_s3({"via": "s3 module"}, f"{KEY}/rebound.json")
    assert does_file_exist(f"{KEY}/rebound.json")
    written = local_store.path_for(f"{KEY}/rebound.json")
    assert json.loads(written.read_text())["via"] == "s3 module", written

    # Left on boto3 on purpose: core/post_evaluations.py imports these for a skipped path.
    assert not hasattr(local_store, "get_s3_client")


def check_pipeline_skips_vendor_stages():
    import run

    assert run.STORAGE == "local", run.STORAGE
    titles = run.pipeline()
    assert run.LOCAL_SKIP == {"Video Gen Clips"}, run.LOCAL_SKIP
    assert not (set(titles) & run.LOCAL_SKIP), titles
    assert len(titles) == 8, titles
    # Avatar Clips stays: its ElevenLabs half builds the lesson_timings that Text Overlays
    # reads, and only the D-ID block inside it is skipped.
    assert "Avatar Clips" in titles
    assert titles.index("Avatar Clips") < titles.index("Text Overlays") < titles.index("Scenes Breakdown")
    # ShotStack is substituted, not dropped, so local mode still ends in a rendered video.
    assert run.LOCAL_SWAP == {"ShotStack": "Local Render"}, run.LOCAL_SWAP
    assert "ShotStack" not in titles and titles[-1] == "Local Render", titles
    assert callable(run.STAGES["Local Render"])


def main() -> int:
    checks = [
        check_json_round_trip,
        check_windows_reserved_characters,
        check_prefix_listing,
        check_file_transfers,
        check_presigned_url_is_a_data_uri,
        check_rebinding_took_effect,
        check_pipeline_skips_vendor_stages,
    ]
    failures = 0
    for check in checks:
        try:
            check()
            print(f"ok    {check.__name__}")
        except Exception as error:
            failures += 1
            print(f"FAIL  {check.__name__}: {type(error).__name__}: {error}")
    print(f"\n{len(checks) - failures}/{len(checks)} passed  (root {_ROOT})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
