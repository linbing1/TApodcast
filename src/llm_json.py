"""Shared parsing for JSON responses returned by the LLM."""

import json


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def loads(text: str) -> object:
    # Models occasionally emit raw control characters (unescaped newlines or
    # tabs) inside string values even in JSON mode; strict=False tolerates them.
    return json.loads(strip_code_fence(text), strict=False)
