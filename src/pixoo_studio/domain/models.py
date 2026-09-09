"""Domain models — purs, sans Qt (SOLID: indépendants de l'UI)."""

from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ElementType = Literal[
    "text",
    "value",
    "bar",
    "pie",
    "sparkline",
    "rect",
    "pattern",
    "status_dot",
]

TransitionType = Literal["none", "fade", "slide"]
OverflowMode = Literal["clip", "marquee"]


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class SourceBinding:
    """Liaison élément → plugin de données."""

    plugin_id: str = "builtin_psutil"
    config: dict[str, Any] = field(default_factory=dict)
    # id logique de source dans le projet (pour cache / history)
    source_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"plugin_id": self.plugin_id, "config": dict(self.config), "source_id": self.source_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SourceBinding:
        if not data:
            return cls()
        return cls(
            plugin_id=str(data.get("plugin_id") or "builtin_psutil"),
            config=dict(data.get("config") or {}),
            source_id=str(data.get("source_id") or ""),
        )


@dataclass
class DataSourceDef:
    """Source déclarée dans le projet (instance configurée d'un plugin)."""

    id: str
    label: str = ""
    plugin_id: str = "builtin_psutil"
    config: dict[str, Any] = field(default_factory=dict)
    unit: str = "%"
    min_value: float = 0.0
    max_value: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataSourceDef:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Element:
    id: str
    type: ElementType = "text"
    x: int = 2
    y: int = 2
    w: int = 60
    h: int = 8
    text: str = ""
    source_id: str = ""
    binding: SourceBinding | None = None
    color: str = "#3CC8FF"
    color_warn: str = "#F0C828"
    color_crit: str = "#FF4646"
    color_bg: str = "#14141C"
    color_secondary: str = "#282837"
    font_size: int = 1
    overflow: OverflowMode = "clip"
    marquee_speed: float = 20.0  # px/s
    period: str = "15m"
    history_points: int = 56
    show_progress: bool = True
    pattern: str = "none"
    pattern_color: str = "#1E1E2A"
    format: str = "{v:.0f}{u}"
    warn_at: float = 70.0
    crit_at: float = 90.0
    visible: bool = True
    z: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.binding is None:
            d["binding"] = None
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Element:
        raw = dict(data)
        binding = raw.pop("binding", None)
        known = cls.__dataclass_fields__
        el = cls(**{k: v for k, v in raw.items() if k in known and k != "binding"})
        el.binding = SourceBinding.from_dict(binding) if binding else None
        return el


@dataclass
class Screen:
    id: str
    title: str = "Screen"
    title_mode: str = "custom"
    duration_s: float = 8.0
    background: str = "#000000"
    transition: TransitionType = "fade"
    transition_ms: int = 400
    elements: list[Element] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "title_mode": self.title_mode,
            "duration_s": self.duration_s,
            "background": self.background,
            "transition": self.transition,
            "transition_ms": self.transition_ms,
            "elements": [e.to_dict() for e in self.elements],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Screen:
        els = [Element.from_dict(e) for e in (data.get("elements") or []) if isinstance(e, dict)]
        return cls(
            id=str(data.get("id") or new_id("scr")),
            title=str(data.get("title") or "Screen"),
            title_mode=str(data.get("title_mode") or "custom"),
            duration_s=float(data.get("duration_s") or 8.0),
            background=str(data.get("background") or "#000000"),
            transition=str(data.get("transition") or "fade"),  # type: ignore[arg-type]
            transition_ms=int(data.get("transition_ms") or 400),
            elements=els,
        )


@dataclass
class ProjectMeta:
    name: str = "Untitled"
    author: str = ""
    pixoo_ip: str = "192.168.1.137"
    brightness: int = 60
    render_mode: str = "native"
    refresh_s: float = 3.0
    ui_fps: int = 20
    notes: str = ""


@dataclass
class RuntimeSettings:
    auto_send: bool = False
    send_interval_s: float = 3.0
    max_backoff_s: float = 60.0
    preview_zoom: int = 8


@dataclass
class Project:
    """Document Studio (.pixoo)."""

    version: int = 2
    meta: ProjectMeta = field(default_factory=ProjectMeta)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    sources: list[DataSourceDef] = field(default_factory=list)
    screens: list[Screen] = field(default_factory=list)
    history_preview: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "meta": asdict(self.meta),
            "runtime": asdict(self.runtime),
            "sources": [s.to_dict() for s in self.sources],
            "screens": [s.to_dict() for s in self.screens],
            "history_preview": self.history_preview,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        meta_raw = data.get("meta") or {}
        meta = ProjectMeta(**{k: v for k, v in meta_raw.items() if k in ProjectMeta.__dataclass_fields__})
        rt_raw = data.get("runtime") or {}
        runtime = RuntimeSettings(**{k: v for k, v in rt_raw.items() if k in RuntimeSettings.__dataclass_fields__})
        sources = [DataSourceDef.from_dict(s) for s in (data.get("sources") or []) if isinstance(s, dict)]
        screens = [Screen.from_dict(s) for s in (data.get("screens") or []) if isinstance(s, dict)]
        hist = data.get("history_preview") or {}
        if not isinstance(hist, dict):
            hist = {}
        return cls(
            version=int(data.get("version") or 2),
            meta=meta,
            runtime=runtime,
            sources=sources,
            screens=screens,
            history_preview={str(k): [float(x) for x in v] for k, v in hist.items() if isinstance(v, list)},
        )

    def clone(self) -> Project:
        return Project.from_dict(copy.deepcopy(self.to_dict()))

    def source_by_id(self, sid: str) -> DataSourceDef | None:
        for s in self.sources:
            if s.id == sid:
                return s
        return None

    def screen_by_id(self, sid: str) -> Screen | None:
        for s in self.screens:
            if s.id == sid:
                return s
        return None


def new_element(etype: ElementType, **kwargs: Any) -> Element:
    defaults: dict[str, Any] = {
        "text": {"type": "text", "text": "Label", "h": 10},
        "value": {"type": "value", "format": "{v:.0f}{u}", "font_size": 2, "h": 12},
        "bar": {"type": "bar", "h": 6, "w": 60},
        "pie": {"type": "pie", "w": 24, "h": 24},
        "sparkline": {"type": "sparkline", "h": 16, "w": 60, "period": "15m"},
        "status_dot": {"type": "status_dot", "w": 8, "h": 8},
        "rect": {"type": "rect", "w": 20, "h": 10, "color": "#1E1E2A"},
        "pattern": {"type": "pattern", "x": 0, "y": 0, "w": 64, "h": 64, "pattern": "dots"},
    }
    base = {**defaults.get(etype, {"type": etype}), **kwargs}
    return Element(id=new_id("el"), **base)


def default_project() -> Project:
    src_cpu = DataSourceDef(
        id="src_cpu",
        label="CPU %",
        plugin_id="builtin_psutil",
        config={"key": "cpu"},
        unit="%",
    )
    src_disk = DataSourceDef(
        id="src_disk",
        label="Disk %",
        plugin_id="builtin_psutil",
        config={"key": "disk"},
        unit="%",
    )
    src_rest = DataSourceDef(
        id="src_rest_demo",
        label="REST demo (httpbin)",
        plugin_id="rest_jsonpath",
        config={
            "url": "https://httpbin.org/json",
            "jsonpath": "$.slideshow.author",
            "timeout_s": 5.0,
        },
        unit="",
        max_value=1.0,
    )

    scr = Screen(
        id="scr_cpu",
        title="CPU",
        transition="fade",
        elements=[
            new_element("pattern", pattern="grid", pattern_color="#12121A", z=0),
            new_element("text", text="CPU", color="#3CC8FF", overflow="marquee", z=1),
            new_element(
                "value",
                x=2,
                y=14,
                source_id="src_cpu",
                color="#28DC64",
                font_size=3,
                format="{v:.0f}%",
                z=2,
            ),
            new_element("bar", x=2, y=36, source_id="src_cpu", z=2),
            new_element("sparkline", x=2, y=46, source_id="src_cpu", period="15m", z=2),
        ],
    )
    scr_disk = Screen(
        id="scr_disk",
        title="DISK",
        transition="slide",
        elements=[
            new_element("text", text="DISK", color="#3CC8FF", z=1),
            new_element("value", x=2, y=14, source_id="src_disk", color="#F08C28", font_size=3, format="{v:.0f}%", z=2),
            new_element("pie", x=36, y=18, w=26, h=26, source_id="src_disk", color="#F08C28", z=2),
        ],
    )
    return Project(
        meta=ProjectMeta(name="Studio Demo", notes="Projet exemple Pixoo Studio"),
        sources=[src_cpu, src_disk, src_rest],
        screens=[scr, scr_disk],
        history_preview={"src_cpu": [20, 30, 45, 55, 48, 62, 70, 58, 45, 50]},
    )
