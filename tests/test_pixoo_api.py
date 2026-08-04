"""FastAPI engine endpoints (in-process)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pixoo.common.models import default_project
from pixoo.engine.api_server import create_app
from pixoo.engine.scheduler import Scheduler
from pixoo.utils.logging import MemoryLogHandler


def _client() -> TestClient:
    sched = Scheduler(default_project())
    sched.fetch_values()
    sched.build_frame()
    return TestClient(create_app(sched, MemoryLogHandler()))


def test_version():
    r = _client().get("/api/v1/version")
    assert r.status_code == 200
    data = r.json()
    assert data["api_version"] == "1.0"
    assert data["config_version"] == "2.0"


def test_status_and_current():
    c = _client()
    assert c.get("/api/v1/status").status_code == 200
    cur = c.get("/api/v1/current")
    assert cur.status_code == 200
    assert cur.json()["image"]


def test_push_config():
    c = _client()
    project = default_project().model_dump(mode="json")
    r = c.post("/api/v1/config", json=project)
    assert r.status_code == 200
    assert r.json()["accepted"] is True
