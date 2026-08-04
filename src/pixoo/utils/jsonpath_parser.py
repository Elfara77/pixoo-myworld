"""JSONPath extraction helpers (jsonpath-ng)."""

from __future__ import annotations

from typing import Any

from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError


def extract_path(config: dict[str, Any]) -> str:
    """Return extract_path or legacy jsonpath key."""
    return str(config.get("extract_path") or config.get("jsonpath") or "").strip()


def extract_jsonpath(data: Any, path: str, *, default: Any = None) -> Any:
    """Extract first JSONPath match; return default if missing/invalid."""
    path = (path or "").strip()
    if not path or path in (".", "$"):
        return data if data is not None else default
    try:
        expr = jsonpath_parse(path)
    except (JsonPathParserError, Exception):
        return default
    matches = expr.find(data)
    if not matches:
        return default
    return matches[0].value


def validate_jsonpath(path: str) -> bool:
    path = (path or "").strip()
    if not path:
        return False
    try:
        jsonpath_parse(path)
        return True
    except Exception:
        return False
