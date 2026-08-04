"""Wizard multi-profils + setups nommés + options d'affichage / historique."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import questionary
from rich.console import Console

from .config import load_config, project_root, write_config
from .display import normalize_disk_style, normalize_render_mode
from .history import (
    HISTORY_METRIC_KEYS,
    HISTORY_METRIC_LABELS,
    parse_period,
)
from .profiles import (
    DEFAULT_NEXTCLOUD,
    DEFAULT_STATUS,
    METRIC_KEYS,
    METRIC_LABELS,
    PROFILE_LABELS,
    PROFILE_ORDER,
    needs_nextcloud_settings,
    profile_defaults,
    resolve_active_metrics,
)
from .screens import (
    GAUGE_METRIC_KEYS,
    default_title_for_metrics,
    label_metric,
    parse_screens,
)
from .setups import (
    apply_setup_to_active,
    delete_setup,
    list_setups,
    save_setup,
    sanitize_setup_name,
)


def _defaults_from_example() -> dict[str, Any]:
    example = project_root() / "config.example.toml"
    if example.is_file():
        return load_config(example)
    return {
        "pixoo": {"ip": "192.168.1.137", "size": 64, "brightness": 60},
        "refresh": {"interval_seconds": 3.0, "page_seconds": 8.0},
        "active_profiles": ["system"],
        "metrics": {k: False for k in METRIC_KEYS},
        "disk": {"path": ""},
        "network": {"interface": ""},
        "thresholds": {
            "cpu_percent": 90,
            "ram_percent": 90,
            "swap_percent": 80,
            "disk_percent": 90,
            "temperature_celsius": 85,
            "nc_disk_percent": 90,
        },
        "display": {
            "overview": True,
            "bars": True,
            "dark": True,
            "n40_thermal": False,
            "render_mode": "scaled",
            "disk_style": "bar",
        },
        "history": {"default_period": "15m", "buckets": 56, "metrics": {}},
        "nextcloud": dict(DEFAULT_NEXTCLOUD),
        "status": dict(DEFAULT_STATUS),
        "profiles": {},
        "setup_name": "",
    }


def _ask_cancel(value: Any, console: Console) -> bool:
    if value is None:
        console.print("[yellow]Annulé[/yellow]")
        return True
    return False


def _ask_period(console: Console, prompt: str, default: str) -> str | None:
    """Preset ou durée libre avec unité s|m|h|j|M|a."""
    choice = questionary.select(
        prompt,
        choices=[
            questionary.Choice("30 secondes", "30s"),
            questionary.Choice("5 minutes", "5m"),
            questionary.Choice("15 minutes", "15m"),
            questionary.Choice("1 heure", "1h"),
            questionary.Choice("24 heures", "24h"),
            questionary.Choice("7 jours", "7j"),
            questionary.Choice("Autre durée… (s/m/h/j/M/a)", "custom"),
        ],
        default=default if default in ("30s", "5m", "15m", "1h", "24h", "7j") else "custom",
    ).ask()
    if choice is None:
        return None
    if choice != "custom":
        return choice

    console.print(
        "[dim]Unités: s=secondes, m=minutes, h=heures, j=jours, M=mois, a=années\n"
        "Ex. 45s, 30m, 2h, 3j, 1M, 1a — nombre seul = minutes[/dim]"
    )
    amount = questionary.text(
        "Valeur numérique",
        default="30",
        validate=lambda s: bool(re.match(r"^\d+(\.\d+)?$", s.strip())) or "Nombre requis",
    ).ask()
    if amount is None:
        return None
    unit = questionary.select(
        "Unité",
        choices=[
            questionary.Choice("s — secondes", "s"),
            questionary.Choice("m — minutes", "m"),
            questionary.Choice("h — heures", "h"),
            questionary.Choice("j — jours", "j"),
            questionary.Choice("M — mois (~30j)", "M"),
            questionary.Choice("a — années (~365j)", "a"),
        ],
        default="m",
    ).ask()
    if unit is None:
        return None
    raw = f"{amount.strip()}{unit}"
    try:
        label, secs = parse_period(raw)
        console.print(f"[dim]→ période normalisée: {label} ({secs}s)[/dim]")
        return label
    except Exception:
        console.print("[red]Durée invalide, repli sur 15m[/red]")
        return "15m"


def _configure_shared(console: Console, base: dict[str, Any]) -> dict[str, Any] | None:
    console.print("\n[bold]Paramètres partagés[/bold] (Pixoo / refresh / affichage)")
    disp = base.get("display") if isinstance(base.get("display"), dict) else {}

    ip = questionary.text(
        "IP du Pixoo 64 (app Divoom → Device)",
        default=str(base.get("pixoo", {}).get("ip", "192.168.1.137")),
    ).ask()
    if _ask_cancel(ip, console):
        return None

    brightness = questionary.text(
        "Luminosité (0–100)",
        default=str(base.get("pixoo", {}).get("brightness", 60)),
        validate=lambda s: s.isdigit() and 0 <= int(s) <= 100,
    ).ask()
    if _ask_cancel(brightness, console):
        return None

    interval = questionary.text(
        "Intervalle refresh (s)",
        default=str(base.get("refresh", {}).get("interval_seconds", 3.0)),
    ).ask()
    if _ask_cancel(interval, console):
        return None

    page_seconds = questionary.text(
        "Durée par page (s)",
        default=str(base.get("refresh", {}).get("page_seconds", 8.0)),
    ).ask()
    if _ask_cancel(page_seconds, console):
        return None

    overview = questionary.confirm(
        "Afficher une page overview compacte ?",
        default=bool(disp.get("overview", True)),
    ).ask()
    if overview is None:
        return None

    console.print(
        "\n[bold]Qualité de rendu[/bold]\n"
        "[dim]native = pixels nets 64×64 (police bitmap, pas de flou)\n"
        "scaled = canvas plus grand puis réduction (aspect plus doux)[/dim]"
    )
    cur_mode = normalize_render_mode(disp.get("render_mode", "scaled"))
    render_mode = questionary.select(
        "Mode de rendu Pixoo",
        choices=[
            questionary.Choice("native — net / pixel-art (recommandé)", "native"),
            questionary.Choice("scaled — doux (comportement hi-res + resize)", "scaled"),
        ],
        default=cur_mode,
    ).ask()
    if render_mode is None:
        return None

    return {
        "ip": ip.strip(),
        "brightness": int(brightness),
        "interval": float(interval),
        "page_seconds": float(page_seconds),
        "overview": bool(overview),
        "render_mode": render_mode,
        # disk_style legacy défaut ; styles fins = écrans / metric_styles
        "disk_style": normalize_disk_style(disp.get("disk_style", "bar")),
    }


def _ask_gauge_style(metric: str, default: str = "bar") -> str | None:
    """Pie (camembert) vs barre pour une mesure %."""
    cur = normalize_disk_style(default)
    choice = questionary.select(
        f"Style jauge — {label_metric(metric)}",
        choices=[
            questionary.Choice("barre — jauge horizontale", "bar"),
            questionary.Choice("camembert (pie) — % utilisé vs libre", "pie"),
        ],
        default=cur if cur in ("bar", "pie") else "bar",
    ).ask()
    return choice


def _configure_screens(
    console: Console,
    base: dict[str, Any],
    flat_metrics: dict[str, bool],
) -> tuple[list[dict[str, Any]], dict[str, str]] | None:
    """
    Organise les métriques en écrans (pages Pixoo).
    Retourne (screens, metric_styles_fallback).
    """
    enabled = [k for k in METRIC_KEYS if flat_metrics.get(k)]
    if not enabled:
        return [], {}

    existing = parse_screens(base)
    console.print(
        "\n[bold]Écrans Pixoo[/bold]\n"
        "[dim]Chaque écran = une page 64×64. Cocher les métriques par écran,\n"
        "titre par défaut ou perso, style pie/barre pour chaque jauge %.\n"
        "Tu peux ajouter autant d'écrans que nécessaire.[/dim]"
    )

    use_custom = questionary.confirm(
        "Organiser les métriques en écrans personnalisés ?",
        default=bool(existing),
    ).ask()
    if use_custom is None:
        return None
    if not use_custom:
        # Styles globaux par mesure (sans découpage d'écrans)
        styles = _configure_metric_styles(console, enabled, base)
        if styles is None:
            return None
        return [], styles

    remaining = list(enabled)
    screens: list[dict[str, Any]] = []
    idx = 0
    prev_by_id = {str(s.get("id")): s for s in existing}

    while remaining:
        idx += 1
        console.print(f"\n[bold cyan]Écran {idx}[/bold cyan] — restantes: {', '.join(remaining[:8])}"
                      + ("…" if len(remaining) > 8 else ""))

        # Précocher depuis setup existant si même id
        prev = prev_by_id.get(f"s{idx}") or (existing[idx - 1] if idx - 1 < len(existing) else None)
        prev_metrics = set(prev.get("metrics") or []) if isinstance(prev, dict) else set()

        choices = [
            questionary.Choice(
                title=label_metric(k),
                value=k,
                checked=(k in prev_metrics) if prev_metrics else (idx == 1),
            )
            for k in remaining
        ]
        selected = questionary.checkbox(
            f"Métriques pour l'écran {idx} (espace = cocher)",
            choices=choices,
        ).ask()
        if selected is None:
            return None
        if not selected:
            console.print("[yellow]Aucune métrique — fin des écrans[/yellow]")
            break

        default_title = default_title_for_metrics(selected)
        title_mode = questionary.select(
            f"Titre de l'écran {idx}",
            choices=[
                questionary.Choice(f"Par défaut (« {default_title} »)", "default"),
                questionary.Choice("Titre personnalisé…", "custom"),
            ],
            default="default",
        ).ask()
        if title_mode is None:
            return None
        title = ""
        title_default = True
        if title_mode == "custom":
            title = questionary.text(
                "Titre (max 10 car. sur Pixoo)",
                default=str((prev or {}).get("title") or default_title)[:10],
            ).ask()
            if title is None:
                return None
            title = title.strip()[:16]
            title_default = False

        styles: dict[str, str] = {}
        prev_styles = (prev or {}).get("styles") if isinstance(prev, dict) else {}
        if not isinstance(prev_styles, dict):
            prev_styles = {}
        for m in selected:
            if m not in GAUGE_METRIC_KEYS:
                continue
            st = _ask_gauge_style(m, str(prev_styles.get(m, "bar")))
            if st is None:
                return None
            styles[m] = st

        screens.append({
            "id": f"s{idx}",
            "title": title,
            "title_default": title_default,
            "metrics": list(selected),
            "styles": styles,
        })
        for m in selected:
            if m in remaining:
                remaining.remove(m)

        if not remaining:
            break
        more = questionary.confirm(
            "Ajouter un écran supplémentaire pour les métriques restantes ?",
            default=True,
        ).ask()
        if more is None:
            return None
        if not more:
            # Dump remaining into one last auto screen
            if remaining:
                idx += 1
                styles2: dict[str, str] = {}
                for m in remaining:
                    if m in GAUGE_METRIC_KEYS:
                        styles2[m] = "bar"
                screens.append({
                    "id": f"s{idx}",
                    "title": "",
                    "title_default": True,
                    "metrics": list(remaining),
                    "styles": styles2,
                })
                remaining = []
            break

    return screens, {}


def _configure_metric_styles(
    console: Console,
    enabled: list[str],
    base: dict[str, Any],
) -> dict[str, str] | None:
    """Sans écrans custom : style pie/barre par mesure jauge."""
    gauges = [k for k in enabled if k in GAUGE_METRIC_KEYS]
    if not gauges:
        return {}
    console.print(
        "\n[bold]Styles de jauge (par mesure)[/bold]\n"
        "[dim]Camembert (pie) = % utilisé vs libre ; barre = jauge horizontale.[/dim]"
    )
    want = questionary.confirm(
        "Choisir pie/barre pour chaque mesure % ?",
        default=True,
    ).ask()
    if want is None:
        return None
    if not want:
        # legacy: une question disque seulement
        existing = base.get("metric_styles") if isinstance(base.get("metric_styles"), dict) else {}
        disk_default = normalize_disk_style(
            existing.get("disk")
            or (base.get("display") or {}).get("disk_style", "bar")
        )
        if "disk" in gauges or "nc_disk" in gauges:
            pie = questionary.confirm(
                "Disque en camembert (pie) plutôt qu'en barre ?",
                default=(disk_default == "pie"),
            ).ask()
            if pie is None:
                return None
            out = dict(existing)
            if "disk" in gauges:
                out["disk"] = "pie" if pie else "bar"
            if "nc_disk" in gauges:
                out["nc_disk"] = "pie" if pie else "bar"
            return {k: normalize_disk_style(v) for k, v in out.items()}
        return {k: normalize_disk_style(v) for k, v in existing.items()}

    existing = base.get("metric_styles") if isinstance(base.get("metric_styles"), dict) else {}
    out: dict[str, str] = {}
    for m in gauges:
        st = _ask_gauge_style(m, str(existing.get(m, "bar")))
        if st is None:
            return None
        out[m] = st
    return out


def _configure_history(console: Console, base: dict[str, Any], flat_metrics: dict[str, bool]) -> dict[str, Any] | None:
    console.print(
        "\n[bold]Historique / sparklines[/bold]\n"
        "[dim]Une page graphe par métrique cochée. Durée totale = s/m/h/j/M/a "
        "(ex. 45s, 30m, 2h, 7j, 1M). Colonnes ≈ largeur Pixoo.[/dim]"
    )
    hist = base.get("history") if isinstance(base.get("history"), dict) else {}
    metrics_h = hist.get("metrics") if isinstance(hist.get("metrics"), dict) else {}

    want = questionary.confirm(
        "Configurer des graphes d'historique ?",
        default=bool(metrics_h),
    ).ask()
    if want is None:
        return None
    if not want:
        # conserver existant
        return dict(hist) if hist else {"default_period": "15m", "buckets": 56, "metrics": {}}

    default_period = str(hist.get("default_period", "15m"))
    default_period = _ask_period(console, "Période par défaut", default_period)
    if default_period is None:
        return None

    # Candidats: métriques history liées aux flags actifs (+ toujours proposés de base)
    candidates: list[str] = []
    mapping = {
        "cpu": "cpu",
        "ram": "ram",
        "swap": "swap",
        "disk": "disk",
        "network": "network",
        "temperature": "temperature",
        "load_avg": "load_avg",
        "nc_disk": "nc_disk",
        "php_fpm_workers": "php_fpm_workers",
    }
    for mk, hk in mapping.items():
        if flat_metrics.get(mk) or (isinstance(metrics_h.get(hk), dict) and metrics_h[hk].get("enabled")):
            if hk not in candidates:
                candidates.append(hk)
    if flat_metrics.get("network") and "net_up" not in candidates:
        # proposer aussi net_up si réseau actif
        pass
    for k in HISTORY_METRIC_KEYS:
        if k not in candidates and isinstance(metrics_h.get(k), dict) and metrics_h[k].get("enabled"):
            candidates.append(k)
    if not candidates:
        candidates = ["cpu", "ram", "disk"]

    choices = []
    for k in candidates:
        prev = metrics_h.get(k) if isinstance(metrics_h.get(k), dict) else {}
        choices.append(
            questionary.Choice(
                title=HISTORY_METRIC_LABELS.get(k, k),
                value=k,
                checked=bool(prev.get("enabled", False)),
            )
        )
    # option net_up
    if "network" in candidates and "net_up" not in [c.value for c in choices]:
        prev = metrics_h.get("net_up") if isinstance(metrics_h.get("net_up"), dict) else {}
        choices.append(
            questionary.Choice(
                title=HISTORY_METRIC_LABELS["net_up"],
                value="net_up",
                checked=bool(prev.get("enabled", False)),
            )
        )

    selected = questionary.checkbox(
        "Métriques avec page graphe historique",
        choices=choices,
    ).ask()
    if selected is None:
        return None

    new_metrics: dict[str, Any] = {}
    for k in selected:
        prev = metrics_h.get(k) if isinstance(metrics_h.get(k), dict) else {}
        per = str(prev.get("period", default_period))
        per = _ask_period(console, f"Période pour {HISTORY_METRIC_LABELS.get(k, k)}", per)
        if per is None:
            return None
        new_metrics[k] = {"enabled": True, "period": per}

    return {
        "default_period": default_period,
        "buckets": int(hist.get("buckets", 56)),
        "metrics": new_metrics,
    }


def _pick_profiles(console: Console, base: dict[str, Any]) -> list[str] | None:
    console.print(
        "\n[bold]Profils à configurer[/bold] "
        "(plusieurs setups de suite — espace = cocher)"
    )
    current_active = base.get("active_profiles") or []
    if not isinstance(current_active, list):
        current_active = []
    existing_profiles = base.get("profiles") or {}
    if not isinstance(existing_profiles, dict):
        existing_profiles = {}

    choices = []
    for name in PROFILE_ORDER:
        label = PROFILE_LABELS.get(name, name)
        already = name in existing_profiles or name in current_active
        title = f"{label} [{name}]" + (" (déjà en config)" if already else "")
        checked = name in current_active or (not current_active and name == "system")
        choices.append(questionary.Choice(title=title, value=name, checked=checked))

    selected = questionary.checkbox("Profils à (re)configurer / activer", choices=choices).ask()
    if selected is None:
        console.print("[yellow]Annulé[/yellow]")
        return None
    if not selected:
        console.print("[red]Sélectionne au moins un profil[/red]")
        return None
    return list(selected)


def _toggle_metrics_for_profile(
    console: Console,
    profile: str,
    existing_section: dict[str, Any] | None,
) -> dict[str, bool] | None:
    defaults = profile_defaults(profile)
    if isinstance(existing_section, dict):
        for k in METRIC_KEYS:
            if k in existing_section:
                defaults[k] = bool(existing_section[k])

    label = PROFILE_LABELS.get(profile, profile)
    console.print(f"\n[bold cyan]Profil:[/bold cyan] {label} ([bold]{profile}[/bold])")

    relevant = [k for k in METRIC_KEYS if defaults.get(k) or k in (existing_section or {})]
    if profile == "system":
        relevant = list(METRIC_KEYS[:10])
    elif profile == "nextcloud_full":
        relevant = [k for k in METRIC_KEYS if defaults.get(k)]
    elif profile == "status":
        from .profiles import STATUS_METRIC_KEYS

        relevant = list(STATUS_METRIC_KEYS) + [
            "services", "nc_http", "disk", "nc_disk", "network", "temperature", "load_avg",
        ]
        seen: set[str] = set()
        deduped: list[str] = []
        for k in relevant:
            if k in METRIC_KEYS and k not in seen:
                seen.add(k)
                deduped.append(k)
        relevant = deduped
    else:
        relevant = [k for k in METRIC_KEYS if profile_defaults(profile).get(k)]

    if not relevant:
        relevant = list(METRIC_KEYS)

    choices = [
        questionary.Choice(title=METRIC_LABELS.get(k, k), value=k, checked=bool(defaults.get(k)))
        for k in relevant
    ]
    selected = questionary.checkbox(f"Métriques / checks — {profile}", choices=choices).ask()
    if selected is None:
        return None

    out = {k: False for k in METRIC_KEYS}
    for k in selected:
        out[k] = True
    return out


def _configure_nextcloud(console: Console, base: dict[str, Any], metrics: dict[str, bool]) -> dict[str, Any] | None:
    nc = dict(DEFAULT_NEXTCLOUD)
    existing = base.get("nextcloud") if isinstance(base.get("nextcloud"), dict) else {}
    nc.update(existing or {})

    console.print("\n[bold]Chemins Nextcloud[/bold] (Debian — exemples)")
    data_dir = questionary.text("Répertoire data Nextcloud", default=str(nc.get("data_dir", "/var/www/nextcloud/data"))).ask()
    if _ask_cancel(data_dir, console):
        return None
    web_root = questionary.text("Web root Nextcloud", default=str(nc.get("web_root", "/var/www/nextcloud"))).ask()
    if _ask_cancel(web_root, console):
        return None
    status_url = questionary.text(
        "URL status.php (ou serverinfo)",
        default=str(nc.get("status_url", "http://127.0.0.1/status.php")),
    ).ask()
    if _ask_cancel(status_url, console):
        return None
    occ_path = questionary.text("Chemin occ (vide = skip)", default=str(nc.get("occ_path", "/var/www/nextcloud/occ"))).ask()
    if _ask_cancel(occ_path, console):
        return None
    db_type = questionary.select(
        "Type de base",
        choices=["mariadb", "mysql", "postgresql"],
        default=str(nc.get("db_type", "mariadb")),
    ).ask()
    if _ask_cancel(db_type, console):
        return None
    services_default = nc.get("services") or DEFAULT_NEXTCLOUD["services"]
    svc_str = ",".join(str(s) for s in services_default) if isinstance(services_default, list) else "php8.4-fpm,nginx,mariadb,redis-server,cron"
    services_raw = questionary.text("Services systemd (séparés par des virgules)", default=svc_str).ask()
    if _ask_cancel(services_raw, console):
        return None
    services = [s.strip() for s in services_raw.split(",") if s.strip()]

    php_fpm = ""
    if metrics.get("php_fpm_workers"):
        php_fpm = questionary.text("URL status php-fpm (optionnel)", default=str(nc.get("php_fpm_status_url", ""))).ask()
        if php_fpm is None:
            return None
    log_path = ""
    if metrics.get("nc_errors"):
        log_path = questionary.text("Chemin log erreurs (optionnel)", default=str(nc.get("log_path", ""))).ask()
        if log_path is None:
            return None
    mounts: list[str] = []
    if metrics.get("nc_external_storage"):
        mounts_raw = questionary.text(
            "Montages externes (virgules)",
            default=",".join(str(m) for m in (nc.get("external_mounts") or [])),
        ).ask()
        if mounts_raw is None:
            return None
        mounts = [m.strip() for m in mounts_raw.split(",") if m.strip()]

    return {
        "data_dir": data_dir.strip(),
        "web_root": web_root.strip(),
        "status_url": status_url.strip(),
        "occ_path": occ_path.strip(),
        "php_fpm_status_url": (php_fpm or "").strip(),
        "log_path": (log_path or str(nc.get("log_path", ""))).strip(),
        "db_type": db_type,
        "services": services,
        "external_mounts": mounts or list(nc.get("external_mounts") or []),
    }


def _configure_status_opts(console: Console, base: dict[str, Any]) -> dict[str, Any] | None:
    st = dict(DEFAULT_STATUS)
    existing = base.get("status") if isinstance(base.get("status"), dict) else {}
    st.update(existing or {})
    ping_enabled = questionary.confirm(
        "Tester la connectivité (ping gateway / cible) ?",
        default=bool(st.get("ping_enabled", True)),
    ).ask()
    if ping_enabled is None:
        return None
    ping_target = questionary.text(
        "Cible ping (vide = gateway auto)",
        default=str(st.get("ping_target", "")),
    ).ask()
    if ping_target is None:
        return None
    return {"ping_enabled": bool(ping_enabled), "ping_target": ping_target.strip()}


def _maybe_save_named(console: Console, data: dict[str, Any], *, force: bool = False) -> None:
    do_save = questionary.confirm("Sauvegarder ce setup sous un nom ?", default=False).ask()
    if not do_save:
        return
    name = questionary.text(
        "Nom du setup (ex. nextcloud-n40)",
        validate=lambda s: bool(s.strip()) or "Nom requis",
    ).ask()
    if not name:
        return
    try:
        safe = sanitize_setup_name(name)
        path = save_setup(safe, data, force=force)
        data["setup_name"] = safe
        write_config(project_root() / "config.toml", data)
        console.print(f"[green]Setup sauvé[/green] {path}")
    except FileExistsError as exc:
        overwrite = questionary.confirm(f"{exc} Écraser ?", default=False).ask()
        if overwrite:
            path = save_setup(sanitize_setup_name(name), data, force=True)
            data["setup_name"] = sanitize_setup_name(name)
            write_config(project_root() / "config.toml", data)
            console.print(f"[green]Setup écrasé[/green] {path}")
        else:
            console.print("[yellow]Sauvegarde annulée[/yellow]")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")


def run_wizard() -> int:
    console = Console()
    console.print("[bold cyan]Setup Pixoo 64 Monitor[/bold cyan] — profils / affichage / setups nommés")

    base = _defaults_from_example()
    existing = project_root() / "config.toml"
    if existing.is_file():
        try:
            base = load_config(existing)
            console.print(f"[dim]Base existante: {existing}[/dim]")
            if base.get("setup_name"):
                console.print(f"[dim]Setup actif: {base['setup_name']}[/dim]")
        except Exception:
            pass

    touch_shared = True
    if existing.is_file():
        touch_shared = questionary.confirm(
            "Reconfigurer IP Pixoo / refresh / rendu ?",
            default=False,
        ).ask()
        if touch_shared is None:
            return 1

    shared: dict[str, Any]
    if touch_shared:
        result = _configure_shared(console, base)
        if result is None:
            return 1
        shared = result
    else:
        disp = base.get("display") if isinstance(base.get("display"), dict) else {}
        shared = {
            "ip": str(base.get("pixoo", {}).get("ip", "192.168.1.137")),
            "brightness": int(base.get("pixoo", {}).get("brightness", 60)),
            "interval": float(base.get("refresh", {}).get("interval_seconds", 3.0)),
            "page_seconds": float(base.get("refresh", {}).get("page_seconds", 8.0)),
            "overview": bool(disp.get("overview", True)),
            "render_mode": normalize_render_mode(disp.get("render_mode", "scaled")),
            "disk_style": normalize_disk_style(disp.get("disk_style", "bar")),
        }

    selected_profiles = _pick_profiles(console, base)
    if selected_profiles is None:
        return 1

    profiles_cfg: dict[str, Any] = {}
    if isinstance(base.get("profiles"), dict):
        profiles_cfg = dict(base["profiles"])

    n40_thermal = bool(base.get("display", {}).get("n40_thermal", False))

    for pname in selected_profiles:
        section = profiles_cfg.get(pname) if isinstance(profiles_cfg.get(pname), dict) else None
        toggled = _toggle_metrics_for_profile(console, pname, section)
        if toggled is None:
            return 1
        profiles_cfg[pname] = dict(toggled)
        profiles_cfg[pname]["enabled"] = True
        if pname in ("n40", "nextcloud_full"):
            n40_thermal = True

    prev_active = base.get("active_profiles") or []
    if not isinstance(prev_active, list):
        prev_active = []
    keep_others = questionary.confirm(
        "Garder les autres profils déjà actifs (en plus de ceux configurés) ?",
        default=True,
    ).ask()
    if keep_others is None:
        return 1
    active = list(dict.fromkeys([str(a) for a in prev_active] + selected_profiles)) if keep_others else list(selected_profiles)

    for name, section in list(profiles_cfg.items()):
        if isinstance(section, dict):
            section["enabled"] = name in active

    disk_path = str(base.get("disk", {}).get("path", ""))
    net_iface = str(base.get("network", {}).get("interface", ""))
    merged_for_prompts = resolve_active_metrics({"active_profiles": active, "profiles": profiles_cfg})

    if merged_for_prompts.get("disk") or merged_for_prompts.get("status_disk"):
        disk_path = questionary.text(
            "Point de montage disque générique (vide = auto)",
            default=disk_path,
        ).ask()
        if disk_path is None:
            return 1
        disk_path = disk_path.strip()

    if merged_for_prompts.get("network") or merged_for_prompts.get("status_network"):
        net_iface = questionary.text("Interface réseau (vide = auto)", default=net_iface).ask()
        if net_iface is None:
            return 1
        net_iface = net_iface.strip()

    nc_cfg = base.get("nextcloud") if isinstance(base.get("nextcloud"), dict) else dict(DEFAULT_NEXTCLOUD)
    if needs_nextcloud_settings(merged_for_prompts):
        ask_nc = questionary.confirm("Configurer chemins / services Nextcloud ?", default=True).ask()
        if ask_nc is None:
            return 1
        if ask_nc:
            nc_new = _configure_nextcloud(console, base, merged_for_prompts)
            if nc_new is None:
                return 1
            nc_cfg = nc_new

    status_cfg = base.get("status") if isinstance(base.get("status"), dict) else dict(DEFAULT_STATUS)
    if any(
        merged_for_prompts.get(k)
        for k in (
            "status_network", "status_overall", "status_host",
            "status_nc_http", "status_services", "status_disk", "status_thermal",
        )
    ):
        ask_st = questionary.confirm("Configurer options status (ping) ?", default=True).ask()
        if ask_st is None:
            return 1
        if ask_st:
            st_new = _configure_status_opts(console, base)
            if st_new is None:
                return 1
            status_cfg = st_new

    flat_metrics = resolve_active_metrics({"active_profiles": active, "profiles": profiles_cfg})

    screens_result = _configure_screens(console, base, flat_metrics)
    if screens_result is None:
        return 1
    screens_cfg, metric_styles = screens_result
    # Si écrans custom, propager disk_style legacy depuis le 1er style disk trouvé
    disk_style_legacy = shared["disk_style"]
    if metric_styles.get("disk"):
        disk_style_legacy = metric_styles["disk"]
    for scr in screens_cfg:
        st = (scr.get("styles") or {}).get("disk")
        if st:
            disk_style_legacy = st
            break

    hist_cfg = _configure_history(console, base, flat_metrics)
    if hist_cfg is None:
        return 1

    data: dict[str, Any] = {
        "setup_name": str(base.get("setup_name") or ""),
        "pixoo": {"ip": shared["ip"], "size": 64, "brightness": shared["brightness"]},
        "refresh": {
            "interval_seconds": shared["interval"],
            "page_seconds": shared["page_seconds"],
        },
        "active_profiles": active,
        "metrics": flat_metrics,
        "disk": {"path": disk_path},
        "network": {"interface": net_iface},
        "thresholds": base.get("thresholds") or {
            "cpu_percent": 90,
            "ram_percent": 90,
            "swap_percent": 80,
            "disk_percent": 90,
            "temperature_celsius": 85,
            "nc_disk_percent": 90,
        },
        "display": {
            "overview": bool(shared["overview"]) and not screens_cfg,
            "bars": True,
            "dark": True,
            "n40_thermal": n40_thermal or "n40" in active,
            "render_mode": shared["render_mode"],
            "disk_style": disk_style_legacy,
        },
        "metric_styles": metric_styles,
        "screens": screens_cfg,
        "history": hist_cfg,
        "nextcloud": nc_cfg,
        "status": status_cfg,
        "profiles": profiles_cfg,
    }

    out = project_root() / "config.toml"
    write_config(out, data)
    console.print(f"\n[green]Écrit[/green] {out}")
    console.print(f"[cyan]Profils actifs:[/cyan] {', '.join(active)}")
    console.print(f"[cyan]Rendu:[/cyan] {shared['render_mode']}")
    if screens_cfg:
        console.print(f"[cyan]Écrans:[/cyan] {len(screens_cfg)}")
        for scr in screens_cfg:
            t = scr.get("title") or default_title_for_metrics(list(scr.get("metrics") or []))
            console.print(f"  • {scr.get('id')}: {t} → {', '.join(scr.get('metrics') or [])}")
    elif metric_styles:
        console.print(f"[cyan]Styles:[/cyan] {metric_styles}")
    _maybe_save_named(console, data)
    console.print(
        "Lance [bold]./scripts/test.sh[/bold] puis [bold]./scripts/run.sh[/bold]\n"
        "Automation: [bold]./scripts/cron-setup.sh[/bold]  |  "
        "Setups: [bold]./scripts/setup.sh --list[/bold]"
    )
    return 0


def _cmd_list(console: Console) -> int:
    names = list_setups()
    active_path = project_root() / "config.toml"
    active = ""
    if active_path.is_file():
        try:
            active = str(load_config(active_path).get("setup_name") or "")
        except Exception:
            pass
    if not names:
        console.print("[dim]Aucun setup nommé dans configs/setups/[/dim]")
        return 0
    console.print("[bold]Setups sauvegardés[/bold] (configs/setups/)")
    for n in names:
        mark = " [cyan]← actif[/cyan]" if n == active else ""
        console.print(f"  • {n}{mark}")
    return 0


def _cmd_save(console: Console, name: str, *, force: bool) -> int:
    path = project_root() / "config.toml"
    if not path.is_file():
        console.print("[red]Pas de config.toml — lance le wizard d'abord[/red]")
        return 1
    data = load_config(path)
    try:
        out = save_setup(name, data, force=force)
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    data["setup_name"] = sanitize_setup_name(name)
    write_config(path, data)
    console.print(f"[green]Sauvé[/green] {out}")
    return 0


def _cmd_load(console: Console, name: str) -> int:
    try:
        out = apply_setup_to_active(name)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(f"[green]Setup chargé[/green] « {sanitize_setup_name(name)} » → {out}")
    console.print("Lance [bold]./scripts/run.sh[/bold] ou [bold]./scripts/test.sh[/bold]")
    return 0


def _cmd_delete(console: Console, name: str, *, force: bool) -> int:
    if not force:
        ok = questionary.confirm(f"Supprimer le setup « {name} » ?", default=False).ask()
        if not ok:
            console.print("[yellow]Annulé[/yellow]")
            return 0
    try:
        path = delete_setup(name)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(f"[green]Supprimé[/green] {path}")
    return 0


def _interactive_menu(console: Console) -> int:
    action = questionary.select(
        "Que veux-tu faire ?",
        choices=[
            questionary.Choice("Configurer / reconfigurer (wizard)", "wizard"),
            questionary.Choice("Charger un setup nommé", "load"),
            questionary.Choice("Sauvegarder le setup actuel", "save"),
            questionary.Choice("Lister les setups", "list"),
            questionary.Choice("Supprimer un setup", "delete"),
            questionary.Choice("Quitter", "quit"),
        ],
    ).ask()
    if action is None or action == "quit":
        return 0
    if action == "wizard":
        return run_wizard()
    if action == "list":
        return _cmd_list(console)
    if action == "load":
        names = list_setups()
        if not names:
            console.print("[yellow]Aucun setup — crée-en un via le wizard[/yellow]")
            return 1
        name = questionary.select("Setup à charger", choices=names).ask()
        if not name:
            return 1
        return _cmd_load(console, name)
    if action == "save":
        name = questionary.text("Nom du setup", validate=lambda s: bool(s.strip()) or "Requis").ask()
        if not name:
            return 1
        return _cmd_save(console, name, force=False)
    if action == "delete":
        names = list_setups()
        if not names:
            console.print("[dim]Aucun setup[/dim]")
            return 0
        name = questionary.select("Setup à supprimer", choices=names).ask()
        if not name:
            return 1
        return _cmd_delete(console, name, force=False)
    return 0


def print_help() -> None:
    print(
        """Usage: python -m pixoo_monitor.setup [options]

Wizard multi-profils Pixoo 64 — rendu, disque camembert, historique, setups nommés.

Sans argument: menu interactif (wizard / charger / sauver / lister / supprimer).

Options:
  --wizard              Lancer directement le wizard de (re)configuration
  --save NAME           Sauver config.toml actuel sous configs/setups/NAME.toml
  --load NAME           Charger un setup nommé → config.toml (actif)
  --list                Lister les setups sauvegardés
  --delete NAME         Supprimer un setup nommé
  --force               Écraser un setup existant (--save) ou supprimer sans confirm
  -h, --help            Cette aide

Exemples:
  ./scripts/setup.sh
  ./scripts/setup.sh --wizard
  ./scripts/setup.sh --save nextcloud-n40
  ./scripts/setup.sh --load nextcloud-n40
  ./scripts/setup.sh --list
  ./scripts/setup.sh --delete old-setup --force

Setups: configs/setups/<nom>.toml  |  actif: config.toml (setup_name=…)
"""
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False, description="Setup Pixoo 64 Monitor")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--wizard", action="store_true")
    parser.add_argument("--save", metavar="NAME")
    parser.add_argument("--load", metavar="NAME")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--delete", metavar="NAME")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--help-profiles", action="store_true")
    args = parser.parse_args(argv)

    if args.help:
        print_help()
        return 0

    console = Console()
    if args.help_profiles:
        console.print("[bold]Profils:[/bold]")
        for name in PROFILE_ORDER:
            console.print(f"  • {name:18} {PROFILE_LABELS.get(name, '')}")
        return 0

    if args.list:
        return _cmd_list(console)
    if args.save:
        return _cmd_save(console, args.save, force=args.force)
    if args.load:
        return _cmd_load(console, args.load)
    if args.delete:
        return _cmd_delete(console, args.delete, force=args.force)
    if args.wizard:
        return run_wizard()

    # Pas d'args → menu interactif
    return _interactive_menu(console)


if __name__ == "__main__":
    sys.exit(main())
