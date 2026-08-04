"""Profils de monitoring prédéfinis (Nextcloud + système + N40 + status).

Chaque profil pré-sélectionne des métriques / checks ; le wizard laisse
cocher/décocher chaque item. Au runtime, les profils actifs sont fusionnés
(union des flags à true).
"""

from __future__ import annotations

from typing import Any

# Métriques système génériques
SYSTEM_METRIC_KEYS = (
    "cpu",
    "cpu_per_core",
    "load_avg",
    "ram",
    "swap",
    "disk",
    "network",
    "temperature",
    "uptime",
    "processes",
)

# Checks / métriques Nextcloud & services
NEXTCLOUD_METRIC_KEYS = (
    "services",
    "php_fpm_workers",
    "db_health",
    "redis",
    "nc_disk",
    "nc_http",
    "nc_cron",
    "nc_errors",
    "nc_external_storage",
)

# Checks « status » — vue santé globale (OK/WARN/DOWN)
STATUS_METRIC_KEYS = (
    "status_host",
    "status_nc_http",
    "status_services",
    "status_disk",
    "status_network",
    "status_thermal",
    "status_overall",
)

METRIC_KEYS = SYSTEM_METRIC_KEYS + NEXTCLOUD_METRIC_KEYS + STATUS_METRIC_KEYS

METRIC_LABELS: dict[str, str] = {
    "cpu": "CPU (%)",
    "cpu_per_core": "CPU par cœur",
    "load_avg": "Load average",
    "ram": "RAM",
    "swap": "Swap",
    "disk": "Disque (montage générique)",
    "network": "Réseau (↑↓)",
    "temperature": "Température",
    "uptime": "Uptime",
    "processes": "Top processus",
    "services": "Services systemd (php-fpm, web, DB, redis, cron)",
    "php_fpm_workers": "php-fpm workers busy/max",
    "db_health": "Santé DB (connexions / ping)",
    "redis": "Redis up + mémoire",
    "nc_disk": "Disque / taille data Nextcloud",
    "nc_http": "HTTP /status.php (ou serverinfo)",
    "nc_cron": "Fraîcheur cron / background jobs",
    "nc_errors": "Erreurs 5xx / log (optionnel)",
    "nc_external_storage": "Montages stockage externe (optionnel)",
    "status_host": "Status: hôte / OS (Debian…)",
    "status_nc_http": "Status: Nextcloud HTTP OK/KO",
    "status_services": "Status: résumé services up/down",
    "status_disk": "Status: disque OK vs alerte",
    "status_network": "Status: interface + connectivité",
    "status_thermal": "Status: thermique / load N40",
    "status_overall": "Status: santé globale (vert/jaune/rouge)",
}

PROFILE_LABELS: dict[str, str] = {
    "system": "Système générique (hôte)",
    "priority": "Priorité haute Nextcloud",
    "nextcloud_files": "Spécifique Nextcloud Files",
    "n40": "Matériel Minisforum N40",
    "status": "Status santé (vue d'ensemble OK/KO)",
    "nextcloud_full": "Nextcloud complet (priority + files + N40 + status)",
}

PROFILE_ORDER = (
    "system",
    "priority",
    "nextcloud_files",
    "n40",
    "status",
    "nextcloud_full",
)

# Pré-sélections par profil (True = coché par défaut dans le wizard)
_PROFILE_DEFAULTS: dict[str, dict[str, bool]] = {
    "system": {
        "cpu": True,
        "cpu_per_core": False,
        "load_avg": True,
        "ram": True,
        "swap": True,
        "disk": True,
        "network": True,
        "temperature": True,
        "uptime": False,
        "processes": False,
    },
    "priority": {
        "disk": True,
        "services": True,
        "php_fpm_workers": True,
        "db_health": True,
        "redis": True,
    },
    "nextcloud_files": {
        "nc_disk": True,
        "nc_http": True,
        "nc_cron": True,
        "nc_errors": False,
        "nc_external_storage": False,
    },
    "n40": {
        "cpu": True,
        "ram": True,
        "swap": True,
        "temperature": True,
        "network": True,
        "load_avg": True,
    },
    "status": {
        "status_host": True,
        "status_nc_http": True,
        "status_services": True,
        "status_disk": True,
        "status_network": True,
        "status_thermal": True,
        "status_overall": True,
        # Sous-jacents utiles pour alimenter le strip (peuvent être décochés)
        "services": True,
        "nc_http": True,
        "disk": True,
        "nc_disk": True,
        "network": True,
        "temperature": True,
        "load_avg": True,
    },
    "nextcloud_full": {},  # rempli ci-dessous = union A+B+C+status
}


def _union(*names: str) -> dict[str, bool]:
    out: dict[str, bool] = {k: False for k in METRIC_KEYS}
    for name in names:
        for key, val in _PROFILE_DEFAULTS.get(name, {}).items():
            if val:
                out[key] = True
    return out


_PROFILE_DEFAULTS["nextcloud_full"] = _union(
    "priority", "nextcloud_files", "n40", "status"
)


def profile_defaults(name: str) -> dict[str, bool]:
    """Retourne un dict complet {metric: bool} pour un profil."""
    base = {k: False for k in METRIC_KEYS}
    base.update(_PROFILE_DEFAULTS.get(name, {}))
    return base


def all_profile_defaults() -> dict[str, dict[str, bool]]:
    return {name: profile_defaults(name) for name in PROFILE_ORDER}


def merge_metrics(*metric_dicts: dict[str, Any]) -> dict[str, bool]:
    """Union booléenne des dicts de métriques."""
    out = {k: False for k in METRIC_KEYS}
    for d in metric_dicts:
        for k in METRIC_KEYS:
            if d.get(k):
                out[k] = True
    return out


def resolve_active_metrics(
    cfg: dict[str, Any],
    *,
    profile_override: str | None = None,
) -> dict[str, bool]:
    """Fusionne les métriques des profils actifs (ou d'un override).

    Priorité :
    1. ``--profile X`` (un seul profil)
    2. ``active_profiles = [...]`` + sections ``[profiles.X]``
    3. Fallback legacy ``[metrics]``
    """
    profiles_cfg = cfg.get("profiles") or {}
    if not isinstance(profiles_cfg, dict):
        profiles_cfg = {}

    if profile_override:
        section = profiles_cfg.get(profile_override)
        if isinstance(section, dict) and any(k in METRIC_KEYS for k in section):
            return merge_metrics(section)
        return profile_defaults(profile_override)

    active = cfg.get("active_profiles")
    if isinstance(active, list) and active:
        parts: list[dict[str, Any]] = []
        for name in active:
            section = profiles_cfg.get(str(name))
            if isinstance(section, dict):
                parts.append(section)
            else:
                parts.append(profile_defaults(str(name)))
        if parts:
            return merge_metrics(*parts)

    # Legacy : section [metrics] plate
    legacy = cfg.get("metrics")
    if isinstance(legacy, dict):
        return merge_metrics(legacy)

    # Si des profils existent sans active_profiles, activer ceux marqués enabled
    enabled_parts: list[dict[str, Any]] = []
    for name, section in profiles_cfg.items():
        if isinstance(section, dict) and section.get("enabled", False):
            enabled_parts.append(section)
    if enabled_parts:
        return merge_metrics(*enabled_parts)

    return profile_defaults("system")


def needs_nextcloud_settings(metrics: dict[str, bool]) -> bool:
    nc_keys = NEXTCLOUD_METRIC_KEYS + (
        "status_nc_http",
        "status_services",
        "status_overall",
    )
    return any(metrics.get(k) for k in nc_keys)


DEFAULT_NEXTCLOUD: dict[str, Any] = {
    "data_dir": "/var/www/nextcloud/data",
    "web_root": "/var/www/nextcloud",
    "status_url": "http://127.0.0.1/status.php",
    "occ_path": "/var/www/nextcloud/occ",
    "php_fpm_status_url": "",
    "log_path": "",
    "db_type": "mariadb",
    "external_mounts": [],
    "services": [
        "php8.4-fpm",
        "nginx",
        "mariadb",
        "redis-server",
        "cron",
    ],
}

DEFAULT_STATUS: dict[str, Any] = {
    # Cible ping optionnelle ("" = gateway auto, ou ex. 1.1.1.1)
    "ping_target": "",
    "ping_enabled": True,
}
