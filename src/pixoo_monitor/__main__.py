"""CLI live monitoring → Pixoo 64."""

from __future__ import annotations

import argparse
import sys

import questionary
from rich.console import Console

from .app import MonitorApp
from .config import apply_profile_override, find_config_path, load_config
from .profiles import PROFILE_LABELS, PROFILE_ORDER
from .setups import active_setup_name


def _interactive(console: Console, cfg: dict) -> argparse.Namespace:
    active = cfg.get("active_profiles") or []
    profiles = list(PROFILE_ORDER)
    for p in (cfg.get("profiles") or {}):
        if p not in profiles:
            profiles.append(str(p))

    use_override = questionary.confirm(
        "Forcer un profil unique pour cette session ?",
        default=False,
    ).ask()
    profile = None
    if use_override:
        choices = [
            questionary.Choice(
                f"{PROFILE_LABELS.get(p, p)} [{p}]",
                p,
            )
            for p in profiles
        ]
        profile = questionary.select("Profil", choices=choices).ask()

    once = questionary.confirm("Une seule frame puis quitter (--once) ?", default=False).ask()
    ip = str(cfg.get("pixoo", {}).get("ip", ""))
    questionary.confirm(f"Pousser vers le Pixoo {ip} ?", default=True).ask()

    ns = argparse.Namespace(config=None, profile=profile, once=bool(once), interactive=True)
    return ns


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Monitoring système → Pixoo 64",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exemples:
  ./scripts/run.sh
  ./scripts/run.sh --once
  ./scripts/run.sh --profile status
  ./scripts/run.sh -c ./config.toml --profile nextcloud_full

Sans argument: mode interactif (profil, once, confirmation IP).
""",
    )
    parser.add_argument("-c", "--config", help="Chemin vers config.toml")
    parser.add_argument(
        "-p",
        "--profile",
        help=f"Forcer un seul profil ({', '.join(PROFILE_ORDER)})",
    )
    parser.add_argument("--once", action="store_true", help="Une seule frame puis quitte")
    parser.add_argument("--interactive", action="store_true", help="Prompts interactifs")
    args = parser.parse_args(argv)

    console = Console(stderr=True)
    try:
        cfg_path = find_config_path(args.config)
        cfg = load_config(cfg_path)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    if args.interactive or (not argv):
        # Si appelé sans args depuis run.sh — interactif
        if not argv or args.interactive:
            try:
                args = _interactive(console, cfg)
            except Exception:
                pass

    if args.profile:
        if args.profile not in PROFILE_ORDER and args.profile not in (cfg.get("profiles") or {}):
            console.print(
                f"[yellow]Profil inconnu[/yellow] {args.profile} "
                f"(connus: {', '.join(PROFILE_ORDER)}) — tentative quand même"
            )
        cfg = apply_profile_override(cfg, args.profile)

    setup = active_setup_name(cfg)
    mode = str((cfg.get("display") or {}).get("render_mode", "scaled"))
    console.print(f"[cyan]Config[/cyan] {cfg['_config_path']}")
    if setup:
        console.print(f"[cyan]Setup[/cyan]  {setup}")
    console.print(f"[cyan]Pixoo[/cyan]  {cfg.get('pixoo', {}).get('ip')}")
    console.print(f"[cyan]Rendu[/cyan]  {mode}")
    if args.profile:
        label = PROFILE_LABELS.get(args.profile, args.profile)
        console.print(f"[cyan]Profil[/cyan] {args.profile} ({label})")
    else:
        active = cfg.get("active_profiles") or []
        console.print(f"[cyan]Profils[/cyan] {', '.join(str(a) for a in active) or '(legacy metrics)'}")

    try:
        app = MonitorApp(cfg, dry_run=False)
    except Exception as exc:
        console.print(f"[red]Connexion Pixoo impossible:[/red] {exc}")
        console.print("Vérifie l'IP dans config.toml, ou utilise ./scripts/test.sh")
        return 1

    if args.once:
        snap = app.collect()
        pages = app.pages(snap)
        name, image = pages[0]
        app.push(image)
        console.print(f"[green]Frame envoyée[/green] ({name})")
        return 0

    console.print("[green]Monitoring démarré[/green] — Ctrl+C pour arrêter")
    try:
        app.run_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]Arrêt[/yellow]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
