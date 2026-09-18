"""A local-filesystem stand-in for core.clients.s3, selected with STORAGE=local.

Every public name here mirrors the s3.py function of the same name, so the swap happens
once at the bottom of s3.py and none of the 25 modules that import from it change. An S3
key maps straight onto a path below LOCAL_STORAGE_ROOT, which keeps the on-disk tree
readable: the artifact for a lesson sits at exactly the key the S3 version would have used.

Two deliberate differences from the S3 behaviour, both forced by there being no network:

- upload_file_to_s3 and copy_s3_object return the *key*, where S3 returns an https URL.
  This is what the callers actually want. They overwhelmingly store the result and presign
  it later (core/clients/openai.py stores it as an image src, stages/image_clips.py then
  does `src if 'http' in src else create_presigned_url(src)`), so handing back a key routes
  them through create_presigned_url below, while a file:// URL would satisfy neither branch.

- create_presigned_url returns a base64 data URI instead of a signed https URL. OpenAI's
  vision endpoint accepts data URIs, which is what keeps image QC working offline. Nothing
  else can consume one, so it refuses anything that is not an image.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# OpenAI rejects images above 20MB, and a data URI larger than that is a request that fails
# obscurely rather than a QC result. Refuse it here where the message can say why.
MAX_DATA_URI_BYTES = 20 * 1024 * 1024


def storage_root() -> Path:
    """Where the artifact tree lives. Read per call so tests can point it at a temp dir."""
    return Path(os.getenv("LOCAL_STORAGE_ROOT")
                or Path(__file__).resolve().parents[2] / "artifacts")


# Characters S3 keys allow but Windows forbids in a path component. Every real course name
# contains one: "AP US History: Video Lessons". Percent-encoded so the mapping is reversible
# and the tree stays legible. '%' is escaped first so an encoded segment round-trips.
#
# ponytail: this covers the reserved characters, not the other Windows path rules -- a
# segment ending in a dot or a space, or named CON/PRN/AUX, would still fail. No key does
# that today. Widen _RESERVED if one ever does.
_RESERVED = '%<>:"|?*'
_ENCODED = re.compile(r"%([0-9A-F]{2})")


def _encode(segment: str) -> str:
    for char in _RESERVED:
        segment = segment.replace(char, f"%{ord(char):02X}")
    return segment


def _decode(segment: str) -> str:
    return _ENCODED.sub(lambda m: chr(int(m.group(1), 16)), segment)


def path_for(key: str) -> Path:
    """Resolve an S3 key to its file, encoding included. Public because anything telling a
    human where to put a file has to name the real path, not the key.

    Leading slashes are stripped so the key stays relative.

    ponytail: the bucket argument every caller may pass is ignored, so the main bucket and
    the two hardcoded ones ('gen-ai-textbooks-media', S3_BUCKET_UI) share one tree. Their
    key prefixes do not overlap today, so nothing collides. If that changes, namespace this
    by bucket -- note that s3.py itself is inconsistent about the default, with some
    functions defaulting to S3_BUCKET and others to the literal 'gen-ai-textbooks-dev'.
    """
    return storage_root().joinpath(*(_encode(part) for part in str(key).lstrip("/").split("/")))


def _write(key: str, data: bytes) -> Path:
    target = path_for(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _keys_under(prefix: str) -> list:
    """Every key starting with `prefix`, matching S3 prefix semantics rather than dir listing.

    Walks only the nearest existing ancestor directory instead of the whole root, so a
    narrow prefix stays cheap.
    """
    prefix = str(prefix).lstrip("/")
    root = storage_root()
    start = path_for(prefix if prefix.endswith("/") else os.path.dirname(prefix))
    if not start.is_dir():
        return []
    found = []
    for path in start.rglob("*"):
        if path.is_file():
            key = "/".join(_decode(part) for part in path.relative_to(root).parts)
            if key.startswith(prefix):
                found.append(key)
    return sorted(found)


def get_last_modified_time(key: str):
    # Timezone-aware to match boto3's LastModified, which callers may compare against.
    return datetime.fromtimestamp(path_for(key).stat().st_mtime, tz=timezone.utc)


def list_files_in_directory(directory, return_type: str = 'full_path'):
    keys = _keys_under(directory)
    return keys if return_type == 'full_path' else [os.path.basename(k) for k in keys]


def create_presigned_url(key, bucket='gen-ai-textbooks-dev', expiration=3600, url_style='path'):
    """A base64 data URI for a local image. bucket, expiration and url_style are ignored."""
    path = path_for(key)
    if not path.is_file():
        logger.error(f"Cannot build a data URI for missing file {key}")
        return None

    content_type = mimetypes.guess_type(path.name)[0] or ''
    if not content_type.startswith('image/'):
        raise ValueError(
            f"STORAGE=local can only presign images, not {content_type or 'unknown type'} "
            f"({key}). Audio and video are presigned only by the D-ID and Video Gen Clips "
            f"steps, which local mode skips because vendors must fetch the URL."
        )

    size = path.stat().st_size
    if size > MAX_DATA_URI_BYTES:
        raise ValueError(
            f"{key} is {size / 1e6:.1f}MB, over the {MAX_DATA_URI_BYTES / 1e6:.0f}MB a data "
            f"URI can carry to OpenAI. Shrink the image or run this stage against S3."
        )

    return f"data:{content_type};base64,{base64.b64encode(path.read_bytes()).decode()}"


def download_directory(s3_directory, local_directory):
    Path(local_directory).mkdir(parents=True, exist_ok=True)
    for key in _keys_under(s3_directory):
        shutil.copyfile(path_for(key), f"{local_directory}/{os.path.basename(key)}")


def download(s3_path, local_path, bucket='gen-ai-textbooks-dev'):
    try:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path_for(s3_path), local_path)
    except Exception as e:
        logger.error(f"Failed to download: {s3_path}, to {local_path}. {e}")
        raise e


def does_path_exist(prefix):
    return bool(_keys_under(prefix))


def does_file_exist(file_path):
    return path_for(file_path).is_file()


def save_file_to_s3(content, file_path, s3_bucket=None, detect_mimetype=False):
    _write(file_path, content if isinstance(content, bytes) else str(content).encode('utf-8'))


def upload_file_to_s3(local_file_path, s3_file_path, s3_bucket=None, detect_mimetype=False):
    _write(s3_file_path, Path(local_file_path).read_bytes())
    return s3_file_path


def copy_s3_object(source_path: str, destination_path: str, s3_bucket=None,
                   s3_destination_bucket=None) -> str:
    _write(destination_path, path_for(source_path).read_bytes())
    return destination_path


def save_json_to_s3(content, file_path, save=False):
    _write(file_path, json.dumps(content, indent=2).encode('utf-8'))


def filter_s3_files(key, file_name, regex=r'Retry(\d+)'):
    retry_files = {}
    max_retry_count = -1
    max_retry_file = None
    for found in _keys_under(key):
        if not found.endswith(file_name):
            continue
        match = re.search(regex, found)
        if match:
            retry_files["Retry" + match.group(1)] = found
            if int(match.group(1)) > max_retry_count:
                max_retry_count = int(match.group(1))
                max_retry_file = found
    return max_retry_file, retry_files


def read_content_from_s3(file_name):
    try:
        return path_for(file_name).read_bytes()
    except Exception as e:
        raise Exception(f"{e}. On file {file_name}")


def read_file_from_s3(file_name):
    return read_content_from_s3(file_name).decode('utf-8')


def load_json_from_s3(path):
    try:
        return json.loads(read_file_from_s3(path))
    except Exception as e:
        logger.error(f"ERROR. When loading file {path}. {e}")
        raise e


def delete_file_from_s3(path, s3_bucket=None):
    path_for(path).unlink(missing_ok=True)


def upload_dir(local_dir, s3_prefix, s3_bucket=None, detect_mimetype=False):
    for local_file_path in Path(local_dir).rglob("*"):
        if local_file_path.is_file():
            relative = local_file_path.relative_to(local_dir).as_posix()
            upload_file_to_s3(str(local_file_path), f"{s3_prefix.rstrip('/')}/{relative}")


def rename_s3_file(old_key, new_key):
    target = path_for(new_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path_for(old_key)), str(target))


def save_content_to_s3(bytes_stream, file_path):
    _write(file_path, bytes_stream)


def copy_s3_folder(current_dir, new_dir):
    for key in _keys_under(current_dir):
        _write(key.replace(current_dir, new_dir, 1), path_for(key).read_bytes())


def check_folder_exists(folder_key):
    return bool(_keys_under(folder_key))


def get_folder_link(folder_path: str, s3_bucket=None) -> str:
    return path_for(folder_path).as_uri()


# What s3.py rebinds. Kept explicit so adding a helper here does not silently shadow an
# S3 function that was deliberately left alone (get_s3_client and S3_BUCKET, for instance,
# stay on boto3 because core/post_evaluations.py imports them for a skipped code path).
OVERRIDES = [
    "check_folder_exists", "copy_s3_folder", "copy_s3_object", "create_presigned_url",
    "delete_file_from_s3", "does_file_exist", "does_path_exist", "download",
    "download_directory", "filter_s3_files", "get_folder_link", "get_last_modified_time",
    "list_files_in_directory", "load_json_from_s3", "read_content_from_s3",
    "read_file_from_s3", "rename_s3_file", "save_content_to_s3", "save_file_to_s3",
    "save_json_to_s3", "upload_dir", "upload_file_to_s3",
]
