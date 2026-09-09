"""Unified CLI entrypoint: studio | daemon | render."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from pixoo import API_VERSION, CONFIG_VERSION, __version__

app = typer.Typer(help="Pixoo Studio / Engine CLI", no_args_is_help=True)


@app.command("version")
def cmd_version() -> None:
    """Print package / API / config versions."""
    typer.echo(f"pixoo {__version__}  api={API_VERSION}  config={CONFIG_VERSION}")


@app.command("studio")
def cmd_studio(
    project: Optional[Path] = typer.Option(None, "--project", "-p", help="Path to .pixoo project"),
) -> None:
    """Launch the graphical Studio (PySide6)."""
    from pixoo.studio.app import run_studio

    run_studio(project)


@app.command("daemon")
def cmd_daemon(
    project: Path = typer.Option(..., "--project", "-p", exists=True, help="Path to .pixoo project"),
    pixoo_ip: Optional[str] = typer.Option(None, "--pixoo-ip", help="Override Pixoo IP"),
    host: str = typer.Option("127.0.0.1", "--host", help="API bind host"),
    port: int = typer.Option(8765, "--port", help="API bind port"),
) -> None:
    """Run the headless engine daemon + REST API."""
    from pixoo.engine.daemon import run_daemon

    run_daemon(project, pixoo_ip=pixoo_ip, host=host, port=port)


@app.command("render")
def cmd_render(
    project: Path = typer.Option(..., "--project", "-p", exists=True),
    output: Path = typer.Option(..., "--output", "-o", help="PNG output path"),
) -> None:
    """Render the first screen to a PNG (offline)."""
    from pixoo.common.config_manager import ConfigManager
    from pixoo.engine.scheduler import Scheduler

    proj = ConfigManager.load(project)
    sched = Scheduler(proj)
    sched.fetch_values()
    frame = sched.build_frame()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.save(output)
    typer.echo(f"Wrote {output}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
