"""HTTP client used by Studio to talk to the engine API."""

from __future__ import annotations

import base64
import io
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from PIL import Image

from pixoo import API_VERSION

logger = logging.getLogger("pixoo.studio.sync")


class VersionMismatchError(RuntimeError):
    pass


class SyncClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def is_reachable(self) -> bool:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(self._url("/api/v1/version"))
                return r.status_code == 200
        except Exception:
            return False

    def check_version(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(self._url("/api/v1/version"))
            r.raise_for_status()
            data = r.json()
        if data.get("api_version") != API_VERSION:
            raise VersionMismatchError(
                f"Engine API {data.get('api_version')!r} incompatible with studio {API_VERSION!r}. "
                "Please upgrade engine or studio."
            )
        return data

    def status(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(self._url("/api/v1/status"))
            r.raise_for_status()
            return r.json()

    def push_config(self, project_dict: dict[str, Any]) -> dict[str, Any]:
        self.check_version()
        with httpx.Client(timeout=max(5.0, self.timeout)) as client:
            r = client.post(self._url("/api/v1/config"), json=project_dict)
            r.raise_for_status()
            return r.json()

    def current_image(self) -> tuple[Image.Image | None, dict[str, Any]]:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(self._url("/api/v1/current"))
            r.raise_for_status()
            data = r.json()
        raw = base64.b64decode(data["image"])
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        return img, data

    def force_refresh(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(self._url("/api/v1/force-refresh"))
            r.raise_for_status()
            return r.json()

    def logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(self._url("/api/v1/logs"), params={"limit": limit})
            r.raise_for_status()
            return list(r.json().get("logs") or [])

    def sources(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(self._url("/api/v1/sources"))
            r.raise_for_status()
            return r.json()

    def start_engine(self, project: Path, *, host: str = "127.0.0.1", port: int = 8765) -> bool:
        if self.is_reachable():
            return True
        cmd = [
            sys.executable,
            "-m",
            "pixoo.main",
            "daemon",
            "--project",
            str(project),
            "--host",
            host,
            "--port",
            str(port),
        ]
        logger.info("Starting engine: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[3]))
        for _ in range(40):
            time.sleep(0.25)
            if self.is_reachable():
                return True
        return False

    def shutdown_engine(self) -> None:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                client.post(self._url("/api/v1/shutdown"))
        except Exception:
            pass
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
