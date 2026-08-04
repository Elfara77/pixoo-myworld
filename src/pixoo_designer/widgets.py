"""Widgets UI — preview, listes, inspecteurs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .model import DataSource, Element, Project, Screen
from .render import render_screen, scale_preview


def pil_to_qpixmap(image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class PreviewWidget(QWidget):
    """Aperçu 64×64 agrandi (nearest)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scale = 8
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Aperçu Pixoo 64×64")
        title.setStyleSheet("font-weight:600; font-size:14px;")
        self.frame = QLabel()
        self.frame.setObjectName("previewFrame")
        self.frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame.setMinimumSize(64 * self._scale + 24, 64 * self._scale + 24)
        self.meta = QLabel("—")
        self.meta.setStyleSheet("color:#9a9aa6;")
        layout.addWidget(title)
        layout.addWidget(self.frame, 1, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.meta)

    def set_scale(self, scale: int) -> None:
        self._scale = max(4, min(12, scale))
        self.frame.setMinimumSize(64 * self._scale + 24, 64 * self._scale + 24)

    def show_screen(self, screen: Screen | None, project: Project, values: dict) -> None:
        if screen is None:
            self.frame.clear()
            self.meta.setText("Aucun écran")
            return
        img = render_screen(screen, project, values)
        pix = pil_to_qpixmap(scale_preview(img, self._scale))
        self.frame.setPixmap(pix)
        n = len([e for e in screen.elements if e.visible])
        self.meta.setText(f"{screen.title}  ·  {n} éléments  ·  {screen.duration_s:.0f}s  ·  zoom ×{self._scale}")


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#FFFFFF", parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedHeight(28)
        self.clicked.connect(self._pick)
        self._apply()

    def color(self) -> str:
        return self._color

    def setColor(self, color: str) -> None:
        self._color = color
        self._apply()

    def _apply(self) -> None:
        self.setText(self._color)
        self.setStyleSheet(
            f"background:{self._color}; color:{'#111' if self._luma() > 160 else '#fff'};"
            "border-radius:6px; border:1px solid #444;"
        )

    def _luma(self) -> float:
        c = QColor(self._color)
        return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()

    def _pick(self) -> None:
        col = QColorDialog.getColor(QColor(self._color), self, "Couleur")
        if col.isValid():
            self._color = col.name().upper()
            self._apply()
            self.colorChanged.emit(self._color)


class ScreenListPanel(QWidget):
    screenSelected = Signal(str)
    addRequested = Signal()
    removeRequested = Signal()
    duplicateRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_sel)
        btns = QHBoxLayout()
        self.btn_add = QPushButton("+ Écran")
        self.btn_dup = QPushButton("Dupliquer")
        self.btn_dup.setObjectName("secondary")
        self.btn_del = QPushButton("Suppr.")
        self.btn_del.setObjectName("secondary")
        self.btn_add.clicked.connect(self.addRequested.emit)
        self.btn_dup.clicked.connect(self.duplicateRequested.emit)
        self.btn_del.clicked.connect(self.removeRequested.emit)
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_dup)
        btns.addWidget(self.btn_del)
        layout.addWidget(self.list, 1)
        layout.addLayout(btns)

    def _on_sel(self, cur: QListWidgetItem | None, _prev) -> None:
        if cur:
            self.screenSelected.emit(cur.data(Qt.ItemDataRole.UserRole))

    def reload(self, project: Project, selected_id: str | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for scr in project.screens:
            item = QListWidgetItem(f"{scr.title}  ({len(scr.elements)})")
            item.setData(Qt.ItemDataRole.UserRole, scr.id)
            self.list.addItem(item)
            if selected_id and scr.id == selected_id:
                self.list.setCurrentItem(item)
        if selected_id is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)


class ElementListPanel(QWidget):
    elementSelected = Signal(str)
    addRequested = Signal(str)  # type
    removeRequested = Signal()
    moveRequested = Signal(int)  # delta

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_sel)
        add_row = QHBoxLayout()
        self.combo_type = QComboBox()
        for t, label in (
            ("text", "Texte"),
            ("value", "Valeur"),
            ("bar", "Barre %"),
            ("pie", "Camembert"),
            ("sparkline", "Graphe / sparkline"),
            ("status_dot", "Pastille status"),
            ("rect", "Rectangle"),
            ("pattern", "Pattern fond"),
        ):
            self.combo_type.addItem(label, t)
        self.btn_add = QPushButton("+")
        self.btn_add.clicked.connect(lambda: self.addRequested.emit(self.combo_type.currentData()))
        add_row.addWidget(self.combo_type, 1)
        add_row.addWidget(self.btn_add)
        ops = QHBoxLayout()
        self.btn_up = QPushButton("↑")
        self.btn_up.setObjectName("secondary")
        self.btn_down = QPushButton("↓")
        self.btn_down.setObjectName("secondary")
        self.btn_del = QPushButton("Suppr.")
        self.btn_del.setObjectName("secondary")
        self.btn_up.clicked.connect(lambda: self.moveRequested.emit(-1))
        self.btn_down.clicked.connect(lambda: self.moveRequested.emit(1))
        self.btn_del.clicked.connect(self.removeRequested.emit)
        ops.addWidget(self.btn_up)
        ops.addWidget(self.btn_down)
        ops.addWidget(self.btn_del)
        layout.addWidget(self.list, 1)
        layout.addLayout(add_row)
        layout.addLayout(ops)

    def _on_sel(self, cur: QListWidgetItem | None, _prev) -> None:
        if cur:
            self.elementSelected.emit(cur.data(Qt.ItemDataRole.UserRole))

    def reload(self, screen: Screen | None, selected_id: str | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        if screen:
            for el in sorted(screen.elements, key=lambda e: (e.z, e.y)):
                mark = "" if el.visible else " (caché)"
                item = QListWidgetItem(f"{el.type} · ({el.x},{el.y}){mark}")
                item.setData(Qt.ItemDataRole.UserRole, el.id)
                self.list.addItem(item)
                if selected_id and el.id == selected_id:
                    self.list.setCurrentItem(item)
        self.list.blockSignals(False)


class InspectorPanel(QWidget):
    """Inspecteur écran + élément + source liés."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._screen: Screen | None = None
        self._element: Element | None = None
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Screen props
        g_scr = QGroupBox("Écran")
        form_s = QFormLayout(g_scr)
        self.scr_title = QLineEdit()
        self.scr_title_mode = QComboBox()
        self.scr_title_mode.addItem("Personnalisé", "custom")
        self.scr_title_mode.addItem("Par défaut", "default")
        self.scr_title_mode.addItem("Masqué", "hidden")
        self.scr_duration = QDoubleSpinBox()
        self.scr_duration.setRange(1, 3600)
        self.scr_duration.setSuffix(" s")
        self.scr_bg = ColorButton("#000000")
        form_s.addRow("Titre", self.scr_title)
        form_s.addRow("Mode titre", self.scr_title_mode)
        form_s.addRow("Durée page", self.scr_duration)
        form_s.addRow("Fond", self.scr_bg)

        # Element props
        g_el = QGroupBox("Élément")
        form_e = QFormLayout(g_el)
        self.el_type = QLabel("—")
        self.el_x = QSpinBox(); self.el_x.setRange(0, 63)
        self.el_y = QSpinBox(); self.el_y.setRange(0, 63)
        self.el_w = QSpinBox(); self.el_w.setRange(1, 64)
        self.el_h = QSpinBox(); self.el_h.setRange(1, 64)
        self.el_z = QSpinBox(); self.el_z.setRange(0, 99)
        self.el_text = QLineEdit()
        self.el_source = QComboBox()
        self.el_format = QLineEdit()
        self.el_period = QLineEdit()
        self.el_period.setPlaceholderText("15m, 1h, 7j, 30s…")
        self.el_pattern = QComboBox()
        for p in ("none", "grid", "dots", "scanlines", "diagonal", "noise"):
            self.el_pattern.addItem(p, p)
        self.el_font = QSpinBox(); self.el_font.setRange(1, 3)
        self.el_visible = QCheckBox("Visible")
        self.el_progress = QCheckBox("Barre progression graphe")
        self.el_color = ColorButton()
        self.el_color_warn = ColorButton("#F0C828")
        self.el_color_crit = ColorButton("#FF4646")
        self.el_color_bg = ColorButton("#14141C")
        self.el_warn = QDoubleSpinBox(); self.el_warn.setRange(0, 1e6)
        self.el_crit = QDoubleSpinBox(); self.el_crit.setRange(0, 1e6)

        form_e.addRow("Type", self.el_type)
        form_e.addRow("X", self.el_x)
        form_e.addRow("Y", self.el_y)
        form_e.addRow("Largeur", self.el_w)
        form_e.addRow("Hauteur", self.el_h)
        form_e.addRow("Z-order", self.el_z)
        form_e.addRow("Texte", self.el_text)
        form_e.addRow("Source", self.el_source)
        form_e.addRow("Format", self.el_format)
        form_e.addRow("Période graphe", self.el_period)
        form_e.addRow("Pattern", self.el_pattern)
        form_e.addRow("Taille police", self.el_font)
        form_e.addRow("Couleur", self.el_color)
        form_e.addRow("Warn", self.el_color_warn)
        form_e.addRow("Crit", self.el_color_crit)
        form_e.addRow("Fond jauge", self.el_color_bg)
        form_e.addRow("Seuil warn", self.el_warn)
        form_e.addRow("Seuil crit", self.el_crit)
        form_e.addRow("", self.el_visible)
        form_e.addRow("", self.el_progress)

        root.addWidget(g_scr)
        root.addWidget(g_el, 1)

        for w in (
            self.scr_title, self.scr_title_mode, self.scr_duration, self.scr_bg,
            self.el_x, self.el_y, self.el_w, self.el_h, self.el_z, self.el_text,
            self.el_source, self.el_format, self.el_period, self.el_pattern,
            self.el_font, self.el_visible, self.el_progress,
            self.el_color, self.el_color_warn, self.el_color_crit, self.el_color_bg,
            self.el_warn, self.el_crit,
        ):
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._commit)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.valueChanged.connect(self._commit)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._commit)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._commit)
            elif isinstance(w, ColorButton):
                w.colorChanged.connect(self._commit)

    def bind(self, project: Project, screen: Screen | None, element: Element | None) -> None:
        self._project = project
        self._screen = screen
        self._element = element
        self._updating = True
        # sources combo
        self.el_source.clear()
        self.el_source.addItem("— aucune —", "")
        for s in project.sources:
            self.el_source.addItem(f"{s.label or s.id}", s.id)

        if screen:
            self.scr_title.setText(screen.title)
            idx = self.scr_title_mode.findData(screen.title_mode)
            self.scr_title_mode.setCurrentIndex(max(0, idx))
            self.scr_duration.setValue(screen.duration_s)
            self.scr_bg.setColor(screen.background)
        if element:
            self.el_type.setText(element.type)
            self.el_x.setValue(element.x)
            self.el_y.setValue(element.y)
            self.el_w.setValue(element.w)
            self.el_h.setValue(element.h)
            self.el_z.setValue(element.z)
            self.el_text.setText(element.text)
            si = self.el_source.findData(element.source_id)
            self.el_source.setCurrentIndex(max(0, si))
            self.el_format.setText(element.format)
            self.el_period.setText(element.period)
            pi = self.el_pattern.findData(element.pattern)
            self.el_pattern.setCurrentIndex(max(0, pi))
            self.el_font.setValue(element.font_size)
            self.el_visible.setChecked(element.visible)
            self.el_progress.setChecked(element.show_progress)
            self.el_color.setColor(element.color)
            self.el_color_warn.setColor(element.color_warn)
            self.el_color_crit.setColor(element.color_crit)
            self.el_color_bg.setColor(element.color_bg)
            self.el_warn.setValue(element.warn_at)
            self.el_crit.setValue(element.crit_at)
        self._updating = False

    def _commit(self, *_args) -> None:
        if self._updating:
            return
        if self._screen:
            self._screen.title = self.scr_title.text()
            self._screen.title_mode = self.scr_title_mode.currentData()
            self._screen.duration_s = float(self.scr_duration.value())
            self._screen.background = self.scr_bg.color()
        if self._element:
            el = self._element
            el.x = self.el_x.value()
            el.y = self.el_y.value()
            el.w = self.el_w.value()
            el.h = self.el_h.value()
            el.z = self.el_z.value()
            el.text = self.el_text.text()
            el.source_id = self.el_source.currentData() or ""
            el.format = self.el_format.text()
            el.period = self.el_period.text().strip() or "15m"
            el.pattern = self.el_pattern.currentData()
            el.font_size = self.el_font.value()
            el.visible = self.el_visible.isChecked()
            el.show_progress = self.el_progress.isChecked()
            el.color = self.el_color.color()
            el.color_warn = self.el_color_warn.color()
            el.color_crit = self.el_color_crit.color()
            el.color_bg = self.el_color_bg.color()
            el.warn_at = float(self.el_warn.value())
            el.crit_at = float(self.el_crit.value())
        self.changed.emit()


class SourceEditorPanel(QWidget):
    """Édition des sources de données (commande / parse / builtin)."""

    changed = Signal()
    testRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._source: DataSource | None = None
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_sel)
        top.addWidget(self.list, 1)

        form_box = QGroupBox("Source sélectionnée")
        form = QFormLayout(form_box)
        self.s_label = QLineEdit()
        self.s_kind = QComboBox()
        for k, lab in (
            ("builtin", "Builtin (psutil)"),
            ("command", "Commande shell"),
            ("http", "HTTP GET"),
            ("static", "Valeur fixe (preview)"),
        ):
            self.s_kind.addItem(lab, k)
        self.s_builtin = QComboBox()
        from .datasources import BUILTIN_KEYS

        for key, lab in BUILTIN_KEYS:
            self.s_builtin.addItem(lab, key)
        self.s_command = QLineEdit()
        self.s_command.setPlaceholderText('ex: df -P / | awk \'END{print $5}\'')
        self.s_url = QLineEdit()
        self.s_parse = QComboBox()
        for k, lab in (
            ("float", "Premier nombre"),
            ("percent", "Pourcentage"),
            ("regex", "Regex (groupe 1)"),
            ("json_path", "JSON path a.b.0"),
            ("line_field", "Ligne:champ[:sep]"),
        ):
            self.s_parse.addItem(lab, k)
        self.s_expr = QLineEdit()
        self.s_expr.setPlaceholderText("regex / json_path / line:field")
        self.s_unit = QLineEdit()
        self.s_min = QDoubleSpinBox(); self.s_min.setRange(-1e9, 1e9)
        self.s_max = QDoubleSpinBox(); self.s_max.setRange(-1e9, 1e9); self.s_max.setValue(100)
        self.s_static = QDoubleSpinBox(); self.s_static.setRange(-1e9, 1e9)
        self.s_result = QLabel("—")
        self.s_result.setWordWrap(True)
        self.s_result.setStyleSheet("color:#9a9aa6;")

        form.addRow("Nom", self.s_label)
        form.addRow("Type", self.s_kind)
        form.addRow("Builtin", self.s_builtin)
        form.addRow("Commande", self.s_command)
        form.addRow("URL", self.s_url)
        form.addRow("Parse", self.s_parse)
        form.addRow("Expression", self.s_expr)
        form.addRow("Unité", self.s_unit)
        form.addRow("Min", self.s_min)
        form.addRow("Max", self.s_max)
        form.addRow("Static", self.s_static)
        form.addRow("Dernier test", self.s_result)

        btns = QHBoxLayout()
        self.btn_add = QPushButton("+ Source")
        self.btn_del = QPushButton("Suppr.")
        self.btn_del.setObjectName("secondary")
        self.btn_test = QPushButton("Tester")
        self.btn_add.clicked.connect(self._add)
        self.btn_del.clicked.connect(self._del)
        self.btn_test.clicked.connect(self.testRequested.emit)
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_del)
        btns.addWidget(self.btn_test)

        layout.addLayout(top)
        layout.addWidget(form_box, 1)
        layout.addLayout(btns)

        for w in (
            self.s_label, self.s_kind, self.s_builtin, self.s_command, self.s_url,
            self.s_parse, self.s_expr, self.s_unit, self.s_min, self.s_max, self.s_static,
        ):
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._commit)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.valueChanged.connect(self._commit)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._commit)

    def set_test_result(self, text: str) -> None:
        self.s_result.setText(text)

    def reload(self, project: Project, selected_id: str | None = None) -> None:
        self._project = project
        self.list.blockSignals(True)
        self.list.clear()
        for s in project.sources:
            item = QListWidgetItem(f"{s.label or s.id} [{s.kind}]")
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self.list.addItem(item)
            if selected_id and s.id == selected_id:
                self.list.setCurrentItem(item)
        if selected_id is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._load_current()

    def _on_sel(self, *_args) -> None:
        self._load_current()

    def current_source(self) -> DataSource | None:
        return self._source

    def _load_current(self) -> None:
        if not self._project:
            return
        item = self.list.currentItem()
        sid = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._source = self._project.source_by_id(sid) if sid else None
        s = self._source
        self._updating = True
        if s:
            self.s_label.setText(s.label)
            self.s_kind.setCurrentIndex(max(0, self.s_kind.findData(s.kind)))
            self.s_builtin.setCurrentIndex(max(0, self.s_builtin.findData(s.builtin_key)))
            self.s_command.setText(s.command)
            self.s_url.setText(s.url)
            self.s_parse.setCurrentIndex(max(0, self.s_parse.findData(s.parse_mode)))
            self.s_expr.setText(s.parse_expr)
            self.s_unit.setText(s.unit)
            self.s_min.setValue(s.min_value)
            self.s_max.setValue(s.max_value)
            self.s_static.setValue(s.static_value)
        self._updating = False

    def _commit(self, *_args) -> None:
        if self._updating or not self._source:
            return
        s = self._source
        s.label = self.s_label.text()
        s.kind = self.s_kind.currentData()
        s.builtin_key = self.s_builtin.currentData()
        s.command = self.s_command.text()
        s.url = self.s_url.text()
        s.parse_mode = self.s_parse.currentData()
        s.parse_expr = self.s_expr.text()
        s.unit = self.s_unit.text()
        s.min_value = float(self.s_min.value())
        s.max_value = float(self.s_max.value())
        s.static_value = float(self.s_static.value())
        # refresh list label
        item = self.list.currentItem()
        if item:
            item.setText(f"{s.label or s.id} [{s.kind}]")
        self.changed.emit()

    def _add(self) -> None:
        if not self._project:
            return
        from .model import _nid

        s = DataSource(id=_nid("src"), label="Nouvelle source", kind="builtin", builtin_key="cpu")
        self._project.sources.append(s)
        self.reload(self._project, s.id)
        self.changed.emit()

    def _del(self) -> None:
        if not self._project or not self._source:
            return
        self._project.sources = [s for s in self._project.sources if s.id != self._source.id]
        self.reload(self._project)
        self.changed.emit()
