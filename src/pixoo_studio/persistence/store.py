"""Persistance projets `.pixoo` (JSON versionné)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.models import (
    DataSourceDef,
    Element,
    Project,
    ProjectMeta,
    RuntimeSettings,
    Screen,
    SourceBinding,
    default_project,
)


CURRENT_VERSION = 2


class ProjectStore:
    """Charge / sauve des documents Studio."""

    @staticmethod
    def save(project: Project, path: str | Path) -> Path:
        path = Path(path)
        if path.suffix.lower() != ".pixoo":
            path = path.with_suffix(".pixoo")
        path.parent.mkdir(parents=True, exist_ok=True)
        project.version = CURRENT_VERSION
        path.write_text(json.dumps(project.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def load(path: str | Path) -> Project:
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Fichier .pixoo invalide")
        data = migrate(data)
        return Project.from_dict(data)


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Migrates designer v1 / pixoo.json → studio v2."""
    version = int(data.get("version") or 1)
    out = dict(data)
    if version < 2:
        out = _migrate_v1_to_v2(out)
    out["version"] = CURRENT_VERSION
    if "runtime" not in out or not isinstance(out.get("runtime"), dict):
        out["runtime"] = RuntimeSettings().__dict__
    return out


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Convertit l'ancien format pixoo_designer (sources kind/builtin_key)."""
    sources_in = data.get("sources") or []
    sources_out: list[dict[str, Any]] = []
    for s in sources_in:
        if not isinstance(s, dict):
            continue
        if "plugin_id" in s:
            sources_out.append(s)
            continue
        kind = str(s.get("kind") or "builtin")
        cfg: dict[str, Any] = {}
        plugin = "builtin_psutil"
        if kind == "builtin":
            plugin = "builtin_psutil"
            cfg = {"key": s.get("builtin_key") or "cpu"}
        elif kind == "command":
            plugin = "shell_command"
            cfg = {
                "command": s.get("command") or "",
                "cwd": s.get("cwd") or "",
                "timeout_s": float(s.get("timeout_s") or 3),
                "parse_mode": s.get("parse_mode") or "float",
                "parse_expr": s.get("parse_expr") or "",
            }
        elif kind == "http":
            plugin = "rest_jsonpath"
            cfg = {
                "url": s.get("url") or "",
                "jsonpath": s.get("parse_expr") or "$",
                "timeout_s": float(s.get("timeout_s") or 3),
            }
        elif kind == "static":
            plugin = "static_value"
            cfg = {"value": float(s.get("static_value") or 0)}
        sources_out.append(
            DataSourceDef(
                id=str(s.get("id")),
                label=str(s.get("label") or s.get("id")),
                plugin_id=plugin,
                config=cfg,
                unit=str(s.get("unit") or "%"),
                min_value=float(s.get("min_value") or 0),
                max_value=float(s.get("max_value") or 100),
            ).to_dict()
        )

    # screens: ensure transition fields
    screens = []
    for scr in data.get("screens") or []:
        if not isinstance(scr, dict):
            continue
        scr = dict(scr)
        scr.setdefault("transition", "fade")
        scr.setdefault("transition_ms", 400)
        for el in scr.get("elements") or []:
            if isinstance(el, dict):
                el.setdefault("overflow", "clip")
                el.setdefault("marquee_speed", 20.0)
        screens.append(scr)

    meta = data.get("meta") or {}
    return {
        "version": 2,
        "meta": meta,
        "runtime": {
            "auto_send": False,
            "send_interval_s": float(meta.get("refresh_s") or 3.0),
            "max_backoff_s": 60.0,
            "preview_zoom": 8,
        },
        "sources": sources_out,
        "screens": screens,
        "history_preview": data.get("history_preview") or {},
    }


def ensure_demo(path: Path | None = None) -> Path:
    root = Path(__file__).resolve().parents[3]
    dest = path or (root / "projects" / "demo.pixoo")
    if not dest.is_file():
        ProjectStore.save(default_project(), dest)
    return dest
