"""Load / save versioned .pixoo JSON projects."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pixoo import COMPATIBLE_CONFIG_VERSIONS, CONFIG_VERSION
from pixoo.common.models import Project, default_project


class ConfigError(Exception):
    """Raised when a project file cannot be loaded or is incompatible."""


class ConfigManager:
    """Version-gated project persistence."""

    @staticmethod
    def save(project: Project, path: str | Path) -> Path:
        path = Path(path)
        if path.suffix.lower() != ".pixoo":
            path = path.with_suffix(".pixoo")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = project.model_dump(mode="json")
        data["config_version"] = CONFIG_VERSION
        now = datetime.now(timezone.utc).isoformat()
        meta = data.setdefault("meta", {})
        meta["modified_at"] = now
        if not meta.get("created_at"):
            meta["created_at"] = now
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def load(path: str | Path) -> Project:
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Cannot read project: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("Invalid project root (expected JSON object)")
        raw = migrate_document(raw)
        version = str(raw.get("config_version") or raw.get("version") or "")
        if version not in COMPATIBLE_CONFIG_VERSIONS:
            raise ConfigError(
                f"Incompatible config_version {version!r}. "
                f"Supported: {sorted(COMPATIBLE_CONFIG_VERSIONS)}. "
                "Please upgrade the project or the engine."
            )
        try:
            return Project.model_validate(raw)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

    @staticmethod
    def new_default(path: str | Path | None = None) -> Project:
        project = default_project()
        if path:
            ConfigManager.save(project, path)
        return project


def migrate_document(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy studio / designer documents to config_version 2.0."""
    out = dict(data)
    # Already v2.0 pixoo package
    if str(out.get("config_version")) == "2.0":
        return out

    # Legacy pixoo_studio version: 2 with plugin_id fields
    if "config_version" not in out and (out.get("version") in (1, 2) or "screens" in out):
        sources_in = out.get("sources") or []
        sources_out: list[dict[str, Any]] = []
        for s in sources_in:
            if not isinstance(s, dict):
                continue
            if "plugin" in s and "plugin_id" not in s:
                sources_out.append(s)
                continue
            plugin_id = str(s.get("plugin_id") or s.get("plugin") or "system")
            cfg = dict(s.get("config") or {})
            # Map old builtin ids
            if plugin_id in ("builtin_psutil", "system"):
                plugin = "system"
                if "key" not in cfg:
                    cfg["key"] = s.get("builtin_key") or cfg.get("key") or "cpu"
            elif plugin_id in ("rest_jsonpath", "rest_api"):
                plugin = "rest_api"
                cfg.setdefault("url", s.get("url") or "")
                cfg.setdefault("jsonpath", s.get("parse_expr") or cfg.get("jsonpath") or "$")
                cfg.setdefault("method", "GET")
            elif plugin_id in ("shell_command", "shell"):
                plugin = "shell"
            else:
                plugin = plugin_id
            sid = str(s.get("id") or "src")
            # Prefer namespaced ids for placeholders
            if "." not in sid and plugin == "system":
                key = cfg.get("key", "cpu")
                sid = f"system.{key}"
            sources_out.append(
                {
                    "id": sid,
                    "label": s.get("label") or sid,
                    "plugin": plugin,
                    "config": cfg,
                    "unit": s.get("unit") or "%",
                    "min_value": float(s.get("min_value") or 0),
                    "max_value": float(s.get("max_value") or 100),
                }
            )

        screens_out = []
        for scr in out.get("screens") or []:
            if not isinstance(scr, dict):
                continue
            els = []
            for el in scr.get("elements") or []:
                if not isinstance(el, dict):
                    continue
                els.append(_migrate_element(el))
            screens_out.append(
                {
                    "id": scr.get("id"),
                    "title": scr.get("title") or "Screen",
                    "duration_s": float(scr.get("duration_s") or 8),
                    "background": scr.get("background") or "#000000",
                    "transition": scr.get("transition") or "fade",
                    "transition_ms": int(scr.get("transition_ms") or 400),
                    "elements": els,
                }
            )

        meta = out.get("meta") or {}
        runtime = out.get("runtime") or {}
        return {
            "config_version": "2.0",
            "meta": meta,
            "runtime": {
                "auto_send": bool(runtime.get("auto_send", True)),
                "send_interval_s": max(1.0, float(runtime.get("send_interval_s") or 1.0)),
                "ui_fps": int(runtime.get("preview_zoom") and 20 or runtime.get("ui_fps") or 20),
                "api_host": runtime.get("api_host") or "127.0.0.1",
                "api_port": int(runtime.get("api_port") or 8765),
                "max_backoff_s": float(runtime.get("max_backoff_s") or 60),
            },
            "sources": sources_out,
            "screens": screens_out,
            "history": out.get("history") or out.get("history_preview") or {},
        }

    out.setdefault("config_version", "2.0")
    return out


def _migrate_element(el: dict[str, Any]) -> dict[str, Any]:
    t = str(el.get("type") or "text")
    base = {
        "id": el.get("id") or "el",
        "x": int(el.get("x") or 0),
        "y": int(el.get("y") or 0),
        "w": int(el.get("w") or 8),
        "h": int(el.get("h") or 8),
        "z": int(el.get("z") or 0),
        "visible": bool(el.get("visible", True)),
    }
    if t == "text":
        return {
            **base,
            "type": "text",
            "content": el.get("content") or el.get("text") or "Label",
            "color": el.get("color") or "#FFFFFF",
            "animation": "marquee" if el.get("overflow") == "marquee" else (el.get("animation") or "none"),
            "speed": int(el.get("marquee_speed") or el.get("speed") or 20),
        }
    if t in ("bar", "pie", "gauge"):
        return {
            **base,
            "type": "gauge",
            "source": el.get("source") or el.get("source_id") or "system.cpu",
            "style": "pie" if t == "pie" or el.get("style") == "pie" else "bar",
            "color": el.get("color") or "#28DC64",
            "color_warn": el.get("color_warn") or "#F0C828",
            "color_crit": el.get("color_crit") or "#FF4646",
            "color_bg": el.get("color_bg") or "#14141C",
            "warn_at": float(el.get("warn_at") or 70),
            "crit_at": float(el.get("crit_at") or 90),
        }
    if t in ("sparkline", "graph"):
        return {
            **base,
            "type": "graph",
            "source": el.get("source") or el.get("source_id") or "system.cpu",
            "period": el.get("period") or "15m",
            "color": el.get("color") or "#3CC8FF",
            "color_bg": el.get("color_bg") or "#14141C",
            "show_progress": bool(el.get("show_progress", True)),
            "history_points": int(el.get("history_points") or 56),
        }
    if t == "value":
        src = el.get("source_id") or "system.cpu"
        return {
            **base,
            "type": "text",
            "content": el.get("format") or f"{{{src}}}",
            "color": el.get("color") or "#FFFFFF",
            "animation": "none",
        }
    # keep as generic
    return {**el, **base, "type": t}
