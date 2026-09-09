"""Modèle de projet designer — écrans, éléments, sources de données."""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
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

SourceKind = Literal["builtin", "command", "http", "static"]
ParseMode = Literal["float", "regex", "json_path", "line_field", "percent"]


def _nid(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class DataSource:
    """Où aller chercher une valeur (builtin, commande, HTTP, static)."""

    id: str
    label: str = ""
    kind: SourceKind = "builtin"
    # builtin: clé psutil/monitoring (cpu, ram, disk, …)
    builtin_key: str = "cpu"
    # command
    command: str = ""
    cwd: str = ""
    timeout_s: float = 3.0
    # http
    url: str = ""
    # parsing du résultat
    parse_mode: ParseMode = "float"
    # regex: groupe 1 = valeur ; json_path: a.b.0.c ; line_field: "line:field" 0-based
    parse_expr: str = ""
    # static
    static_value: float = 0.0
    unit: str = "%"
    # échelle affichage
    min_value: float = 0.0
    max_value: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataSource:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Element:
    """Élément visuel sur un écran 64×64."""

    id: str
    type: ElementType = "text"
    x: int = 2
    y: int = 2
    w: int = 60
    h: int = 8
    # texte / binding
    text: str = ""
    source_id: str = ""
    # style
    color: str = "#3CC8FF"
    color_warn: str = "#F0C828"
    color_crit: str = "#FF4646"
    color_bg: str = "#14141C"
    color_secondary: str = "#282837"
    font_size: int = 1  # 1=sm, 2=md, 3=lg (bitmap-ish)
    align: str = "left"
    # jauges / graphes
    warn_at: float = 70.0
    crit_at: float = 90.0
    # sparkline
    period: str = "15m"  # s/m/h/j/M/a
    history_points: int = 56
    show_progress: bool = True
    # pattern: none|grid|dots|scanlines|noise|diagonal
    pattern: str = "none"
    pattern_color: str = "#1E1E2A"
    # value format
    format: str = "{v:.0f}{u}"
    visible: bool = True
    z: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Element:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Screen:
    id: str
    title: str = "Screen"
    title_mode: str = "custom"  # custom | default | hidden
    duration_s: float = 8.0
    background: str = "#000000"
    elements: list[Element] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "title_mode": self.title_mode,
            "duration_s": self.duration_s,
            "background": self.background,
            "elements": [e.to_dict() for e in self.elements],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Screen:
        els = [Element.from_dict(e) for e in (data.get("elements") or []) if isinstance(e, dict)]
        return cls(
            id=str(data.get("id") or _nid("scr")),
            title=str(data.get("title") or "Screen"),
            title_mode=str(data.get("title_mode") or "custom"),
            duration_s=float(data.get("duration_s") or 8.0),
            background=str(data.get("background") or "#000000"),
            elements=els,
        )


@dataclass
class ProjectMeta:
    name: str = "Untitled"
    author: str = ""
    pixoo_ip: str = "192.168.1.137"
    brightness: int = 60
    render_mode: str = "native"  # native | scaled
    refresh_s: float = 3.0
    notes: str = ""


@dataclass
class Project:
    """Projet designer complet (JSON)."""

    version: int = 1
    meta: ProjectMeta = field(default_factory=ProjectMeta)
    sources: list[DataSource] = field(default_factory=list)
    screens: list[Screen] = field(default_factory=list)
    # historique simulé / réel pour preview sparklines {source_id: [floats]}
    history_preview: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "meta": asdict(self.meta),
            "sources": [s.to_dict() for s in self.sources],
            "screens": [s.to_dict() for s in self.screens],
            "history_preview": self.history_preview,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        meta_raw = data.get("meta") or {}
        meta = ProjectMeta(**{k: v for k, v in meta_raw.items() if k in ProjectMeta.__dataclass_fields__})
        sources = [DataSource.from_dict(s) for s in (data.get("sources") or []) if isinstance(s, dict)]
        screens = [Screen.from_dict(s) for s in (data.get("screens") or []) if isinstance(s, dict)]
        hist = data.get("history_preview") or {}
        if not isinstance(hist, dict):
            hist = {}
        return cls(
            version=int(data.get("version") or 1),
            meta=meta,
            sources=sources,
            screens=screens,
            history_preview={str(k): [float(x) for x in v] for k, v in hist.items() if isinstance(v, list)},
        )

    def clone(self) -> Project:
        return Project.from_dict(copy.deepcopy(self.to_dict()))

    def source_by_id(self, sid: str) -> DataSource | None:
        for s in self.sources:
            if s.id == sid:
                return s
        return None

    def screen_by_id(self, sid: str) -> Screen | None:
        for s in self.screens:
            if s.id == sid:
                return s
        return None

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> Project:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)


def default_project() -> Project:
    """Projet démo prêt à éditer."""
    src_cpu = DataSource(id="src_cpu", label="CPU %", kind="builtin", builtin_key="cpu", unit="%")
    src_ram = DataSource(id="src_ram", label="RAM %", kind="builtin", builtin_key="ram", unit="%")
    src_disk = DataSource(id="src_disk", label="Disk %", kind="builtin", builtin_key="disk", unit="%")
    src_load = DataSource(
        id="src_load",
        label="Load 1m",
        kind="command",
        command="python3 -c \"import os; print(os.getloadavg()[0])\"",
        parse_mode="float",
        unit="",
        max_value=8.0,
    )

    scr_cpu = Screen(
        id="scr_cpu",
        title="CPU",
        background="#000000",
        elements=[
            Element(id=_nid("el"), type="pattern", x=0, y=0, w=64, h=64, pattern="grid", pattern_color="#12121A", z=0),
            Element(id=_nid("el"), type="text", x=2, y=1, w=60, h=10, text="CPU", color="#3CC8FF", z=1),
            Element(
                id=_nid("el"),
                type="value",
                x=2,
                y=14,
                w=40,
                h=16,
                source_id="src_cpu",
                color="#28DC64",
                font_size=3,
                format="{v:.0f}%",
                z=2,
            ),
            Element(
                id=_nid("el"),
                type="bar",
                x=2,
                y=36,
                w=60,
                h=6,
                source_id="src_cpu",
                color="#28DC64",
                color_warn="#F0C828",
                color_crit="#FF4646",
                z=2,
            ),
            Element(
                id=_nid("el"),
                type="sparkline",
                x=2,
                y=46,
                w=60,
                h=14,
                source_id="src_cpu",
                period="15m",
                color="#3CC8FF",
                show_progress=True,
                z=2,
            ),
        ],
    )

    scr_disk = Screen(
        id="scr_disk",
        title="DISK",
        background="#000000",
        elements=[
            Element(id=_nid("el"), type="text", x=2, y=1, w=60, h=10, text="DISK", color="#3CC8FF", z=1),
            Element(
                id=_nid("el"),
                type="value",
                x=2,
                y=14,
                w=28,
                h=16,
                source_id="src_disk",
                color="#F08C28",
                font_size=3,
                format="{v:.0f}%",
                z=2,
            ),
            Element(
                id=_nid("el"),
                type="pie",
                x=36,
                y=18,
                w=26,
                h=26,
                source_id="src_disk",
                color="#F08C28",
                color_secondary="#282837",
                z=2,
            ),
            Element(
                id=_nid("el"),
                type="status_dot",
                x=2,
                y=52,
                w=8,
                h=8,
                source_id="src_disk",
                warn_at=80,
                crit_at=90,
                z=2,
            ),
            Element(id=_nid("el"), type="text", x=12, y=52, w=48, h=10, text="usage", color="#78788C", z=2),
        ],
    )

    return Project(
        meta=ProjectMeta(name="Demo Pixoo", notes="Projet exemple — éditable dans le Designer"),
        sources=[src_cpu, src_ram, src_disk, src_load],
        screens=[scr_cpu, scr_disk],
        history_preview={
            "src_cpu": [20, 25, 40, 55, 48, 62, 70, 58, 45, 38, 42, 50, 60, 72, 65, 55],
            "src_disk": [60, 61, 61, 62, 63, 63, 64, 64],
        },
    )


def new_element(etype: ElementType, **kwargs: Any) -> Element:
    defaults: dict[str, Any] = {
        "text": {"type": "text", "text": "Label", "h": 10},
        "value": {"type": "value", "format": "{v:.0f}{u}", "font_size": 2, "h": 12},
        "bar": {"type": "bar", "h": 6, "w": 60},
        "pie": {"type": "pie", "w": 24, "h": 24},
        "sparkline": {"type": "sparkline", "h": 16, "w": 60, "period": "15m"},
        "rect": {"type": "rect", "w": 20, "h": 10, "color": "#1E1E2A"},
        "pattern": {"type": "pattern", "x": 0, "y": 0, "w": 64, "h": 64, "pattern": "dots"},
        "status_dot": {"type": "status_dot", "w": 8, "h": 8},
    }
    base = defaults.get(etype, {"type": etype})
    base = {**base, **kwargs}
    return Element(id=_nid("el"), **base)


# validation légère période
_PERIOD_OK = re.compile(r"^\d+(\.\d+)?(s|m|h|j|M|a|d)?$", re.I)


def valid_period(value: str) -> bool:
    return bool(_PERIOD_OK.match((value or "").strip()))
