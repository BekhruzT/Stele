"""Pull a JSON object out of an LLM's reply.

The three functions below are copied verbatim from the textbook tree's
configs/scripts/outputs/parsers/common.py, which is 530 lines of which the video pipeline
imports only str_2_json. Taking the chain rather than the file keeps markdown,
markdown_to_json and jsonschema out of this package.
"""

import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


def extract_json_response_fallback(text):
    try:
        json.loads(text)
        return text
    except Exception as e:
        logger.error(f"Invalid json response - failed to parse! {e}")
        raise Exception("Invalid json response - failed to parse!")


def extract_json_response(text):
    matches = re.findall(r"```json(.*?)```", text, re.DOTALL)

    if len(matches) == 0:
        return extract_json_response_fallback(text)
    elif len(matches) > 1:
        logger.error("Found more than 1 json string.")
        raise Exception("Found more than 1 json string.")

    json_string = matches[0]
    return json_string


def str_2_json(_str: str) -> Dict[Any, Any]:
    _str = _str.replace("\n\n", "\n")
    try:
        return json.loads(extract_json_response(_str))
    except:
        try:
            return json.loads(_str)
        except Exception as e:
            logger.error(f"Error {e}. {repr(_str)}")
            raise Exception(f"Error {e}. {repr(_str)}")
