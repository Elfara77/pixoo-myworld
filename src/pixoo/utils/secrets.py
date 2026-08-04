"""Resolve ${ENV:NAME} placeholders and load .env files."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_ENV_RE = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")
_dotenv_loaded = False


def load_dotenv(path: str | Path | None = None) -> None:
    """Load .env once (repo root or explicit path)."""
    global _dotenv_loaded
    if _dotenv_loaded and path is None:
        return
    try:
        from dotenv import load_dotenv as _load
    except ImportError:
        return
    if path is not None:
        _load(dotenv_path=path, override=False)
    else:
        root = Path(__file__).resolve().parents[3]
        _load(dotenv_path=root / ".env", override=False)
        _load(override=False)
    _dotenv_loaded = True


def resolve_env_string(value: str) -> str:
    load_dotenv()

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.environ.get(key, "")

    return _ENV_RE.sub(repl, value)


def resolve_secrets(obj: Any) -> Any:
    """Recursively resolve ${ENV:KEY} in strings inside dicts/lists."""
    if isinstance(obj, str):
        return resolve_env_string(obj)
    if isinstance(obj, dict):
        return {k: resolve_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_secrets(v) for v in obj]
    return obj
