"""64x64 canvas with zoom, click-select and drag reposition."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QPixmap
from PySide6.QtWidgets import QWidget
from PIL import Image


class CanvasWidget(QWidget):
    elementSelected = Signal(str)
    elementMoved = Signal(str, int, int)  # id, x, y

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scale = 8
        self._show_grid = True
        self._image: Image.Image | None = None
        self._elements: list[dict[str, Any]] = []
        self._selected_id: Optional[str] = None
        self._drag_id: Optional[str] = None
        self._drag_offset = QPoint(0, 0)
        self.setMouseTracking(True)
        self.setMinimumSize(64 * self._scale + 16, 64 * self._scale + 16)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_zoom(self, scale: int) -> None:
        self._scale = max(4, min(12, scale))
        self.setMinimumSize(64 * self._scale + 16, 64 * self._scale + 16)
        self.update()

    def set_grid(self, enabled: bool) -> None:
        self._show_grid = enabled
        self.update()

    def set_frame(self, image: Image.Image, elements: list[dict[str, Any]], selected_id: str | None) -> None:
        self._image = image
        self._elements = elements
        self._selected_id = selected_id
        self.update()

    def _to_pixel(self, pos: QPoint) -> tuple[int, int]:
        margin_x = max(0, (self.width() - 64 * self._scale) // 2)
        margin_y = max(0, (self.height() - 64 * self._scale) // 2)
        x = (pos.x() - margin_x) // self._scale
        y = (pos.y() - margin_y) // self._scale
        return max(0, min(63, x)), max(0, min(63, y))

    def _hit_test(self, px: int, py: int) -> str | None:
        # top-most first
        for el in sorted(self._elements, key=lambda e: int(e.get("z") or 0), reverse=True):
            if not el.get("visible", True):
                continue
            x, y = int(el.get("x", 0)), int(el.get("y", 0))
            w, h = int(el.get("w") or 8), int(el.get("h") or 8)
            if el.get("type") == "text":
                w, h = int(el.get("w") or 60), int(el.get("h") or 10)
            if x <= px < x + w and y <= py < y + h:
                return str(el.get("id"))
        return None

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta > 0:
            self.set_zoom(self._scale + 1)
        elif delta < 0:
            self.set_zoom(self._scale - 1)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        px, py = self._to_pixel(event.position().toPoint())
        eid = self._hit_test(px, py)
        self._selected_id = eid
        if eid:
            self.elementSelected.emit(eid)
            el = next((e for e in self._elements if e.get("id") == eid), None)
            if el:
                self._drag_id = eid
                self._drag_offset = QPoint(px - int(el.get("x", 0)), py - int(el.get("y", 0)))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if not self._drag_id or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        px, py = self._to_pixel(event.position().toPoint())
        nx = max(0, min(63, px - self._drag_offset.x()))
        ny = max(0, min(63, py - self._drag_offset.y()))
        for el in self._elements:
            if el.get("id") == self._drag_id:
                el["x"], el["y"] = nx, ny
                break
        self.elementMoved.emit(self._drag_id, nx, ny)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_id = None

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0b0b0d"))
        margin_x = max(0, (self.width() - 64 * self._scale) // 2)
        margin_y = max(0, (self.height() - 64 * self._scale) // 2)
        if self._image is not None:
            rgba = self._image.convert("RGBA")
            qimg = QImage(
                rgba.tobytes("raw", "RGBA"),
                rgba.width,
                rgba.height,
                QImage.Format.Format_RGBA8888,
            )
            pix = QPixmap.fromImage(qimg).scaled(
                64 * self._scale,
                64 * self._scale,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            painter.drawPixmap(margin_x, margin_y, pix)
        if self._show_grid:
            pen = QPen(QColor(255, 255, 255, 30))
            painter.setPen(pen)
            for i in range(65):
                x = margin_x + i * self._scale
                y = margin_y + i * self._scale
                painter.drawLine(x, margin_y, x, margin_y + 64 * self._scale)
                painter.drawLine(margin_x, y, margin_x + 64 * self._scale, y)
        if self._selected_id:
            el = next((e for e in self._elements if e.get("id") == self._selected_id), None)
            if el:
                x, y = int(el.get("x", 0)), int(el.get("y", 0))
                w, h = int(el.get("w") or 8), int(el.get("h") or 8)
                if el.get("type") == "text":
                    w, h = int(el.get("w") or 60), int(el.get("h") or 10)
                painter.setPen(QPen(QColor("#2d6cdf"), 2))
                painter.drawRect(
                    margin_x + x * self._scale,
                    margin_y + y * self._scale,
                    w * self._scale,
                    h * self._scale,
                )
