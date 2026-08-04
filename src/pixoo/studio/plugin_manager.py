"""Plugin list + dynamic schema form for Studio."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
)

from pixoo.plugins.base import get_registry


class PluginManagerWidget(QWidget):
    configChanged = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.registry = get_registry()
        layout = QVBoxLayout(self)
        self.combo = QComboBox()
        for name, plug in self.registry.plugins.items():
            self.combo.addItem(f"{plug.name} — {plug.description}", name)
        self.combo.currentIndexChanged.connect(self._rebuild)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self._widgets: dict[str, QWidget] = {}
        layout.addWidget(QLabel("Plugin"))
        layout.addWidget(self.combo)
        layout.addWidget(self.form_host)
        layout.addStretch(1)
        self._rebuild()

    def selected_plugin(self) -> str:
        return str(self.combo.currentData())

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, w in self._widgets.items():
            if isinstance(w, QComboBox):
                out[key] = w.currentData() if w.currentData() is not None else w.currentText()
            elif isinstance(w, QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QDoubleSpinBox):
                out[key] = float(w.value())
            elif isinstance(w, QLineEdit):
                out[key] = w.text()
        return out

    def _rebuild(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._widgets.clear()
        plug = self.registry.get(self.selected_plugin())
        if not plug:
            return
        schema = plug.get_config_schema()
        for key, prop in schema.items():
            label = str(prop.get("label") or key)
            ptype = str(prop.get("type") or "string")
            default = prop.get("default")
            enum = prop.get("enum")
            if enum:
                w: QWidget = QComboBox()
                for v in enum:
                    w.addItem(str(v), v)  # type: ignore[attr-defined]
                if default in enum:
                    w.setCurrentIndex(enum.index(default))  # type: ignore[attr-defined]
                w.currentIndexChanged.connect(lambda *_: self.configChanged.emit(self.values()))  # type: ignore[attr-defined]
            elif ptype == "integer":
                w = QSpinBox()
                w.setRange(0, 10**6)  # type: ignore[attr-defined]
                w.setValue(int(default or 0))  # type: ignore[attr-defined]
                w.valueChanged.connect(lambda *_: self.configChanged.emit(self.values()))  # type: ignore[attr-defined]
            elif ptype in ("number", "float"):
                w = QDoubleSpinBox()
                w.setRange(-1e9, 1e9)  # type: ignore[attr-defined]
                w.setValue(float(default or 0))  # type: ignore[attr-defined]
                w.valueChanged.connect(lambda *_: self.configChanged.emit(self.values()))  # type: ignore[attr-defined]
            else:
                w = QLineEdit(str(default if default is not None else ""))
                w.textChanged.connect(lambda *_: self.configChanged.emit(self.values()))  # type: ignore[attr-defined]
            self._widgets[key] = w
            self.form.addRow(label, w)
        self.configChanged.emit(self.values())
