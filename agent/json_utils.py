from __future__ import annotations

import json
import re
from typing import Any


class JsonParseError(ValueError):
    """Raised when the model response cannot be parsed as a JSON object."""


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1].strip()

    return text[start:].strip()


def _extract_candidate(text: str) -> str:
    cleaned = _strip_code_fences(text)
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    return _extract_first_json_object(cleaned)


def parse_json_object(raw_text: str) -> dict[str, Any]:
    """Parse a model response into a strict top-level JSON object."""

    candidate = _extract_candidate(raw_text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise JsonParseError(f"Response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise JsonParseError("Top-level JSON value must be an object.")
    return data
