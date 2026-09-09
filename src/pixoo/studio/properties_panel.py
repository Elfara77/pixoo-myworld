"""Contextual properties panel."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class PropertiesPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._el: Optional[dict[str, Any]] = None
        self._updating = False
        layout = QVBoxLayout(self)
        self.title = QLabel("No selection")
        self.title.setStyleSheet("font-weight:600;")
        form = QFormLayout()
        self.x = QSpinBox(); self.x.setRange(0, 63)
        self.y = QSpinBox(); self.y.setRange(0, 63)
        self.w = QSpinBox(); self.w.setRange(1, 64)
        self.h = QSpinBox(); self.h.setRange(1, 64)
        self.content = QLineEdit()
        self.color = QLineEdit("#FFFFFF")
        self.source = QLineEdit("system.cpu")
        self.animation = QComboBox()
        for a in ("none", "marquee", "fade"):
            self.animation.addItem(a, a)
        form.addRow("X", self.x)
        form.addRow("Y", self.y)
        form.addRow("W", self.w)
        form.addRow("H", self.h)
        form.addRow("Content", self.content)
        form.addRow("Color", self.color)
        form.addRow("Source", self.source)
        form.addRow("Animation", self.animation)
        layout.addWidget(self.title)
        layout.addLayout(form)
        layout.addStretch(1)
        for w in (self.x, self.y, self.w, self.h):
            w.valueChanged.connect(self._commit)
        for w in (self.content, self.color, self.source):
            w.textChanged.connect(self._commit)
        self.animation.currentIndexChanged.connect(self._commit)

    def bind(self, element: dict[str, Any] | None) -> None:
        self._el = element
        self._updating = True
        if not element:
            self.title.setText("No selection")
            self._updating = False
            return
        self.title.setText(f"{element.get('type')} · {element.get('id')}")
        self.x.setValue(int(element.get("x", 0)))
        self.y.setValue(int(element.get("y", 0)))
        self.w.setValue(int(element.get("w") or 8))
        self.h.setValue(int(element.get("h") or 8))
        self.content.setText(str(element.get("content") or element.get("text") or ""))
        self.color.setText(str(element.get("color") or "#FFFFFF"))
        self.source.setText(str(element.get("source") or element.get("source_id") or ""))
        anim = str(element.get("animation") or "none")
        self.animation.setCurrentIndex(max(0, self.animation.findData(anim)))
        self._updating = False

    def _commit(self, *_args: Any) -> None:
        if self._updating or not self._el:
            return
        self._el["x"] = self.x.value()
        self._el["y"] = self.y.value()
        self._el["w"] = self.w.value()
        self._el["h"] = self.h.value()
        if self._el.get("type") == "text":
            self._el["content"] = self.content.text()
            self._el["animation"] = self.animation.currentData()
        if "source" in self._el or self._el.get("type") in ("gauge", "graph"):
            self._el["source"] = self.source.text().strip()
        self._el["color"] = self.color.text().strip() or "#FFFFFF"
        self.changed.emit()
