"""Load and apply preconfigured plugin templates."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pixoo.common.models import DataSourceConfig, Project, Screen

logger = logging.getLogger("pixoo.studio.templates")

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "plugins" / "templates"


class TemplateManager:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or TEMPLATES_DIR

    def list_templates(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if not self.directory.is_dir():
            return out
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": path.stem,
                        "name": str(data.get("name") or path.stem),
                        "description": str(data.get("description") or ""),
                        "path": str(path),
                    }
                )
            except Exception as exc:
                logger.warning("Bad template %s: %s", path, exc)
        return out

    def load(self, template_id: str) -> dict[str, Any]:
        path = self.directory / f"{template_id}.json"
        if not path.is_file():
            # allow full path stem match
            matches = list(self.directory.glob(f"{template_id}*.json"))
            if not matches:
                raise FileNotFoundError(template_id)
            path = matches[0]
        return json.loads(path.read_text(encoding="utf-8"))

    def apply_to_project(self, project: Project, template_id: str, *, replace_screens: bool = False) -> Project:
        """Merge template sources/screens into project (mutates and returns)."""
        data = self.load(template_id)
        cfg = data.get("config") or {}
        for s in cfg.get("sources") or []:
            src = DataSourceConfig.model_validate(s)
            project.sources = [x for x in project.sources if x.id != src.id] + [src]
        screens_raw = cfg.get("screens") or []
        new_screens = [Screen.model_validate(sc) for sc in screens_raw]
        if replace_screens:
            project.screens = new_screens
        else:
            existing = {s.id for s in project.screens}
            for sc in new_screens:
                if sc.id in existing:
                    sc.id = f"{sc.id}_tpl"
                project.screens.append(sc)
        return project
