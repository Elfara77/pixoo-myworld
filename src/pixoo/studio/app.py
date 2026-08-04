"""Launch Pixoo Studio GUI."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from pixoo.studio.main_window import MainWindow
from pixoo.utils.logging import setup_logging


def run_studio(project: Path | None = None) -> None:
    setup_logging()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Pixoo Studio")
    win = MainWindow(project)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    run_studio(path)