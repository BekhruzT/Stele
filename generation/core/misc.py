import mimetypes
from pathlib import Path


path_extension_to_content_type_mapping = {
    ".ttf": "font/ttf",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".css": "text/css",
    ".html": "text/html"
}


def normalize(text):
    chars_to_replace = ' :/'
    for char in chars_to_replace:
        text = text.replace(char, '-')
    return text.lower()


def detect_content_type(file_path: str) -> str:
    content_type = mimetypes.guess_type(file_path)[0]
    if not content_type:
        extension = Path(file_path).suffix
        return path_extension_to_content_type_mapping.get(extension, 'binary/octet-stream')
    return content_type
