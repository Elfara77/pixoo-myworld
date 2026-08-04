from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from .profiles import (
    DEFAULT_NEXTCLOUD,
    DEFAULT_STATUS,
    METRIC_KEYS,
    PROFILE_ORDER,
    merge_metrics,
    profile_defaults,
    resolve_active_metrics,
)

DEFAULT_CONFIG_NAMES = ("config.toml", "config.example.toml")

# Réexport pour compatibilité
__all__ = [
    "METRIC_KEYS",
    "DEFAULT_CONFIG_NAMES",
    "project_root",
    "find_config_path",
    "load_config",
    "enabled_metrics",
    "write_config",
    "resolve_active_metrics",
    "merge_metrics",
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Config introuvable: {path}")
        return path

    root = project_root()
    for name in DEFAULT_CONFIG_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Aucune config trouvée. Lance ./scripts/setup.sh ou copie config.example.toml → config.toml"
    )


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = find_config_path(path)
    with cfg_path.open("rb") as fh:
        data = tomllib.load(fh)
    data["_config_path"] = str(cfg_path)
    # Normalise metrics fusionnées pour le runtime
    data["_resolved_metrics"] = resolve_active_metrics(data)
    return data


def apply_profile_override(cfg: dict[str, Any], profile: str | None) -> dict[str, Any]:
    """Retourne une copie logique avec métriques résolues pour un profil."""
    if not profile:
        return cfg
    resolved = resolve_active_metrics(cfg, profile_override=profile)
    out = dict(cfg)
    out["_resolved_metrics"] = resolved
    out["_profile_override"] = profile
    return out


def enabled_metrics(cfg: dict[str, Any]) -> list[str]:
    metrics = cfg.get("_resolved_metrics")
    if not isinstance(metrics, dict):
        metrics = resolve_active_metrics(cfg)
    return [name for name in METRIC_KEYS if bool(metrics.get(name, False))]


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_bool(value: Any) -> str:
    return "true" if value else "false"


def _toml_list_str(values: list[Any]) -> str:
    parts = [_toml_str(str(v)) for v in values]
    return "[" + ", ".join(parts) + "]"


def write_config(path: Path, data: dict[str, Any]) -> None:
    """Écrit un config.toml (profils + nextcloud) sans dépendance toml write."""
    lines: list[str] = [
        "# Généré par pixoo_monitor.setup — éditable à la main",
        "# Re-lancer ./scripts/setup.sh ajoute / met à jour des profils sans tout effacer.",
        "",
    ]

    active = data.get("active_profiles") or []
    if not isinstance(active, list):
        active = []
    # Clés racine AVANT toute table TOML
    lines.append(f"active_profiles = {_toml_list_str([str(a) for a in active])}")
    setup_name = str(data.get("setup_name") or "").strip()
    if setup_name:
        lines.append(f"setup_name = {_toml_str(setup_name)}")
    lines.append("")

    lines += [
        "[pixoo]",
        f'ip = {_toml_str(str(data["pixoo"]["ip"]))}',
        f'size = {int(data["pixoo"].get("size", 64))}',
        f'brightness = {int(data["pixoo"].get("brightness", 60))}',
        "",
        "[refresh]",
        f'interval_seconds = {float(data["refresh"].get("interval_seconds", 3.0))}',
        f'page_seconds = {float(data["refresh"].get("page_seconds", 8.0))}',
        "",
    ]
    # Legacy flat [metrics] = union des actifs (pratique pour lecture rapide)
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        metrics = resolve_active_metrics(data)
    lines.append("[metrics]")
    for key in METRIC_KEYS:
        lines.append(f"{key} = {_toml_bool(metrics.get(key))}")
    lines.append("")

    disk = data.get("disk", {})
    net = data.get("network", {})
    lines += [
        "[disk]",
        f'path = {_toml_str(str(disk.get("path", "")))}',
        "",
        "[network]",
        f'interface = {_toml_str(str(net.get("interface", "")))}',
        "",
        "[thresholds]",
    ]
    thr = data.get("thresholds", {})
    for key, default in (
        ("cpu_percent", 90),
        ("ram_percent", 90),
        ("swap_percent", 80),
        ("disk_percent", 90),
        ("temperature_celsius", 85),
        ("nc_disk_percent", 90),
    ):
        lines.append(f"{key} = {int(thr.get(key, default))}")

    disp = data.get("display", {})
    render_mode = str(disp.get("render_mode", "scaled")).strip().lower()
    if render_mode not in ("native", "scaled"):
        render_mode = "scaled"
    disk_style = str(disp.get("disk_style", "bar")).strip().lower()
    if disp.get("disk_pie") and disk_style == "bar":
        disk_style = "pie"
    if disk_style not in ("bar", "pie"):
        disk_style = "bar"
    lines += [
        "",
        "[display]",
        f'overview = {_toml_bool(disp.get("overview", True))}',
        f'bars = {_toml_bool(disp.get("bars", True))}',
        f'dark = {_toml_bool(disp.get("dark", True))}',
        f'n40_thermal = {_toml_bool(disp.get("n40_thermal", False))}',
        f'render_mode = {_toml_str(render_mode)}',
        f'disk_style = {_toml_str(disk_style)}',
        "",
    ]

    # Styles pie/barre par mesure (si pas d'écrans custom)
    metric_styles = data.get("metric_styles") or {}
    if isinstance(metric_styles, dict) and metric_styles:
        lines.append("[metric_styles]")
        for key in ("cpu", "ram", "swap", "disk", "nc_disk", "php_fpm_workers"):
            if key in metric_styles:
                style = str(metric_styles[key]).strip().lower()
                if style not in ("bar", "pie"):
                    style = "bar"
                lines.append(f"{key} = {_toml_str(style)}")
        lines.append("")

    # Écrans personnalisés [[screens]]
    screens = data.get("screens") or []
    if isinstance(screens, list):
        for i, scr in enumerate(screens):
            if not isinstance(scr, dict):
                continue
            metrics_list = scr.get("metrics") or []
            if not isinstance(metrics_list, list) or not metrics_list:
                continue
            sid = str(scr.get("id") or f"s{i + 1}")
            title = str(scr.get("title") or "")
            title_default = bool(scr.get("title_default", not bool(title.strip())))
            styles = scr.get("styles") if isinstance(scr.get("styles"), dict) else {}
            # Inline styles table
            style_parts = []
            for mk, mv in styles.items():
                st = str(mv).strip().lower()
                if st not in ("bar", "pie"):
                    st = "bar"
                style_parts.append(f"{mk} = {_toml_str(st)}")
            styles_inline = "{ " + ", ".join(style_parts) + " }" if style_parts else "{}"
            lines += [
                "[[screens]]",
                f'id = {_toml_str(sid)}',
                f'title = {_toml_str(title)}',
                f"title_default = {_toml_bool(title_default)}",
                f"metrics = {_toml_list_str([str(m) for m in metrics_list])}",
                f"styles = {styles_inline}",
                "",
            ]

    nc = data.get("nextcloud") or {}
    if not isinstance(nc, dict):
        nc = {}
    merged_nc = {**DEFAULT_NEXTCLOUD, **nc}
    services = merged_nc.get("services") or DEFAULT_NEXTCLOUD["services"]
    mounts = merged_nc.get("external_mounts") or []
    if not isinstance(services, list):
        services = list(DEFAULT_NEXTCLOUD["services"])
    if not isinstance(mounts, list):
        mounts = []

    lines += [
        "[nextcloud]",
        f'data_dir = {_toml_str(str(merged_nc.get("data_dir", "")))}',
        f'web_root = {_toml_str(str(merged_nc.get("web_root", "")))}',
        f'status_url = {_toml_str(str(merged_nc.get("status_url", "")))}',
        f'occ_path = {_toml_str(str(merged_nc.get("occ_path", "")))}',
        f'php_fpm_status_url = {_toml_str(str(merged_nc.get("php_fpm_status_url", "")))}',
        f'log_path = {_toml_str(str(merged_nc.get("log_path", "")))}',
        f'db_type = {_toml_str(str(merged_nc.get("db_type", "mariadb")))}',
        f"services = {_toml_list_str([str(s) for s in services])}",
        f"external_mounts = {_toml_list_str([str(m) for m in mounts])}",
        "",
    ]

    st = data.get("status") or {}
    if not isinstance(st, dict):
        st = {}
    merged_st = {**DEFAULT_STATUS, **st}
    lines += [
        "[status]",
        f'ping_enabled = {_toml_bool(merged_st.get("ping_enabled", True))}',
        f'ping_target = {_toml_str(str(merged_st.get("ping_target", "")))}',
        "",
    ]

    # Historique / sparklines
    hist = data.get("history") or {}
    if not isinstance(hist, dict):
        hist = {}
    default_period = str(hist.get("default_period", "15m"))
    buckets = int(hist.get("buckets", 56))
    lines += [
        "[history]",
        f'default_period = {_toml_str(default_period)}',
        f"buckets = {buckets}",
        "",
    ]
    metrics_h = hist.get("metrics") or {}
    if not isinstance(metrics_h, dict):
        metrics_h = {}
    # Aussi fusionner clés à plat historiques
    from .history import HISTORY_METRIC_KEYS

    for key in HISTORY_METRIC_KEYS:
        section = metrics_h.get(key)
        if section is None and isinstance(hist.get(key), dict):
            section = hist[key]
        if not isinstance(section, dict):
            continue
        lines.append(f"[history.metrics.{key}]")
        lines.append(f'enabled = {_toml_bool(section.get("enabled", False))}')
        lines.append(f'period = {_toml_str(str(section.get("period", default_period)))}')
        if "buckets" in section:
            lines.append(f'buckets = {int(section["buckets"])}')
        lines.append("")

    profiles = data.get("profiles") or {}
    if not isinstance(profiles, dict):
        profiles = {}

    # Toujours écrire les profils connus + ceux présents
    names = list(PROFILE_ORDER)
    for name in profiles:
        if name not in names:
            names.append(str(name))

    for name in names:
        section = profiles.get(name)
        if not isinstance(section, dict):
            # Ne créer une section que si le profil est actif ou déjà présent
            if name not in active and name not in profiles:
                continue
            section = profile_defaults(name)
        lines.append(f"[profiles.{name}]")
        # Garder enabled si présent
        if "enabled" in section:
            lines.append(f"enabled = {_toml_bool(section.get('enabled'))}")
        defaults = profile_defaults(name) if name in PROFILE_ORDER else {k: False for k in METRIC_KEYS}
        for key in METRIC_KEYS:
            val = section[key] if key in section else defaults.get(key, False)
            lines.append(f"{key} = {_toml_bool(val)}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
