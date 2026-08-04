"""Named setup presets — save/load full config snapshots under configs/setups/."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import load_config, project_root, write_config

SETUPS_DIRNAME = "configs/setups"
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def setups_dir() -> Path:
    return project_root() / SETUPS_DIRNAME


def sanitize_setup_name(name: str) -> str:
    raw = (name or "").strip()
    # Spaces → dashes ; strip unsafe chars
    cleaned = re.sub(r"\s+", "-", raw)
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "", cleaned)
    cleaned = cleaned.strip(".-_")
    if not cleaned or not NAME_RE.match(cleaned):
        raise ValueError(
            f"Nom de setup invalide: {name!r} "
            "(lettres, chiffres, ._- ; commencer par alphanumérique)"
        )
    return cleaned


def setup_path(name: str) -> Path:
    return setups_dir() / f"{sanitize_setup_name(name)}.toml"


def list_setups() -> list[str]:
    d = setups_dir()
    if not d.is_dir():
        return []
    names = sorted(p.stem for p in d.glob("*.toml") if p.is_file())
    return names


def save_setup(name: str, data: dict[str, Any], *, force: bool = False) -> Path:
    """Écrit un snapshot nommé. Refuse l'écrasement sauf force=True."""
    safe = sanitize_setup_name(name)
    path = setups_dir() / f"{safe}.toml"
    setups_dir().mkdir(parents=True, exist_ok=True)
    if path.is_file() and not force:
        raise FileExistsError(
            f"Setup « {safe} » existe déjà ({path}). Utilise --force pour écraser."
        )
    snapshot = dict(data)
    snapshot["setup_name"] = safe
    # Ne pas persister les clés runtime
    snapshot.pop("_config_path", None)
    snapshot.pop("_resolved_metrics", None)
    snapshot.pop("_profile_override", None)
    write_config(path, snapshot)
    return path


def load_setup(name: str) -> dict[str, Any]:
    path = setup_path(name)
    if not path.is_file():
        known = ", ".join(list_setups()) or "(aucun)"
        raise FileNotFoundError(
            f"Setup « {sanitize_setup_name(name)} » introuvable. Disponibles: {known}"
        )
    return load_config(path)


def apply_setup_to_active(name: str, *, active_path: Path | None = None) -> Path:
    """Charge un setup nommé et l'écrit comme config.toml active."""
    data = load_setup(name)
    out = active_path or (project_root() / "config.toml")
    data["setup_name"] = sanitize_setup_name(name)
    data.pop("_config_path", None)
    data.pop("_resolved_metrics", None)
    data.pop("_profile_override", None)
    write_config(out, data)
    return out


def delete_setup(name: str) -> Path:
    path = setup_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"Setup « {sanitize_setup_name(name)} » introuvable")
    path.unlink()
    return path


def active_setup_name(cfg: dict[str, Any] | None) -> str:
    if not cfg:
        return ""
    name = cfg.get("setup_name")
    return str(name).strip() if name else ""
