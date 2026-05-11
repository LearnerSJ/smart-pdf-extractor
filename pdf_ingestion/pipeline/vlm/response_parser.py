"""Utility for cleaning VLM responses before JSON parsing."""

import re


def strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from VLM responses.

    Claude often wraps JSON in ```json ... ``` blocks.
    This strips those fences to get clean JSON.
    """
    if not text:
        return text
    # Strip ```json ... ``` or ``` ... ```
    pattern = r'^```(?:json)?\s*\n?(.*?)\n?```\s*$'
    match = re.match(pattern, text.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()
