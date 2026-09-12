import hashlib
import json


def hash_code(data):
    if isinstance(data, dict):
        json_str = json.dumps(data, sort_keys=True).encode()
        return hashlib.sha256(json_str).hexdigest()[:8]
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:8]


def hash_image_description(image_description):
    snake_case_description = image_description.replace(' ', '_').lower()
    hashed_image_description = hash_code(snake_case_description)
    return hashed_image_description
