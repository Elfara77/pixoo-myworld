"""Tests for the headless renderer / config v2."""

from __future__ import annotations

from pathlib import Path

from pixoo.common.config_manager import ConfigManager
from pixoo.common.models import default_project
from pixoo.engine.renderer import Renderer, substitute_placeholders
from pixoo.engine.scheduler import Scheduler


def test_substitute_placeholders():
    assert substitute_placeholders("CPU {system.cpu}%", {"system.cpu": 42.0}) == "CPU 42%"
    assert substitute_placeholders("x {missing}", {}) == "x —"


def test_render_default_project():
    project = default_project()
    renderer = Renderer()
    scr = project.screens[0]
    values = {"system.cpu": 33.0, "system.ram": 50.0, "system.disk": 70.0}
    frame = renderer.render(scr, project, values, anim_t=0.0)
    assert frame.size == (64, 64)
    assert frame.mode == "RGB"


def test_scheduler_fetch_and_frame():
    project = default_project()
    sched = Scheduler(project)
    values = sched.fetch_values()
    assert "system.cpu" in values
    frame = sched.build_frame()
    assert frame.size == (64, 64)


def test_config_roundtrip(tmp_path: Path):
    project = default_project()
    path = ConfigManager.save(project, tmp_path / "demo.pixoo")
    loaded = ConfigManager.load(path)
    assert loaded.config_version == "2.0"
    assert loaded.meta.name == project.meta.name
    assert len(loaded.screens) == 1
