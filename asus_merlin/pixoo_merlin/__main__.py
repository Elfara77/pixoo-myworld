"""CLI entry: run monitor + manage named setups."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _root() -> Path:
    return ROOT


def cmd_run(args: argparse.Namespace) -> int:
    from .app import build_app
    from .config import load_config

    if args.demo:
        import os

        os.environ["DEMO"] = "1"
    if args.setup:
        import os

        os.environ["SETUP"] = args.setup
    if args.env:
        cfg = load_config(args.env)
    else:
        cfg = load_config()
    if args.demo:
        # rebuild with demo flag forced
        from dataclasses import replace

        cfg = replace(cfg, demo=True)
    if args.preview:
        from dataclasses import replace

        cfg = replace(cfg, save_preview=args.preview)

    app = build_app(cfg, setup_name=args.setup or cfg.setup_name, root=_root())
    if args.once or (args.demo and args.preview):
        out = Path(args.preview or (_root() / "previews"))
        paths = app.run_once_demo_previews(out)
        for p in paths:
            print(p)
        return 0
    if args.demo and not args.forever:
        out = Path(args.preview or (_root() / "previews"))
        paths = app.run_once_demo_previews(out)
        print(f"demo: wrote {len(paths)} preview(s) under {out}")
        for p in paths:
            print(f"  {p}")
        return 0
    app.run_forever()
    return 0


def cmd_list_setups(_args: argparse.Namespace) -> int:
    from .setups import ensure_default_setup, list_setups, load_setup

    ensure_default_setup(_root())
    active = ""
    try:
        from .config import load_config
        import os

        os.environ.setdefault("DEMO", "1")
        active = load_config().setup_name
    except SystemExit:
        active = "default"
    for name in list_setups(_root()):
        setup = load_setup(name, _root())
        n = len(setup.enabled_screens())
        mark = "*" if name == active else " "
        print(f"{mark} {name}  screens_enabled={n}/{len(setup.screens)}  title={setup.title!r}")
    return 0


def cmd_show_setup(args: argparse.Namespace) -> int:
    from .setups import load_setup

    setup = load_setup(args.name, _root())
    print(f"setup: {setup.name}")
    print(f"title: {setup.title}")
    ss = setup.screen_seconds
    print(f"screen_seconds: {ss if ss is not None else '(config.env SCREEN_SECONDS)'}")
    if setup.path:
        print(f"path: {setup.path}")
    for i, sc in enumerate(setup.screens, 1):
        flag = "on " if sc.enabled else "off"
        dur = f"{sc.seconds:g}s" if sc.seconds is not None else "default"
        print(f"  [{flag}] {i}. {sc.id} ({dur}): {', '.join(sc.widgets)}")
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    from .setups import set_screen_enabled, set_screen_seconds

    if args.action == "seconds":
        raw = args.seconds
        if raw is None:
            raise ValueError("screen seconds requires a value (or 0 to clear override)")
        sec: float | None
        if float(raw) <= 0:
            sec = None
        else:
            sec = float(raw)
        setup = set_screen_seconds(args.setup, args.screen, sec, _root())
        shown = "default" if sec is None else f"{sec:g}s"
        print(f"{setup.name}: screen {args.screen} → {shown}")
        return 0

    enabled = args.action == "enable"
    setup = set_screen_enabled(args.setup, args.screen, enabled, _root())
    print(f"{setup.name}: screen {args.screen} → {'enabled' if enabled else 'disabled'}")
    return 0


def cmd_copy_setup(args: argparse.Namespace) -> int:
    from .setups import copy_setup

    path = copy_setup(args.src, args.dst, _root())
    print(f"copied {args.src} → {path}")
    return 0


def cmd_widget(args: argparse.Namespace) -> int:
    from .setups import set_widget_enabled

    enabled = args.action == "enable"
    setup = set_widget_enabled(args.setup, args.screen, args.widget, enabled, _root())
    print(
        f"{setup.name}/{args.screen}: widget {args.widget} → "
        f"{'enabled' if enabled else 'disabled'}"
    )
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    """Set SETUP= in config.env (create from example if needed)."""
    from .setups import load_setup

    load_setup(args.name, _root())  # validate
    env_path = _root() / "config.env"
    example = _root() / "config.example.env"
    if not env_path.is_file() and example.is_file():
        env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith("SETUP="):
            out.append(f"SETUP={args.name}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"SETUP={args.name}")
    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"active setup → {args.name} (wrote {env_path})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pixoo_merlin",
        description="AsusWRT-Merlin → Divoom Pixoo 64 monitor",
    )
    sub = p.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="Run monitor loop (default)")
    run.add_argument("--demo", action="store_true", help="Fake metrics; write PNG previews")
    run.add_argument("--forever", action="store_true", help="With --demo, loop forever")
    run.add_argument("--once", action="store_true", help="Render each screen once and exit")
    run.add_argument("--setup", default="", help="Setup name (overrides config.env)")
    run.add_argument("--env", default="", help="Path to config.env")
    run.add_argument("--preview", default="", help="Directory or PNG path for previews")
    run.set_defaults(func=cmd_run)

    ls = sub.add_parser("list-setups", help="List named setups")
    ls.set_defaults(func=cmd_list_setups)

    show = sub.add_parser("show-setup", help="Show setup screens/widgets")
    show.add_argument("name")
    show.set_defaults(func=cmd_show_setup)

    cp = sub.add_parser("copy-setup", help="Copy setup to a new name")
    cp.add_argument("src")
    cp.add_argument("dst")
    cp.set_defaults(func=cmd_copy_setup)

    use = sub.add_parser("use", help="Set active SETUP in config.env")
    use.add_argument("name")
    use.set_defaults(func=cmd_use)

    scr = sub.add_parser("screen", help="Enable/disable a screen in a setup")
    scr.add_argument("action", choices=("enable", "disable"))
    scr.add_argument("setup")
    scr.add_argument("screen", help="Screen id or 1-based index")
    scr.set_defaults(func=cmd_screen)

    wid = sub.add_parser("widget", help="Add/remove a widget on a screen")
    wid.add_argument("action", choices=("enable", "disable"))
    wid.add_argument("setup")
    wid.add_argument("screen")
    wid.add_argument("widget")
    wid.set_defaults(func=cmd_widget)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Default to run when no subcommand
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        return int(func(args))
    except (FileNotFoundError, FileExistsError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
