"""FastAPI control plane for the headless engine."""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from pixoo import API_VERSION, CONFIG_VERSION, __version__
from pixoo.common.api_schemas import (
    ConfigAcceptResponse,
    CurrentFrameResponse,
    ForceRefreshResponse,
    LogEntry,
    LogsResponse,
    ShutdownResponse,
    StatusResponse,
    VersionResponse,
)
from pixoo.common.config_manager import ConfigManager, ConfigError
from pixoo.common.models import Project
from pixoo.engine.scheduler import Scheduler
from pixoo.utils.logging import MemoryLogHandler

logger = logging.getLogger("pixoo.engine.api")


def create_app(
    scheduler: Scheduler,
    mem_logs: MemoryLogHandler,
    *,
    on_shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    app = FastAPI(title="Pixoo Engine API", version=API_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/version", response_model=VersionResponse)
    def version() -> VersionResponse:
        return VersionResponse(
            api_version=API_VERSION,
            engine_version=__version__,
            config_version=CONFIG_VERSION,
        )

    @app.get("/api/v1/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        st = scheduler.stats
        return StatusResponse(
            status=st.status,
            uptime=st.uptime,
            last_send=st.last_send,
            error_count=st.error_count,
            pixoo_ip=scheduler.project.meta.pixoo_ip,
            sends_ok=st.sends_ok,
        )

    @app.get("/api/v1/current", response_model=CurrentFrameResponse)
    def current() -> CurrentFrameResponse:
        frame = scheduler._last_frame or scheduler.build_frame()
        png = scheduler.renderer.to_png_bytes(frame)
        scr = scheduler.current_screen()
        return CurrentFrameResponse(
            image=base64.b64encode(png).decode("ascii"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            screen_id=scr.id if scr else None,
        )

    @app.post("/api/v1/config", response_model=ConfigAcceptResponse)
    def post_config(body: dict[str, Any]) -> ConfigAcceptResponse:
        try:
            # Accept either raw project or {"project": {...}}
            raw = body.get("project") if isinstance(body.get("project"), dict) else body
            # Ensure version gate via ConfigManager path
            import json
            import tempfile
            from pathlib import Path

            with tempfile.NamedTemporaryFile("w", suffix=".pixoo", delete=False) as tmp:
                json.dump(raw, tmp)
                tmp_path = Path(tmp.name)
            try:
                project = ConfigManager.load(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)
            scheduler.reload_project(project)
            return ConfigAcceptResponse(accepted=True, reload_time=0.5, message="config applied")
        except (ConfigError, Exception) as exc:
            logger.error("Config rejected: %s", exc)
            return ConfigAcceptResponse(accepted=False, reload_time=0.0, message=str(exc))

    @app.get("/api/v1/logs", response_model=LogsResponse)
    def logs(
        since: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> LogsResponse:
        entries = [LogEntry(**e) for e in mem_logs.entries(since=since, limit=limit)]
        return LogsResponse(logs=entries)

    @app.post("/api/v1/force-refresh", response_model=ForceRefreshResponse)
    def force_refresh() -> ForceRefreshResponse:
        frame = scheduler.tick() if False else None
        scheduler.fetch_values()
        frame = scheduler.build_frame()
        ok = scheduler.push_frame(frame, force=True)
        return ForceRefreshResponse(ok=ok, message="pushed" if ok else "push failed")

    @app.post("/api/v1/shutdown", response_model=ShutdownResponse)
    def shutdown() -> ShutdownResponse:
        logger.info("Shutdown requested via API")
        if on_shutdown:
            on_shutdown()
        return ShutdownResponse(ok=True)

    return app
