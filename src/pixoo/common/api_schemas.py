"""FastAPI request/response schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class VersionResponse(BaseModel):
    api_version: str
    engine_version: str
    config_version: str


class StatusResponse(BaseModel):
    status: str
    uptime: float
    last_send: Optional[str] = None
    error_count: int = 0
    pixoo_ip: str = ""
    sends_ok: int = 0


class CurrentFrameResponse(BaseModel):
    image: str  # base64 PNG
    timestamp: str
    screen_id: Optional[str] = None


class ConfigAcceptResponse(BaseModel):
    accepted: bool
    reload_time: float = 0.5
    message: str = ""


class LogEntry(BaseModel):
    time: str
    level: str
    msg: str


class LogsResponse(BaseModel):
    logs: list[LogEntry] = Field(default_factory=list)


class ForceRefreshResponse(BaseModel):
    ok: bool
    message: str = ""


class ShutdownResponse(BaseModel):
    ok: bool
    message: str = "shutting down"


class SourceStat(BaseModel):
    id: str
    plugin: str
    label: str = ""
    success_rate: float = 1.0
    avg_response_time: float = 0.0
    last_error: Optional[str] = None
    last_success: Optional[str] = None
    last_ms: Optional[float] = None
    cache_hit_rate: float = 0.0
    value_preview: Optional[Any] = None


class SourcesResponse(BaseModel):
    sources: list[SourceStat] = Field(default_factory=list)
    fetch_logs: list[dict[str, Any]] = Field(default_factory=list)
