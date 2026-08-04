"""Mode test: collecte + rendu 64×64 sans Pixoo (PNG preview)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import questionary
from rich.console import Console
from rich.table import Table

from .app import MonitorApp, pixoo_reachable
from .config import apply_profile_override, enabled_metrics, find_config_path, load_config, project_root
from .profiles import PROFILE_ORDER
from .setups import active_setup_name


def _print_snapshot(console: Console, snap, cfg) -> None:
    table = Table(title="Métriques collectées", show_header=True, header_style="bold cyan")
    table.add_column("Clé")
    table.add_column("Valeur")
    metrics = cfg.get("_resolved_metrics") or cfg.get("metrics", {})

    rows: list[tuple[str, str]] = [
        ("host", snap.hostname),
        ("platform", snap.platform),
    ]
    if snap.cpu_percent is not None:
        rows.append(("cpu", f"{snap.cpu_percent:.1f}%"))
    if snap.cpu_per_core is not None:
        rows.append(("cpu_cores", ", ".join(f"{c:.0f}" for c in snap.cpu_per_core[:8])))
    if snap.load_avg is not None:
        l1, l5, l15 = snap.load_avg
        rows.append(("load", f"{l1:.2f} / {l5:.2f} / {l15:.2f}"))
    if snap.ram_percent is not None:
        rows.append(("ram", f"{snap.ram_percent:.1f}% ({snap.ram_used_gb:.1f}/{snap.ram_total_gb:.1f} GiB)"))
    if snap.swap_percent is not None:
        rows.append(("swap", f"{snap.swap_percent:.1f}% ({snap.swap_used_gb:.1f}/{snap.swap_total_gb:.1f} GiB)"))
    if snap.disk_percent is not None:
        rows.append(
            (
                "disk",
                f"{snap.disk_percent:.1f}% @ {snap.disk_path} "
                f"({snap.disk_used_gb:.0f}/{snap.disk_total_gb:.0f} GiB)",
            )
        )
    if snap.net_interface:
        up = "…" if snap.net_up_kbps is None else f"{snap.net_up_kbps:.0f} kbps"
        down = "…" if snap.net_down_kbps is None else f"{snap.net_down_kbps:.0f} kbps"
        rows.append(("net", f"{snap.net_interface} ↓{down} ↑{up}"))
    if metrics.get("temperature"):
        if snap.temperatures:
            rows.append(("temp", ", ".join(f"{n}={v:.0f}°C" for n, v in snap.temperatures)))
        else:
            rows.append(("temp", "N/A (osx-cpu-temp / lm-sensors)"))
    if snap.uptime_hours is not None:
        rows.append(("uptime", f"{snap.uptime_hours:.1f} h"))
    if snap.top_processes:
        rows.append(("procs", ", ".join(f"{n}({c:.0f}%)" for n, c in snap.top_processes)))

    nc = snap.nc
    if nc.services:
        parts = []
        for s in nc.services:
            mark = "OK" if s.active else ("KO" if s.active is False else "?")
            parts.append(f"{s.name}:{mark}")
        rows.append(("services", ", ".join(parts)))
    if nc.nc_http_ok is not None or nc.nc_http_detail:
        rows.append(
            (
                "nc_http",
                f"{'OK' if nc.nc_http_ok else ('KO' if nc.nc_http_ok is False else '?')} "
                f"{nc.nc_http_code or ''} {nc.nc_http_detail}".strip(),
            )
        )
    if nc.nc_disk_percent is not None:
        rows.append(("nc_disk", f"{nc.nc_disk_percent:.1f}% @ {nc.nc_disk_path}"))
    if nc.db_ok is not None:
        rows.append(("db", f"{'OK' if nc.db_ok else 'KO'} conn={nc.db_connections} {nc.db_detail}"))
    if nc.redis_ok is not None:
        mem = f"{nc.redis_memory_mb:.0f}MB" if nc.redis_memory_mb is not None else ""
        rows.append(("redis", f"{'OK' if nc.redis_ok else 'KO'} {mem} {nc.redis_detail}".strip()))

    st = snap.status
    if st.overall_label or st.items:
        rows.append(("status", f"{st.overall_label or st.overall}"))
        for name, h in st.items:
            rows.append((f"st.{name}", h))

    for k, v in rows:
        table.add_row(k, v)
    console.print(table)


def _interactive(cfg: dict) -> argparse.Namespace:
    profiles = list(PROFILE_ORDER)
    use = questionary.confirm("Forcer un profil ?", default=False).ask()
    profile = None
    if use:
        profile = questionary.select(
            "Profil",
            choices=profiles,
        ).ask()
    push = questionary.confirm("Tenter un push Pixoo si joignable ?", default=False).ask()
    out = questionary.text(
        "Dossier PNG preview",
        default=str(project_root() / "assets" / "test_preview"),
    ).ask()
    return argparse.Namespace(
        config=None,
        profile=profile,
        out=out or "",
        pixoo=bool(push),
        samples=2,
        interactive=True,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Mode test: collecte + rendu 64x64 sans Pixoo (PNG preview)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exemples:
  ./scripts/test.sh
  ./scripts/test.sh --pixoo
  ./scripts/test.sh --profile status -o /tmp/pixoo
Sans argument: prompts interactifs.
""",
    )
    parser.add_argument("-c", "--config", help="Chemin vers config.toml")
    parser.add_argument("-p", "--profile", help=f"Forcer un profil ({', '.join(PROFILE_ORDER)})")
    parser.add_argument("-o", "--out", default="", help="Dossier de sortie PNG")
    parser.add_argument("--pixoo", action="store_true", help="Pousse une frame test si IP joignable")
    parser.add_argument("--samples", type=int, default=2, help="Nombre de collectes")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args(argv)
    console = Console()

    try:
        cfg_path = find_config_path(args.config)
        cfg = load_config(cfg_path)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    if not argv or args.interactive:
        try:
            args = _interactive(cfg)
        except Exception:
            pass

    if args.profile:
        cfg = apply_profile_override(cfg, args.profile)

    out_dir = Path(args.out) if args.out else project_root() / "assets" / "test_preview"
    out_dir.mkdir(parents=True, exist_ok=True)

    setup = active_setup_name(cfg)
    mode = str((cfg.get("display") or {}).get("render_mode", "scaled"))
    disk_style = str((cfg.get("display") or {}).get("disk_style", "bar"))
    console.print(f"[cyan]Config[/cyan]  {cfg['_config_path']}")
    if setup:
        console.print(f"[cyan]Setup[/cyan]   {setup}")
    console.print(f"[cyan]Rendu[/cyan]   {mode}  disk={disk_style}")
    console.print(f"[cyan]Enabled[/cyan] {', '.join(enabled_metrics(cfg)) or '(aucune)'}")
    if args.profile:
        console.print(f"[cyan]Profile[/cyan] {args.profile}")
    console.print(f"[cyan]Output[/cyan]  {out_dir}")

    app = MonitorApp(cfg, dry_run=True)

    snap = None
    for i in range(max(1, args.samples)):
        snap = app.collect()
        if i + 1 < args.samples:
            time.sleep(1.0)

    assert snap is not None
    _print_snapshot(console, snap, cfg)

    pages = app.pages(snap)
    console.print(f"\n[bold]Pages rendues:[/bold] {len(pages)}  [dim]({mode})[/dim]")
    for name, image in pages:
        tag = f"{name}_{mode}"
        path = out_dir / f"{tag}.png"
        preview = image.resize((image.width * 4, image.height * 4), resample=0)
        preview.save(path)
        native = out_dir / f"{tag}_64.png"
        image.save(native)
        console.print(f"  • {name:14} → {path.name} + {native.name}")

    errors: list[str] = []
    for name, image in pages:
        if image.size != (app.size, app.size):
            errors.append(f"{name}: taille {image.size} ≠ ({app.size},{app.size})")
        if image.mode != "RGB":
            errors.append(f"{name}: mode {image.mode} ≠ RGB")

    resolved = cfg.get("_resolved_metrics") or cfg.get("metrics", {})
    if resolved.get("cpu") and snap.cpu_percent is None:
        errors.append("CPU activé mais valeur absente")
    if resolved.get("ram") and snap.ram_percent is None:
        errors.append("RAM activée mais valeur absente")

    if errors:
        console.print("\n[red]Échecs:[/red]")
        for e in errors:
            console.print(f"  ✗ {e}")
        return 1

    console.print("\n[green]OK[/green] collecte + rendu validés (dry-run)")

    if args.pixoo:
        ip = str(cfg.get("pixoo", {}).get("ip", ""))
        console.print(f"\n[cyan]Probe Pixoo[/cyan] {ip}:80 …")
        if not pixoo_reachable(ip):
            console.print(f"[yellow]Pixoo injoignable[/yellow] ({ip}) — skip push")
            return 0
        try:
            live = MonitorApp(cfg, dry_run=False)
            live.push(pages[0][1])
            console.print(f"[green]Frame test poussée[/green] ({pages[0][0]}) → {ip}")
        except Exception as exc:
            console.print(f"[red]Push échoué:[/red] {exc}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
