"""Declarative named setups (YAML) — screens + widgets."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit(
        "PyYAML required. On Merlin: opkg install python3-yaml\n"
        "On desktop: pip install pyyaml"
    ) from exc

# Widget ids usable in setup files
WIDGETS = (
    "title",
    "clients",
    "wan_rate",
    "cpu",
    "temp",
    "ram",
    "wan_graph",
    "internet",
    "usb",
    "ethernet",
    "wan_ip",
    "uptime",
    "top_clients",
    "hour_stats",
    "disk_pie",
)

DEFAULT_SETUP_NAME = "default"


@dataclass
class ScreenDef:
    id: str
    enabled: bool = True
    seconds: float | None = None
    widgets: list[str] = field(default_factory=list)


@dataclass
class Setup:
    name: str
    title: str = "Asus Merlin"
    # None → fall back to config.env SCREEN_SECONDS at runtime
    screen_seconds: float | None = None
    screens: list[ScreenDef] = field(default_factory=list)
    path: Path | None = None

    def enabled_screens(self) -> list[ScreenDef]:
        return [s for s in self.screens if s.enabled and s.widgets]


def setups_dir(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parent.parent
    return base / "setups"


def _safe_name(name: str) -> str:
    n = (name or "").strip().lower()
    n = re.sub(r"[^a-z0-9_-]+", "_", n)
    if not n or n in (".", ".."):
        raise ValueError(f"Invalid setup name: {name!r}")
    return n


def _normalize_widgets(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [w.strip() for w in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(w).strip() for w in raw]
    else:
        return []
    out: list[str] = []
    aliases = {
        "wan": "wan_rate",
        "bandwidth": "wan_rate",
        "graph": "wan_graph",
        "graphs": "wan_graph",
        "net": "internet",
        "eth": "ethernet",
        "ip": "wan_ip",
        "top": "top_clients",
        "top_dl": "top_clients",
        "stats": "hour_stats",
        "minmax": "hour_stats",
        "disk": "disk_pie",
        "pie": "disk_pie",
    }
    for w in items:
        if not w:
            continue
        key = w.lower().replace("-", "_")
        key = aliases.get(key, key)
        if key not in WIDGETS:
            raise ValueError(f"Unknown widget {w!r}. Valid: {', '.join(WIDGETS)}")
        if key not in out:
            out.append(key)
    return out


def _parse_screen(raw: dict[str, Any], idx: int) -> ScreenDef:
    sid = str(raw.get("id") or f"screen{idx + 1}").strip()
    enabled = bool(raw.get("enabled", True))
    seconds = raw.get("seconds")
    sec = float(seconds) if seconds is not None else None
    widgets = _normalize_widgets(raw.get("widgets") or raw.get("elements") or [])
    return ScreenDef(id=sid, enabled=enabled, seconds=sec, widgets=widgets)


def load_setup(name: str, root: Path | None = None) -> Setup:
    name = _safe_name(name)
    path = setups_dir(root) / f"{name}.yaml"
    if not path.is_file():
        # legacy .yml
        alt = setups_dir(root) / f"{name}.yml"
        if alt.is_file():
            path = alt
        else:
            raise FileNotFoundError(f"Setup not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be a mapping")
    meta = data.get("setup") or {}
    if not isinstance(meta, dict):
        meta = {}
    screens_raw = data.get("screens") or []
    if not isinstance(screens_raw, list):
        raise ValueError(f"{path}: screens must be a list")
    screens = [
        _parse_screen(s if isinstance(s, dict) else {}, i) for i, s in enumerate(screens_raw)
    ]
    raw_ss = meta.get("screen_seconds", data.get("screen_seconds"))
    screen_seconds: float | None
    if raw_ss is None or raw_ss == "":
        screen_seconds = None
    else:
        screen_seconds = float(raw_ss)
    return Setup(
        name=name,
        title=str(meta.get("title") or data.get("title") or "Asus Merlin"),
        screen_seconds=screen_seconds,
        screens=screens,
        path=path,
    )


def list_setups(root: Path | None = None) -> list[str]:
    d = setups_dir(root)
    if not d.is_dir():
        return []
    names = {p.stem for p in d.glob("*.yaml")} | {p.stem for p in d.glob("*.yml")}
    return sorted(names)


def write_setup(setup: Setup, root: Path | None = None) -> Path:
    name = _safe_name(setup.name)
    d = setups_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.yaml"
    payload = {
        "setup": {
            "title": setup.title,
            **(
                {"screen_seconds": float(setup.screen_seconds)}
                if setup.screen_seconds is not None
                else {}
            ),
        },
        "screens": [
            {
                "id": sc.id,
                "enabled": bool(sc.enabled),
                **({"seconds": float(sc.seconds)} if sc.seconds is not None else {}),
                "widgets": list(sc.widgets),
            }
            for sc in setup.screens
        ],
    }
    path.write_text(
        yaml.safe_dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    setup.path = path
    return path


def copy_setup(src: str, dst: str, root: Path | None = None) -> Path:
    src_n, dst_n = _safe_name(src), _safe_name(dst)
    if src_n == dst_n:
        raise ValueError("Source and destination setup names must differ")
    setup = load_setup(src_n, root)
    setup.name = dst_n
    dst_path = setups_dir(root) / f"{dst_n}.yaml"
    if dst_path.exists():
        raise FileExistsError(f"Setup already exists: {dst_path}")
    return write_setup(setup, root)


def set_screen_enabled(name: str, screen_id: str, enabled: bool, root: Path | None = None) -> Setup:
    setup = load_setup(name, root)
    found = False
    for sc in setup.screens:
        if sc.id == screen_id or sc.id.lower() == screen_id.lower():
            sc.enabled = enabled
            found = True
            break
    if not found and screen_id.isdigit():
        idx = int(screen_id) - 1
        if 0 <= idx < len(setup.screens):
            setup.screens[idx].enabled = enabled
            found = True
    if not found:
        ids = ", ".join(s.id for s in setup.screens)
        raise KeyError(f"Screen {screen_id!r} not in setup {name!r} ({ids})")
    write_setup(setup, root)
    return setup


def set_widget_enabled(
    name: str,
    screen_id: str,
    widget: str,
    enabled: bool,
    root: Path | None = None,
) -> Setup:
    setup = load_setup(name, root)
    wlist = _normalize_widgets([widget])
    if not wlist:
        raise ValueError(f"Invalid widget: {widget}")
    wid = wlist[0]
    target: ScreenDef | None = None
    for sc in setup.screens:
        if sc.id == screen_id or sc.id.lower() == screen_id.lower():
            target = sc
            break
    if target is None and screen_id.isdigit():
        idx = int(screen_id) - 1
        if 0 <= idx < len(setup.screens):
            target = setup.screens[idx]
    if target is None:
        raise KeyError(f"Screen {screen_id!r} not found")
    if enabled:
        if wid not in target.widgets:
            target.widgets.append(wid)
    else:
        target.widgets = [w for w in target.widgets if w != wid]
    write_setup(setup, root)
    return setup


def set_screen_seconds(
    name: str,
    screen_id: str,
    seconds: float | None,
    root: Path | None = None,
) -> Setup:
    """Set per-screen duration (None clears override → use setup/config default)."""
    setup = load_setup(name, root)
    found = False
    for sc in setup.screens:
        if sc.id == screen_id or sc.id.lower() == screen_id.lower():
            sc.seconds = float(seconds) if seconds is not None else None
            if sc.seconds is not None and sc.seconds < 1.0:
                sc.seconds = 1.0
            found = True
            break
    if not found and screen_id.isdigit():
        idx = int(screen_id) - 1
        if 0 <= idx < len(setup.screens):
            sc = setup.screens[idx]
            sc.seconds = float(seconds) if seconds is not None else None
            if sc.seconds is not None and sc.seconds < 1.0:
                sc.seconds = 1.0
            found = True
    if not found:
        ids = ", ".join(s.id for s in setup.screens)
        raise KeyError(f"Screen {screen_id!r} not in setup {name!r} ({ids})")
    write_setup(setup, root)
    return setup


def ensure_default_setup(root: Path | None = None) -> Path:
    """Write default.yaml if missing (full multi-screen layout)."""
    path = setups_dir(root) / f"{DEFAULT_SETUP_NAME}.yaml"
    if path.is_file():
        return path
    setup = Setup(
        name=DEFAULT_SETUP_NAME,
        title="Asus Merlin",
        screen_seconds=8.0,
        screens=[
            ScreenDef(id="overview", enabled=True, widgets=["title", "clients", "ram", "cpu", "temp"]),
            ScreenDef(id="bandwidth", enabled=True, seconds=12.0, widgets=["wan_graph"]),
            ScreenDef(id="status", enabled=True, seconds=10.0, widgets=["title", "internet", "wan_ip", "usb", "ethernet"]),
            ScreenDef(id="top_dl", enabled=True, widgets=["title", "top_clients"]),
            ScreenDef(id="hour_stats", enabled=True, widgets=["hour_stats"]),
            ScreenDef(id="disk", enabled=True, widgets=["disk_pie"]),
        ],
    )
    return write_setup(setup, root)
