from typing import List, Dict, Any
import random
import pandas as pd
import math
import mimetypes
from pathlib import Path


def round_robin(elements: List[Any]) -> Any:
    if not elements:
        return None
    return random.choice(elements)

path_extension_to_content_type_mapping = {
    ".ttf": "font/ttf",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".css": "text/css",
    ".html": "text/html"
}


def replace_placeholders(text, **kwargs):
    for key, val in kwargs.items():
        text = text.replace(f"${key}", str(val))
    return text


def flatten(nested_data: List[List]):
    return [item for data in nested_data for item in data]


def batch_list(input_list, batch_size):
    return [input_list[index:index+batch_size] for index in range(0, len(input_list), batch_size)]


def rows_to_csv(rows, output_path):
    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)


def normalize(text):
    chars_to_replace = ' :/'
    for char in chars_to_replace:
        text = text.replace(char, '-')
    return text.lower()


def pk(*args):
    return "#".join(args)


def index_by_key(items: List[Dict], key: str):
    indexed_items = {}
    for item in items:
        indexed_items[item[key]] = item
    return indexed_items


def round_ceil(num):
    return math.ceil(num * 10) / 10


def shift_char(char, n):
    return chr(ord(char) + n)


def detect_content_type(file_path: str) -> str:
    content_type = mimetypes.guess_type(file_path)[0]
    if not content_type:
        extension = Path(file_path).suffix
        return path_extension_to_content_type_mapping.get(extension, 'binary/octet-stream')
    return content_type
