"""Écrans Pixoo personnalisés — métriques, titre, style pie/barre par mesure."""

from __future__ import annotations

from typing import Any

from .display import normalize_disk_style
from .profiles import METRIC_KEYS, METRIC_LABELS

# Métriques pour lesquelles pie (camembert) vs bar a un sens (% utilisé)
GAUGE_METRIC_KEYS: tuple[str, ...] = (
    "cpu",
    "ram",
    "swap",
    "disk",
    "nc_disk",
    "php_fpm_workers",
)

DEFAULT_SCREEN_TITLES: dict[str, str] = {
    "cpu": "CPU",
    "cpu_per_core": "CORES",
    "load_avg": "LOAD",
    "ram": "RAM",
    "swap": "SWAP",
    "disk": "DISK",
    "network": "NET",
    "temperature": "TEMP",
    "uptime": "UP",
    "processes": "TOP",
    "services": "SVC",
    "php_fpm_workers": "FPM",
    "db_health": "DB",
    "redis": "REDIS",
    "nc_disk": "NC DSK",
    "nc_http": "NC HTTP",
    "nc_cron": "CRON",
    "nc_errors": "ERR",
    "nc_external_storage": "MNT",
    "status_host": "HOST",
    "status_nc_http": "NC",
    "status_services": "SVC",
    "status_disk": "DSK",
    "status_network": "NET",
    "status_thermal": "THM",
    "status_overall": "STATUS",
}


def default_title_for_metrics(metrics: list[str]) -> str:
    """Titre court dérivé des métriques (≤10 car. pour Pixoo)."""
    if not metrics:
        return "SCR"
    if len(metrics) == 1:
        return DEFAULT_SCREEN_TITLES.get(metrics[0], metrics[0][:6].upper())[:10]
    # Compose jusqu'à 3 libellés courts
    parts = [DEFAULT_SCREEN_TITLES.get(m, m[:3].upper())[:4] for m in metrics[:3]]
    joined = "+".join(parts)
    return joined[:10]


def normalize_screen(raw: Any, index: int = 0) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    metrics_raw = raw.get("metrics") or []
    if isinstance(metrics_raw, str):
        metrics_raw = [m.strip() for m in metrics_raw.split(",") if m.strip()]
    if not isinstance(metrics_raw, list):
        return None
    metrics = [str(m).strip() for m in metrics_raw if str(m).strip() in METRIC_KEYS]
    if not metrics:
        return None

    sid = str(raw.get("id") or f"s{index + 1}").strip() or f"s{index + 1}"
    title_raw = raw.get("title")
    use_default = bool(raw.get("title_default", True))
    if title_raw is None or (isinstance(title_raw, str) and not title_raw.strip()):
        title = ""
        use_default = True
    else:
        title = str(title_raw).strip()[:16]
        use_default = False if title else True

    styles_raw = raw.get("styles") if isinstance(raw.get("styles"), dict) else {}
    styles: dict[str, str] = {}
    for m in metrics:
        if m not in GAUGE_METRIC_KEYS:
            continue
        # style dédié, ou clé plate "cpu_style", ou défaut bar
        style_val = styles_raw.get(m)
        if style_val is None:
            style_val = raw.get(f"{m}_style")
        styles[m] = normalize_disk_style(style_val if style_val is not None else "bar")

    return {
        "id": sid,
        "title": title,
        "title_default": use_default,
        "metrics": metrics,
        "styles": styles,
    }


def parse_screens(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Lit [[screens]] ou [screens.N] depuis la config."""
    raw = cfg.get("screens")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            scr = normalize_screen(item, i)
            if scr:
                out.append(scr)
        return out
    if isinstance(raw, dict):
        # Tables nommées [screens.cpu] ou index numérique
        items = sorted(raw.items(), key=lambda kv: str(kv[0]))
        for i, (key, item) in enumerate(items):
            if not isinstance(item, dict):
                continue
            merged = dict(item)
            merged.setdefault("id", str(key))
            scr = normalize_screen(merged, i)
            if scr:
                out.append(scr)
    return out


def resolve_screen_title(screen: dict[str, Any]) -> str:
    if screen.get("title_default", True) or not str(screen.get("title") or "").strip():
        return default_title_for_metrics(list(screen.get("metrics") or []))
    return str(screen["title"]).strip()[:10]


def metric_style(screen: dict[str, Any], metric: str, fallback: str = "bar") -> str:
    styles = screen.get("styles") if isinstance(screen.get("styles"), dict) else {}
    if metric in styles:
        return normalize_disk_style(styles[metric])
    return normalize_disk_style(fallback)


def screens_collect_metrics(screens: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for scr in screens:
        for m in scr.get("metrics") or []:
            keys.add(str(m))
    return keys


def label_metric(key: str) -> str:
    return METRIC_LABELS.get(key, key)
