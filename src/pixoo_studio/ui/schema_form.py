"""Génération automatique de formulaires Qt depuis un schéma plugin."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SchemaForm(QWidget):
    """Construit des champs à partir d'un dict style JSON Schema (sous-ensemble)."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._widgets: dict[str, QWidget] = {}
        self._schema: dict[str, Any] = {}

    def build(self, schema: dict[str, Any], values: dict[str, Any] | None = None) -> None:
        while self._layout.rowCount():
            self._layout.removeRow(0)
        self._widgets.clear()
        self._schema = schema or {}
        values = values or {}
        props = self._schema.get("properties") or {}
        for key, prop in props.items():
            title = str(prop.get("title") or key)
            w = self._make_widget(prop, values.get(key, prop.get("default")))
            self._widgets[key] = w
            self._layout.addRow(title, w)

    def _make_widget(self, prop: dict[str, Any], value: Any) -> QWidget:
        ptype = prop.get("type", "string")
        enum = prop.get("enum")
        if enum:
            combo = QComboBox()
            labels = prop.get("enumLabels") or enum
            for lab, val in zip(labels, enum):
                combo.addItem(str(lab), val)
            if value in enum:
                combo.setCurrentIndex(enum.index(value))
            combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
            return combo
        if ptype == "boolean":
            cb = QCheckBox()
            cb.setChecked(bool(value))
            cb.toggled.connect(lambda *_: self.changed.emit())
            return cb
        if ptype == "integer":
            sp = QSpinBox()
            sp.setRange(-10**9, 10**9)
            sp.setValue(int(value or 0))
            sp.valueChanged.connect(lambda *_: self.changed.emit())
            return sp
        if ptype == "number":
            sp = QDoubleSpinBox()
            sp.setRange(-1e12, 1e12)
            sp.setDecimals(4)
            sp.setValue(float(value or 0))
            sp.valueChanged.connect(lambda *_: self.changed.emit())
            return sp
        le = QLineEdit(str(value if value is not None else ""))
        le.textChanged.connect(lambda *_: self.changed.emit())
        return le

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, w in self._widgets.items():
            if isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QDoubleSpinBox):
                out[key] = float(w.value())
            elif isinstance(w, QLineEdit):
                out[key] = w.text()
        return out
