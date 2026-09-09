"""Widgets canvas, logs, LED statut."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPixmap, QPainter, QBrush
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from PIL import Image

from ..render.engine import RenderEngine


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class StatusLed(QWidget):
    """Indicateur LED rouge / jaune / vert."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._status = "unknown"
        self.setFixedSize(18, 18)

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def paintEvent(self, _event) -> None:
        colors = {
            "ok": QColor("#28DC64"),
            "degraded": QColor("#F0C828"),
            "down": QColor("#FF4646"),
            "unknown": QColor("#666670"),
        }
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(colors.get(self._status, colors["unknown"])))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(2, 2, 14, 14)


class PreviewCanvas(QWidget):
    """Aperçu WYSIWYG 64×64 avec zoom."""

    def __init__(self, engine: RenderEngine | None = None, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine or RenderEngine()
        self._scale = 8
        self._pixmap: QPixmap | None = None
        layout = QVBoxLayout(self)
        title = QLabel("Canvas Pixoo 64×64")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        self.frame = QLabel()
        self.frame.setObjectName("previewFrame")
        self.frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meta = QLabel("—")
        self.meta.setStyleSheet("color:#9a9aa6;")
        layout.addWidget(title)
        layout.addWidget(self.frame, 1, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.meta)
        self._apply_min()

    def set_zoom(self, scale: int) -> None:
        self._scale = max(4, min(12, scale))
        self._apply_min()
        if self._pixmap:
            self.frame.setPixmap(self._pixmap)

    def _apply_min(self) -> None:
        self.frame.setMinimumSize(64 * self._scale + 24, 64 * self._scale + 24)

    def show_image(self, image: Image.Image, meta: str = "") -> None:
        scaled = self.engine.scale_preview(image, self._scale)
        self._pixmap = pil_to_qpixmap(scaled)
        self.frame.setPixmap(self._pixmap)
        self.meta.setText(meta or f"zoom ×{self._scale}")


class LogDock(QWidget):
    """Console de logs filtrable."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.level = QComboBox()
        self.level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.level.setCurrentText("INFO")
        self.level.currentTextChanged.connect(self._apply_filter)
        bar.addWidget(QLabel("Niveau"))
        bar.addWidget(self.level)
        bar.addStretch(1)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)
        self._records: list[tuple[int, str]] = []

    def append(self, level: int, message: str) -> None:
        self._records.append((level, message))
        if len(self._records) > 2000:
            self._records = self._records[-1500:]
        self._apply_filter()

    def _apply_filter(self) -> None:
        min_level = getattr(logging, self.level.currentText(), logging.INFO)
        lines = [m for lvl, m in self._records if lvl >= min_level]
        self.view.setPlainText("\n".join(lines[-500:]))
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())


class QtLogHandler(logging.Handler):
    def __init__(self, sink: Callable[[int, str], None]) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.sink(record.levelno, msg)
        except Exception:
            pass
