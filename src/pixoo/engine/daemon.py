"""Headless engine daemon: scheduler loop + FastAPI server."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn

from pixoo.common.config_manager import ConfigManager
from pixoo.common.models import Project
from pixoo.engine.api_server import create_app
from pixoo.engine.scheduler import Scheduler
from pixoo.utils.logging import setup_logging

logger = logging.getLogger("pixoo.engine.daemon")


class EngineDaemon:
    def __init__(self, project: Project, *, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.project = project
        self.host = host
        self.port = port
        self.mem_logs = setup_logging()
        self.scheduler = Scheduler(project)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None

        def _request_stop() -> None:
            self._stop.set()
            if self._server is not None:
                self._server.should_exit = True

        self.app = create_app(self.scheduler, self.mem_logs, on_shutdown=_request_stop)

    def start_loop(self) -> None:
        self.scheduler.stats.status = "running"

        def _run() -> None:
            interval = max(1.0, float(self.project.runtime.send_interval_s))
            while not self._stop.is_set():
                try:
                    self.scheduler.tick()
                except Exception as exc:
                    logger.exception("Tick failed: %s", exc)
                # Sleep in small slices for responsive shutdown
                end = time.monotonic() + interval
                while time.monotonic() < end and not self._stop.is_set():
                    time.sleep(0.05)

        self._thread = threading.Thread(target=_run, name="pixoo-scheduler", daemon=True)
        self._thread.start()

    def run(self) -> None:
        self.start_loop()
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        self._server = uvicorn.Server(config)
        logger.info("Engine API on http://%s:%s", self.host, self.port)
        try:
            self._server.run()
        finally:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=2)

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.should_exit = True


def run_daemon(project_path: str | Path, *, pixoo_ip: str | None = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    project = ConfigManager.load(project_path)
    if pixoo_ip:
        project.meta.pixoo_ip = pixoo_ip
    project.runtime.api_host = host
    project.runtime.api_port = port
    EngineDaemon(project, host=host, port=port).run()
