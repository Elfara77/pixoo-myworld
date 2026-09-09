"""Guided wizard to add and test a data source plugin."""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from pixoo.common.models import DataSourceConfig
from pixoo.plugins.base import get_registry
from pixoo.utils.secrets import resolve_secrets


class PluginConfigWizard(QDialog):
    """Simple multi-step-ish dialog: pick plugin → fill schema → test → accept."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add data source")
        self.resize(480, 560)
        self.registry = get_registry()
        self._result: DataSourceConfig | None = None
        self._widgets: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Plugin type"))
        self.plugin_combo = QComboBox()
        for name, plug in sorted(self.registry.plugins.items()):
            self.plugin_combo.addItem(f"{plug.name} — {plug.description}", name)
        self.plugin_combo.currentIndexChanged.connect(self._rebuild_form)
        layout.addWidget(self.plugin_combo)

        form_host = QWidget()
        self.form = QFormLayout(form_host)
        layout.addWidget(form_host)

        id_row = QHBoxLayout()
        self.id_edit = QLineEdit(f"src_{uuid.uuid4().hex[:6]}")
        self.label_edit = QLineEdit("My source")
        id_row.addWidget(QLabel("Source id"))
        id_row.addWidget(self.id_edit)
        id_row.addWidget(QLabel("Label"))
        id_row.addWidget(self.label_edit)
        layout.addLayout(id_row)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(100)
        layout.addWidget(QLabel("Test result"))
        layout.addWidget(self.preview)

        btn_test = QPushButton("Test fetch")
        btn_test.clicked.connect(self._test)
        layout.addWidget(btn_test)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._rebuild_form()

    def result_source(self) -> DataSourceConfig | None:
        return self._result

    def _rebuild_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._widgets.clear()
        name = str(self.plugin_combo.currentData())
        plug = self.registry.get(name)
        if not plug:
            return
        for key, prop in plug.get_config_schema().items():
            label = str(prop.get("label") or key)
            ptype = str(prop.get("type") or "string")
            default = prop.get("default")
            enum = prop.get("enum")
            if enum:
                w: QWidget = QComboBox()
                for v in enum:
                    w.addItem(str(v), v)  # type: ignore[attr-defined]
                if default in enum:
                    w.setCurrentIndex(list(enum).index(default))  # type: ignore[attr-defined]
            elif ptype == "boolean":
                w = QCheckBox()
                w.setChecked(bool(default))  # type: ignore[attr-defined]
            elif ptype == "integer":
                w = QSpinBox()
                w.setRange(-10**9, 10**9)  # type: ignore[attr-defined]
                w.setValue(int(default or 0))  # type: ignore[attr-defined]
            elif ptype in ("number", "float"):
                w = QDoubleSpinBox()
                w.setRange(-1e9, 1e9)  # type: ignore[attr-defined]
                w.setDecimals(4)  # type: ignore[attr-defined]
                w.setValue(float(default or 0))  # type: ignore[attr-defined]
            else:
                w = QLineEdit(str(default if default is not None else ""))
            self._widgets[key] = w
            self.form.addRow(label, w)

    def _values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, w in self._widgets.items():
            if isinstance(w, QComboBox):
                out[key] = w.currentData() if w.currentData() is not None else w.currentText()
            elif isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QDoubleSpinBox):
                out[key] = float(w.value())
            elif isinstance(w, QLineEdit):
                text = w.text()
                # try parse JSON objects/arrays for convenience
                if text[:1] in "{[":
                    try:
                        out[key] = json.loads(text)
                        continue
                    except json.JSONDecodeError:
                        pass
                out[key] = text
        return out

    def _test(self) -> None:
        name = str(self.plugin_combo.currentData())
        plug = self.registry.get(name)
        if not plug:
            return
        cfg = resolve_secrets(self._values())
        try:
            if not plug.validate_config(cfg):
                self.preview.setPlainText("Invalid configuration")
                return
            raw = plug.fetch_data(cfg)
            self.preview.setPlainText(json.dumps(raw, indent=2, default=str)[:2000])
        except Exception as exc:
            self.preview.setPlainText(f"Error: {exc}")

    def _accept(self) -> None:
        name = str(self.plugin_combo.currentData())
        sid = self.id_edit.text().strip()
        if not sid:
            QMessageBox.warning(self, "Source", "Source id required")
            return
        self._result = DataSourceConfig(
            id=sid,
            label=self.label_edit.text().strip() or sid,
            plugin=name,
            config=self._values(),
        )
        self.accept()
