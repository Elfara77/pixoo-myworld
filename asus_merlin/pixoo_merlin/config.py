"""Configuration via variables d'environnement / fichier .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    pixoo_ip: str
    brightness: int = 40
    screen_seconds: float = 8.0
    frame_interval: float = 1.05
    wan_iface: str = ""
    ping_host: str = "1.1.1.1"
    history_seconds: int = 300
    stats_seconds: int = 3600
    top_clients: int = 5
    marquee_speed: float = 36.0
    sample_interval: float = 2.0
    demo: bool = False
    save_preview: str = ""
    setup_name: str = "default"


def load_config(env_file: str | Path | None = None) -> Config:
    root = Path(__file__).resolve().parent.parent
    candidates = []
    if env_file:
        candidates.append(Path(env_file))
    candidates.extend(
        [
            Path(os.environ.get("PIXOO_MERLIN_ENV", "")),
            root / "config.env",
            root / ".env",
            Path.cwd() / "config.env",
        ]
    )
    for p in candidates:
        if p and str(p):
            _load_dotenv(p)

    ip = (os.environ.get("PIXOO_IP") or os.environ.get("PIXOO_MERLIN_IP") or "").strip()
    demo = _bool("DEMO") or _bool("PIXOO_MERLIN_DEMO")
    if not ip and not demo:
        raise SystemExit(
            "PIXOO_IP manquant. Copie config.example.env → config.env "
            "ou lance avec --demo."
        )

    setup = (
        os.environ.get("SETUP")
        or os.environ.get("PIXOO_MERLIN_SETUP")
        or "default"
    ).strip() or "default"

    return Config(
        pixoo_ip=ip or "127.0.0.1",
        brightness=_int("BRIGHTNESS", 40),
        screen_seconds=_float("SCREEN_SECONDS", 8.0),
        frame_interval=max(1.0, _float("FRAME_INTERVAL", 1.05)),
        wan_iface=(os.environ.get("WAN_IFACE") or "").strip(),
        ping_host=(os.environ.get("PING_HOST") or "1.1.1.1").strip(),
        history_seconds=max(60, _int("HISTORY_SECONDS", 300)),
        stats_seconds=max(60, _int("STATS_SECONDS", 3600)),
        top_clients=max(1, min(8, _int("TOP_CLIENTS", 5))),
        marquee_speed=max(8.0, _float("MARQUEE_SPEED", 36.0)),
        sample_interval=max(1.0, _float("SAMPLE_INTERVAL", 2.0)),
        demo=demo,
        save_preview=(os.environ.get("SAVE_PREVIEW") or "").strip(),
        setup_name=setup,
    )
