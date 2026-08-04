"""Point d'entrée — Pixoo 64 Designer (PySide6)."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("Pixoo 64 Designer")
    app.setOrganizationName("pixoo-monitor")

    qss = Path(__file__).resolve().parent / "resources" / "styles.qss"
    if qss.is_file():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
