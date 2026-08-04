"""Pydantic configuration models (config_version gated)."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class ElementType(str, Enum):
    TEXT = "text"
    GAUGE = "gauge"
    GRAPH = "graph"
    IMAGE = "image"
    # Extended types retained for migration / rich dashboards
    BAR = "bar"
    PIE = "pie"
    SPARKLINE = "sparkline"
    RECT = "rect"
    PATTERN = "pattern"
    STATUS_DOT = "status_dot"
    VALUE = "value"


class TextElement(BaseModel):
    id: str = "el"
    type: Literal["text"] = "text"
    x: int = Field(ge=0, le=63, default=2)
    y: int = Field(ge=0, le=63, default=2)
    w: int = Field(ge=1, le=64, default=60)
    h: int = Field(ge=1, le=64, default=10)
    z: int = 0
    content: str = "Label"
    color: str = "#FFFFFF"
    font: str = "pixel_5x7"
    animation: Optional[Literal["marquee", "fade", "none"]] = "none"
    speed: Optional[int] = 1
    visible: bool = True

    model_config = {"extra": "allow"}


class GaugeElement(BaseModel):
    id: str = "el"
    type: Literal["gauge"] = "gauge"
    x: int = Field(ge=0, le=63, default=2)
    y: int = Field(ge=0, le=63, default=40)
    w: int = Field(ge=1, le=64, default=60)
    h: int = Field(ge=1, le=64, default=6)
    z: int = 0
    source: str = "system.cpu"  # plugin.key
    style: Literal["bar", "pie"] = "bar"
    color: str = "#28DC64"
    color_warn: str = "#F0C828"
    color_crit: str = "#FF4646"
    color_bg: str = "#14141C"
    warn_at: float = 70.0
    crit_at: float = 90.0
    visible: bool = True

    model_config = {"extra": "allow"}


class GraphElement(BaseModel):
    id: str = "el"
    type: Literal["graph"] = "graph"
    x: int = Field(ge=0, le=63, default=2)
    y: int = Field(ge=0, le=63, default=46)
    w: int = Field(ge=1, le=64, default=60)
    h: int = Field(ge=1, le=64, default=14)
    z: int = 0
    source: str = "system.cpu"
    period: str = "15m"
    color: str = "#3CC8FF"
    color_bg: str = "#14141C"
    show_progress: bool = True
    history_points: int = 56
    visible: bool = True

    model_config = {"extra": "allow"}


class ImageElement(BaseModel):
    id: str = "el"
    type: Literal["image"] = "image"
    x: int = Field(ge=0, le=63, default=0)
    y: int = Field(ge=0, le=63, default=0)
    w: int = Field(ge=1, le=64, default=64)
    h: int = Field(ge=1, le=64, default=64)
    z: int = 0
    path: str = ""
    visible: bool = True

    model_config = {"extra": "allow"}


class GenericElement(BaseModel):
    """Fallback for migrated / extended element types."""

    id: str = "el"
    type: str = "rect"
    x: int = Field(ge=0, le=63, default=0)
    y: int = Field(ge=0, le=63, default=0)
    w: int = Field(ge=1, le=64, default=8)
    h: int = Field(ge=1, le=64, default=8)
    z: int = 0
    visible: bool = True

    model_config = {"extra": "allow"}


AnyElement = Annotated[
    Union[TextElement, GaugeElement, GraphElement, ImageElement, GenericElement],
    Field(discriminator="type"),
]


class Screen(BaseModel):
    id: str
    title: str = "Screen"
    duration_s: float = 8.0
    background: str = "#000000"
    transition: Literal["none", "fade", "slide"] = "fade"
    transition_ms: int = 400
    elements: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class DataSourceConfig(BaseModel):
    id: str
    label: str = ""
    plugin: str = "system"
    config: dict[str, Any] = Field(default_factory=dict)
    unit: str = ""
    min_value: float = 0.0
    max_value: float = 100.0

    model_config = {"extra": "allow"}


class ProjectMeta(BaseModel):
    name: str = "Untitled"
    author: str = ""
    pixoo_ip: str = "192.168.1.137"
    brightness: int = Field(default=60, ge=0, le=100)
    created_at: Optional[str] = None
    modified_at: Optional[str] = None
    notes: str = ""

    model_config = {"extra": "allow"}


class RuntimeSettings(BaseModel):
    auto_send: bool = True
    send_interval_s: float = Field(default=1.0, ge=1.0)  # rate limit >= 1s
    ui_fps: int = Field(default=20, ge=5, le=60)
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    max_backoff_s: float = 60.0

    model_config = {"extra": "allow"}


class Project(BaseModel):
    """Versioned .pixoo document."""

    config_version: str = "2.0"
    meta: ProjectMeta = Field(default_factory=ProjectMeta)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    sources: list[DataSourceConfig] = Field(default_factory=list)
    screens: list[Screen] = Field(default_factory=list)
    history: dict[str, list[float]] = Field(default_factory=dict)

    model_config = {"extra": "allow"}

    @field_validator("config_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        from pixoo import COMPATIBLE_CONFIG_VERSIONS

        if v not in COMPATIBLE_CONFIG_VERSIONS:
            raise ValueError(
                f"Incompatible config_version {v!r}; "
                f"supported: {sorted(COMPATIBLE_CONFIG_VERSIONS)}"
            )
        return v


def default_project() -> Project:
    return Project(
        meta=ProjectMeta(name="Demo", notes="graph_n_motor demo"),
        sources=[
            DataSourceConfig(id="system.cpu", label="CPU", plugin="system", config={"key": "cpu"}, unit="%"),
            DataSourceConfig(id="system.ram", label="RAM", plugin="system", config={"key": "ram"}, unit="%"),
            DataSourceConfig(id="system.disk", label="Disk", plugin="system", config={"key": "disk"}, unit="%"),
        ],
        screens=[
            Screen(
                id="scr_main",
                title="CPU",
                elements=[
                    {
                        "id": "t1",
                        "type": "text",
                        "x": 2,
                        "y": 2,
                        "content": "CPU {system.cpu}%",
                        "color": "#3CC8FF",
                        "animation": "marquee",
                        "speed": 20,
                    },
                    {
                        "id": "g1",
                        "type": "gauge",
                        "x": 2,
                        "y": 24,
                        "w": 60,
                        "h": 8,
                        "source": "system.cpu",
                        "style": "bar",
                        "color": "#28DC64",
                    },
                    {
                        "id": "gr1",
                        "type": "graph",
                        "x": 2,
                        "y": 40,
                        "w": 60,
                        "h": 20,
                        "source": "system.cpu",
                        "color": "#3CC8FF",
                    },
                ],
            )
        ],
    )
