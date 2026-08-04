"""Regex extraction helpers."""

from __future__ import annotations

import re
from typing import Any


def extract_regex(text: str, pattern: str, *, group: int = 1, multiple: bool = False) -> Any:
    """Apply regex to text; return group or full match."""
    if not text or not pattern:
        return None
    try:
        rx = re.compile(pattern)
    except re.error:
        return None
    if multiple:
        out: list[str] = []
        for m in rx.finditer(text):
            if m.lastindex and group <= m.lastindex:
                out.append(m.group(group))
            else:
                out.append(m.group(0))
        return out or None
    m = rx.search(text)
    if not m:
        return None
    if m.lastindex and group <= m.lastindex:
        return m.group(group)
    return m.group(0)
