"""Tag resolution for text elements: {source.path}, formats, time."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# {path} or {path:format}
_TAG_RE = re.compile(r"\{([^{}]+)\}")


def _lookup(data: dict[str, Any], path: str) -> Any:
    if path in data:
        return data[path]
    # dotted path into nested dicts / source flattening
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            # try progressive keys: a.b.c already flat
            return data.get(path)
    return cur


def _format_value(val: Any, fmt: str | None) -> str:
    if val is None:
        return "—"
    if fmt:
        try:
            if isinstance(val, (int, float)):
                return format(val, fmt)
            return format(val, fmt)
        except (ValueError, TypeError):
            pass
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, float):
        if abs(val - round(val)) < 1e-6:
            return str(int(round(val)))
        return f"{val:.1f}"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, dict):
        # prefer common fields
        for key in ("value", "price", "temperature", "summary", "state"):
            if key in val:
                return _format_value(val[key], None)
        return str(val)
    return str(val)


def resolve_tags(text: str, data: dict[str, Any] | None = None) -> str:
    """
    Replace tags in text.

    Examples:
      {system.cpu} → 42
      {weather.temperature:.1f}°C → 12.5°C
      {time:%H:%M} → 14:30
    """
    data = data or {}

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner.startswith("time:") or inner == "time":
            fmt = inner.split(":", 1)[1] if ":" in inner else "%H:%M"
            try:
                return datetime.now().strftime(fmt)
            except Exception:
                return datetime.now().strftime("%H:%M")
        # split format: path:fmt — but path may contain dots; format starts with . , + - or digits-ish
        path, fmt = inner, None
        if ":" in inner:
            # last colon separates format for numbers like .1f or ,,.0f or %+
            left, right = inner.rsplit(":", 1)
            if right and (right[0] in ".,+-" or right[0].isdigit() or right.endswith("f") or right.endswith("d")):
                path, fmt = left, right
        val = _lookup(data, path)
        return _format_value(val, fmt)

    return _TAG_RE.sub(repl, text)


def resolve_nested(obj: Any, data: dict[str, Any]) -> Any:
    """Resolve tags inside strings in nested structures."""
    if isinstance(obj, str):
        if "{" in obj and "}" in obj:
            return resolve_tags(obj, data)
        return obj
    if isinstance(obj, dict):
        return {k: resolve_nested(v, data) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_nested(v, data) for v in obj]
    return obj
