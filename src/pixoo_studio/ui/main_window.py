"""Fenêtre principale Pixoo Studio."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QSystemTrayIcon,
    QMenu,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from ..domain.models import DataSourceDef, Project, ProjectMeta, Screen, default_project, new_element, new_id
from ..persistence.store import ProjectStore
from ..plugins.base import get_loader
from ..render.engine import RenderEngine
from ..runtime.service import DataFetcher, SendService
from .schema_form import SchemaForm
from .widgets import LogDock, PreviewCanvas, QtLogHandler, StatusLed

ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger("pixoo_studio")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pixoo Studio")
        self.resize(1360, 860)

        self.project = default_project()
        self.path: Path | None = None
        self.engine = RenderEngine()
        self.loader = get_loader()
        self.fetcher = DataFetcher(self.loader)
        self.send_service = SendService(self.project, self.engine)
        self.current_screen_id = self.project.screens[0].id if self.project.screens else None
        self.current_element_id: str | None = None
        self.current_source_id: str | None = None
        self.values: dict = {}
        self._anim_t0 = time.monotonic()

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._build_tray()
        self._setup_logging()

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(max(33, int(1000 / max(1, self.project.meta.ui_fps))))
        self.anim_timer.timeout.connect(self._on_anim_tick)
        self.anim_timer.start()

        self.fetch_timer = QTimer(self)
        self.fetch_timer.setInterval(int(self.project.meta.refresh_s * 1000))
        self.fetch_timer.timeout.connect(self.refresh_values)
        self.fetch_timer.start()

        self.send_timer = QTimer(self)
        self.send_timer.setInterval(int(self.project.runtime.send_interval_s * 1000))
        self.send_timer.timeout.connect(self._auto_send_tick)

        self.reload_all()
        self.refresh_values()
        logger.info("Pixoo Studio prêt")

    # ----- UI construction -----
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: screens + elements
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Écrans"))
        self.screen_list = QListWidget()
        self.screen_list.currentItemChanged.connect(self._on_screen_sel)
        ll.addWidget(self.screen_list, 1)
        row = QHBoxLayout()
        b_add_s = QPushButton("+ Écran")
        b_del_s = QPushButton("Suppr.")
        b_del_s.setObjectName("secondary")
        b_add_s.clicked.connect(self._add_screen)
        b_del_s.clicked.connect(self._del_screen)
        row.addWidget(b_add_s)
        row.addWidget(b_del_s)
        ll.addLayout(row)
        ll.addWidget(QLabel("Éléments"))
        self.element_list = QListWidget()
        self.element_list.currentItemChanged.connect(self._on_element_sel)
        ll.addWidget(self.element_list, 1)
        erow = QHBoxLayout()
        self.el_type = QComboBox()
        for t, lab in (
            ("text", "Texte"),
            ("value", "Valeur"),
            ("bar", "Barre"),
            ("pie", "Camembert"),
            ("sparkline", "Sparkline"),
            ("status_dot", "Pastille"),
            ("pattern", "Pattern"),
            ("rect", "Rectangle"),
        ):
            self.el_type.addItem(lab, t)
        b_add_e = QPushButton("+")
        b_del_e = QPushButton("Suppr.")
        b_del_e.setObjectName("secondary")
        b_add_e.clicked.connect(self._add_element)
        b_del_e.clicked.connect(self._del_element)
        erow.addWidget(self.el_type, 1)
        erow.addWidget(b_add_e)
        erow.addWidget(b_del_e)
        ll.addLayout(erow)
        left.setMinimumWidth(240)
        splitter.addWidget(left)

        # Center: canvas
        self.canvas = PreviewCanvas(self.engine)
        splitter.addWidget(self.canvas)

        # Right: properties tabs
        right = QTabWidget()
        self.props_screen = QWidget()
        self.props_element = QWidget()
        self.props_source = QWidget()
        right.addTab(self._build_screen_props(), "Écran")
        right.addTab(self._build_element_props(), "Élément")
        right.addTab(self._build_source_props(), "Sources")
        right.addTab(self._build_status_panel(), "Status")
        right.setMinimumWidth(320)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        root.addWidget(splitter)

        # Log dock
        self.log_dock_widget = QDockWidget("Logs", self)
        self.log_view = LogDock()
        self.log_dock_widget.setWidget(self.log_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock_widget)

        # Status bar LED
        self.led = StatusLed()
        self.status_label = QLabel("Pixoo: —")
        self.statusBar().addPermanentWidget(self.led)
        self.statusBar().addPermanentWidget(self.status_label)

    def _build_screen_props(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.scr_title = QLineEdit()
        self.scr_duration = QDoubleSpinBox()
        self.scr_duration.setRange(1, 3600)
        self.scr_duration.setSuffix(" s")
        self.scr_transition = QComboBox()
        for t in ("none", "fade", "slide"):
            self.scr_transition.addItem(t, t)
        self.scr_bg = QLineEdit("#000000")
        for widget in (self.scr_title, self.scr_duration, self.scr_transition, self.scr_bg):
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._commit_screen)
            elif isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(self._commit_screen)
            else:
                widget.currentIndexChanged.connect(self._commit_screen)
        form.addRow("Titre", self.scr_title)
        form.addRow("Durée", self.scr_duration)
        form.addRow("Transition", self.scr_transition)
        form.addRow("Fond", self.scr_bg)
        return w

    def _build_element_props(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.el_x = QSpinBox(); self.el_x.setRange(0, 63)
        self.el_y = QSpinBox(); self.el_y.setRange(0, 63)
        self.el_w = QSpinBox(); self.el_w.setRange(1, 64)
        self.el_h = QSpinBox(); self.el_h.setRange(1, 64)
        self.el_text = QLineEdit()
        self.el_source = QComboBox()
        self.el_color = QLineEdit("#3CC8FF")
        self.el_overflow = QComboBox()
        self.el_overflow.addItem("clip", "clip")
        self.el_overflow.addItem("marquee", "marquee")
        self.el_period = QLineEdit("15m")
        self.el_format = QLineEdit("{v:.0f}{u}")
        for widget in (
            self.el_x, self.el_y, self.el_w, self.el_h, self.el_text,
            self.el_source, self.el_color, self.el_overflow, self.el_period, self.el_format,
        ):
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._commit_element)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._commit_element)
            else:
                widget.currentIndexChanged.connect(self._commit_element)
        form.addRow("X", self.el_x)
        form.addRow("Y", self.el_y)
        form.addRow("W", self.el_w)
        form.addRow("H", self.el_h)
        form.addRow("Texte", self.el_text)
        form.addRow("Source", self.el_source)
        form.addRow("Couleur", self.el_color)
        form.addRow("Overflow", self.el_overflow)
        form.addRow("Période", self.el_period)
        form.addRow("Format", self.el_format)
        return w

    def _build_source_props(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.source_list = QListWidget()
        self.source_list.currentItemChanged.connect(self._on_source_sel)
        layout.addWidget(self.source_list, 1)
        form = QFormLayout()
        self.src_label = QLineEdit()
        self.src_plugin = QComboBox()
        for pid, plug in self.loader.plugins.items():
            self.src_plugin.addItem(f"{plug.name} ({pid})", pid)
        self.src_plugin.currentIndexChanged.connect(self._on_plugin_changed)
        form.addRow("Nom", self.src_label)
        form.addRow("Plugin", self.src_plugin)
        layout.addLayout(form)
        self.schema_form = SchemaForm()
        self.schema_form.changed.connect(self._commit_source)
        layout.addWidget(self.schema_form, 2)
        btns = QHBoxLayout()
        b_add = QPushButton("+ Source")
        b_del = QPushButton("Suppr.")
        b_del.setObjectName("secondary")
        b_test = QPushButton("Tester")
        b_add.clicked.connect(self._add_source)
        b_del.clicked.connect(self._del_source)
        b_test.clicked.connect(self._test_source)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addWidget(b_test)
        layout.addLayout(btns)
        self.src_test_result = QLabel("—")
        self.src_test_result.setWordWrap(True)
        layout.addWidget(self.src_test_result)
        self.src_label.textChanged.connect(self._commit_source)
        return w

    def _build_status_panel(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.stat_ok = QLabel("0")
        self.stat_fail = QLabel("0")
        self.stat_uptime = QLabel("0s")
        self.stat_err = QLabel("—")
        form.addRow("Envois OK", self.stat_ok)
        form.addRow("Envois KO", self.stat_fail)
        form.addRow("Uptime", self.stat_uptime)
        form.addRow("Dernière erreur", self.stat_err)
        self.chk_autosend = QCheckBox("Auto-send activé")
        self.chk_autosend.toggled.connect(self._toggle_autosend)
        form.addRow(self.chk_autosend)
        self.send_interval = QDoubleSpinBox()
        self.send_interval.setRange(0.5, 3600)
        self.send_interval.setValue(3)
        self.send_interval.valueChanged.connect(self._on_send_interval)
        form.addRow("Intervalle send (s)", self.send_interval)
        return w

    def _build_menus(self) -> None:
        m = self.menuBar()
        file_m = m.addMenu("&Fichier")
        file_m.addAction(QAction("&Nouveau", self, shortcut=QKeySequence.StandardKey.New, triggered=self.file_new))
        file_m.addAction(QAction("&Ouvrir…", self, shortcut=QKeySequence.StandardKey.Open, triggered=self.file_open))
        file_m.addAction(QAction("&Enregistrer", self, shortcut=QKeySequence.StandardKey.Save, triggered=self.file_save))
        file_m.addAction(QAction("Enregistrer &sous…", self, shortcut=QKeySequence.StandardKey.SaveAs, triggered=self.file_save_as))
        file_m.addSeparator()
        file_m.addAction(QAction("Exporter PNG…", self, triggered=self.export_png))
        file_m.addSeparator()
        file_m.addAction(QAction("&Quitter", self, shortcut=QKeySequence.StandardKey.Quit, triggered=self.close))

        edit_m = m.addMenu("&Édition")
        edit_m.addAction(QAction("Paramètres projet…", self, triggered=self.edit_meta))
        edit_m.addAction(QAction("Dupliquer écran", self, triggered=self._dup_screen))

        prof_m = m.addMenu("&Profils")
        prof_m.addAction(QAction("Recharger projet démo", self, triggered=self._load_demo))

        help_m = m.addMenu("&Aide")
        help_m.addAction(QAction("Documentation Studio", self, triggered=self._open_docs))
        help_m.addAction(QAction("À propos", self, triggered=self._about))

    def _build_toolbar(self) -> None:
        tb = QToolBar("Principal")
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction("Nouveau", self.file_new)
        tb.addAction("Ouvrir", self.file_open)
        tb.addAction("Sauver", self.file_save)
        tb.addSeparator()
        self.act_play = tb.addAction("▶ Auto-send", lambda: self._toggle_autosend(True))
        self.act_stop = tb.addAction("■ Stop", lambda: self._toggle_autosend(False))
        tb.addAction("Push once", self.push_once)
        tb.addAction("Refresh", self.refresh_values)
        tb.addSeparator()
        tb.addAction("Zoom+", self._zoom_in)
        tb.addAction("Zoom−", self._zoom_out)

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray indisponible sur cette plateforme")
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("Pixoo Studio")
        # icône simple générée
        pix = QPixmap(32, 32)
        pix.fill(QColor("#2d6cdf"))
        self.tray.setIcon(QIcon(pix))
        menu = QMenu()
        menu.addAction("Ouvrir l'éditeur", self.showNormal)
        menu.addAction("Masquer l'éditeur", self.hide)
        menu.addSeparator()
        menu.addAction("Démarrer auto-send", lambda: self._toggle_autosend(True))
        menu.addAction("Arrêter auto-send", lambda: self._toggle_autosend(False))
        menu.addAction("Voir les logs", self.log_dock_widget.show)
        menu.addSeparator()
        menu.addAction("Quitter", QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _setup_logging(self) -> None:
        handler = QtLogHandler(self.log_view.append)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"))
        logging.getLogger("pixoo_studio").addHandler(handler)
        logging.getLogger("pixoo_studio").setLevel(logging.DEBUG)

    # ----- data / preview -----
    def current_screen(self) -> Screen | None:
        return self.project.screen_by_id(self.current_screen_id or "")

    def current_element(self):
        scr = self.current_screen()
        if not scr:
            return None
        for el in scr.elements:
            if el.id == self.current_element_id:
                return el
        return None

    def reload_all(self) -> None:
        self.send_service.project = self.project
        self.screen_list.blockSignals(True)
        self.screen_list.clear()
        for scr in self.project.screens:
            item = QListWidgetItem(f"{scr.title} ({len(scr.elements)})")
            item.setData(Qt.ItemDataRole.UserRole, scr.id)
            self.screen_list.addItem(item)
            if scr.id == self.current_screen_id:
                self.screen_list.setCurrentItem(item)
        self.screen_list.blockSignals(False)
        self._reload_elements()
        self._reload_sources()
        self._load_screen_form()
        self._load_element_form()
        self.chk_autosend.setChecked(self.project.runtime.auto_send)
        self.send_interval.setValue(self.project.runtime.send_interval_s)
        self.canvas.set_zoom(self.project.runtime.preview_zoom)
        self._update_preview()
        self.setWindowTitle(f"Pixoo Studio — {self.project.meta.name}")

    def _reload_elements(self) -> None:
        self.element_list.blockSignals(True)
        self.element_list.clear()
        scr = self.current_screen()
        if scr:
            for el in sorted(scr.elements, key=lambda e: e.z):
                item = QListWidgetItem(f"{el.type} @({el.x},{el.y})")
                item.setData(Qt.ItemDataRole.UserRole, el.id)
                self.element_list.addItem(item)
                if el.id == self.current_element_id:
                    self.element_list.setCurrentItem(item)
        self.element_list.blockSignals(False)

    def _reload_sources(self) -> None:
        self.source_list.blockSignals(True)
        self.source_list.clear()
        self.el_source.blockSignals(True)
        self.el_source.clear()
        self.el_source.addItem("—", "")
        for src in self.project.sources:
            item = QListWidgetItem(f"{src.label} [{src.plugin_id}]")
            item.setData(Qt.ItemDataRole.UserRole, src.id)
            self.source_list.addItem(item)
            self.el_source.addItem(src.label, src.id)
            if src.id == self.current_source_id:
                self.source_list.setCurrentItem(item)
        self.el_source.blockSignals(False)
        self.source_list.blockSignals(False)
        self._load_source_form()

    def refresh_values(self) -> None:
        try:
            psutil_prime()
            self.values = self.fetcher.fetch_all(self.project)
        except Exception as exc:
            logger.error("Refresh: %s", exc)
        self._update_preview()
        self._update_status_ui()

    def _on_anim_tick(self) -> None:
        self._update_preview()

    def _update_preview(self) -> None:
        scr = self.current_screen()
        if not scr:
            return
        anim_t = time.monotonic() - self._anim_t0
        # optionally show transition preview via send_service rotation index sync
        frame = self.engine.render_screen(scr, self.project, self.values, anim_t=anim_t)
        n = sum(1 for e in scr.elements if e.visible)
        self.canvas.show_image(frame, f"{scr.title} · {n} els · zoom ×{self.canvas._scale}")

    def _update_status_ui(self) -> None:
        st = self.send_service.conn.status
        self.led.set_status(st)
        self.status_label.setText(f"Pixoo: {st} · {self.project.meta.pixoo_ip}")
        self.stat_ok.setText(str(self.send_service.stats.sends_ok))
        self.stat_fail.setText(str(self.send_service.stats.sends_fail))
        self.stat_uptime.setText(f"{self.send_service.stats.uptime_s:.0f}s")
        self.stat_err.setText(self.send_service.conn.last_error or "—")

    # ----- selections / commits -----
    def _on_screen_sel(self, cur, _prev) -> None:
        if cur:
            self.current_screen_id = cur.data(Qt.ItemDataRole.UserRole)
            self.current_element_id = None
            self._reload_elements()
            self._load_screen_form()
            self._update_preview()

    def _on_element_sel(self, cur, _prev) -> None:
        if cur:
            self.current_element_id = cur.data(Qt.ItemDataRole.UserRole)
            self._load_element_form()

    def _on_source_sel(self, cur, _prev) -> None:
        if cur:
            self.current_source_id = cur.data(Qt.ItemDataRole.UserRole)
            self._load_source_form()

    def _load_screen_form(self) -> None:
        scr = self.current_screen()
        if not scr:
            return
        self.scr_title.blockSignals(True)
        self.scr_title.setText(scr.title)
        self.scr_duration.setValue(scr.duration_s)
        self.scr_transition.setCurrentIndex(max(0, self.scr_transition.findData(scr.transition)))
        self.scr_bg.setText(scr.background)
        self.scr_title.blockSignals(False)

    def _commit_screen(self, *_a) -> None:
        scr = self.current_screen()
        if not scr:
            return
        scr.title = self.scr_title.text()
        scr.duration_s = float(self.scr_duration.value())
        scr.transition = self.scr_transition.currentData()
        scr.background = self.scr_bg.text().strip() or "#000000"
        self.reload_all()

    def _load_element_form(self) -> None:
        el = self.current_element()
        if not el:
            return
        for w in (self.el_x, self.el_y, self.el_w, self.el_h, self.el_text, self.el_source, self.el_color, self.el_overflow, self.el_period, self.el_format):
            w.blockSignals(True)
        self.el_x.setValue(el.x)
        self.el_y.setValue(el.y)
        self.el_w.setValue(el.w)
        self.el_h.setValue(el.h)
        self.el_text.setText(el.text)
        self.el_source.setCurrentIndex(max(0, self.el_source.findData(el.source_id)))
        self.el_color.setText(el.color)
        self.el_overflow.setCurrentIndex(max(0, self.el_overflow.findData(el.overflow)))
        self.el_period.setText(el.period)
        self.el_format.setText(el.format)
        for w in (self.el_x, self.el_y, self.el_w, self.el_h, self.el_text, self.el_source, self.el_color, self.el_overflow, self.el_period, self.el_format):
            w.blockSignals(False)

    def _commit_element(self, *_a) -> None:
        el = self.current_element()
        if not el:
            return
        el.x = self.el_x.value()
        el.y = self.el_y.value()
        el.w = self.el_w.value()
        el.h = self.el_h.value()
        el.text = self.el_text.text()
        el.source_id = self.el_source.currentData() or ""
        el.color = self.el_color.text().strip() or "#FFFFFF"
        el.overflow = self.el_overflow.currentData()
        el.period = self.el_period.text().strip() or "15m"
        el.format = self.el_format.text()
        self.engine.cache.clear()
        self._reload_elements()
        self._update_preview()

    def _load_source_form(self) -> None:
        src = self.project.source_by_id(self.current_source_id or "")
        if not src:
            return
        self.src_label.blockSignals(True)
        self.src_plugin.blockSignals(True)
        self.src_label.setText(src.label)
        self.src_plugin.setCurrentIndex(max(0, self.src_plugin.findData(src.plugin_id)))
        self.src_label.blockSignals(False)
        self.src_plugin.blockSignals(False)
        plug = self.loader.get(src.plugin_id)
        if plug:
            self.schema_form.build(plug.get_config_schema(), src.config)

    def _on_plugin_changed(self, *_a) -> None:
        src = self.project.source_by_id(self.current_source_id or "")
        if not src:
            return
        src.plugin_id = self.src_plugin.currentData()
        plug = self.loader.get(src.plugin_id)
        if plug:
            defaults = {k: p.get("default") for k, p in (plug.get_config_schema().get("properties") or {}).items()}
            src.config = {k: v for k, v in defaults.items() if v is not None}
            self.schema_form.build(plug.get_config_schema(), src.config)
        self._reload_sources()

    def _commit_source(self, *_a) -> None:
        src = self.project.source_by_id(self.current_source_id or "")
        if not src:
            return
        src.label = self.src_label.text()
        src.plugin_id = self.src_plugin.currentData()
        src.config = self.schema_form.values()
        self._reload_sources()

    # ----- CRUD -----
    def _add_screen(self) -> None:
        scr = Screen(id=new_id("scr"), title=f"Screen {len(self.project.screens)+1}")
        scr.elements.append(new_element("text", text=scr.title))
        self.project.screens.append(scr)
        self.current_screen_id = scr.id
        self.reload_all()

    def _del_screen(self) -> None:
        if len(self.project.screens) <= 1:
            QMessageBox.information(self, "Écrans", "Garde au moins un écran.")
            return
        self.project.screens = [s for s in self.project.screens if s.id != self.current_screen_id]
        self.current_screen_id = self.project.screens[0].id
        self.reload_all()

    def _dup_screen(self) -> None:
        scr = self.current_screen()
        if not scr:
            return
        data = scr.to_dict()
        data["id"] = new_id("scr")
        data["title"] = scr.title + " copy"
        for el in data.get("elements") or []:
            el["id"] = new_id("el")
        clone = Screen.from_dict(data)
        self.project.screens.append(clone)
        self.current_screen_id = clone.id
        self.reload_all()

    def _add_element(self) -> None:
        scr = self.current_screen()
        if not scr:
            return
        el = new_element(self.el_type.currentData())
        if self.project.sources and el.type in ("value", "bar", "pie", "sparkline", "status_dot"):
            el.source_id = self.project.sources[0].id
        scr.elements.append(el)
        self.current_element_id = el.id
        self.reload_all()

    def _del_element(self) -> None:
        scr = self.current_screen()
        if not scr or not self.current_element_id:
            return
        scr.elements = [e for e in scr.elements if e.id != self.current_element_id]
        self.current_element_id = None
        self.reload_all()

    def _add_source(self) -> None:
        src = DataSourceDef(id=new_id("src"), label="Nouvelle source", plugin_id="builtin_psutil", config={"key": "cpu"})
        self.project.sources.append(src)
        self.current_source_id = src.id
        self.reload_all()

    def _del_source(self) -> None:
        if not self.current_source_id:
            return
        self.project.sources = [s for s in self.project.sources if s.id != self.current_source_id]
        self.current_source_id = self.project.sources[0].id if self.project.sources else None
        self.reload_all()

    def _test_source(self) -> None:
        src = self.project.source_by_id(self.current_source_id or "")
        if not src:
            return
        plug = self.loader.get(src.plugin_id)
        if not plug:
            self.src_test_result.setText("Plugin introuvable")
            return
        try:
            if not plug.validate_config(src.config):
                self.src_test_result.setText("Config invalide")
                return
            val = plug.fetch_data(src.config)
            self.src_test_result.setText(f"OK → {val!r}")
            logger.info("Test source %s = %r", src.id, val)
        except Exception as exc:
            self.src_test_result.setText(f"Erreur: {exc}")
            logger.error("Test source: %s", exc)

    # ----- runtime -----
    def _toggle_autosend(self, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = self.chk_autosend.isChecked()
        else:
            self.chk_autosend.blockSignals(True)
            self.chk_autosend.setChecked(bool(enabled))
            self.chk_autosend.blockSignals(False)
        self.project.runtime.auto_send = bool(enabled)
        if enabled:
            self.send_timer.start()
            logger.info("Auto-send démarré (%ss)", self.project.runtime.send_interval_s)
            if self.tray:
                self.tray.showMessage("Pixoo Studio", "Auto-send démarré", QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            self.send_timer.stop()
            logger.info("Auto-send arrêté")

    def _on_send_interval(self, value: float) -> None:
        self.project.runtime.send_interval_s = float(value)
        self.send_timer.setInterval(int(value * 1000))

    def _auto_send_tick(self) -> None:
        if not self.project.runtime.auto_send:
            return
        anim_t = time.monotonic() - self._anim_t0
        self.send_service.push_once(anim_t=anim_t)
        self._update_status_ui()

    def _zoom_in(self) -> None:
        self.canvas.set_zoom(self.canvas._scale + 1)
        self.project.runtime.preview_zoom = self.canvas._scale
        self._update_preview()

    def _zoom_out(self) -> None:
        self.canvas.set_zoom(self.canvas._scale - 1)
        self.project.runtime.preview_zoom = self.canvas._scale
        self._update_preview()

    def push_once(self) -> None:
        ok = self.send_service.push_once(anim_t=time.monotonic() - self._anim_t0)
        self._update_status_ui()
        self.statusBar().showMessage("Push OK" if ok else "Push échoué / backoff", 3000)

    # ----- files -----
    def file_new(self) -> None:
        self.project = Project(meta=ProjectMeta(name="Untitled"))
        self.project.screens = [Screen(id=new_id("scr"), title="Screen 1")]
        self.project.screens[0].elements.append(new_element("text", text="Screen 1"))
        self.path = None
        self.current_screen_id = self.project.screens[0].id
        self.engine.cache.clear()
        self.reload_all()

    def _load_demo(self) -> None:
        self.project = default_project()
        self.path = None
        self.current_screen_id = self.project.screens[0].id
        self.engine.cache.clear()
        self.reload_all()

    def file_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir projet", str(ROOT / "projects"), "Pixoo Studio (*.pixoo *.json)"
        )
        if not path:
            return
        try:
            self.project = ProjectStore.load(path)
            self.path = Path(path)
            self.current_screen_id = self.project.screens[0].id if self.project.screens else None
            self.engine.cache.clear()
            self.engine.fonts.preload()
            self.reload_all()
            self.refresh_values()
            logger.info("Ouvert %s", path)
        except Exception as exc:
            QMessageBox.critical(self, "Ouverture", str(exc))

    def file_save(self) -> None:
        if not self.path:
            self.file_save_as()
            return
        try:
            ProjectStore.save(self.project, self.path)
            self.statusBar().showMessage(f"Enregistré {self.path}", 3000)
            logger.info("Sauvé %s", self.path)
        except Exception as exc:
            QMessageBox.critical(self, "Enregistrement", str(exc))

    def file_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer sous",
            str(ROOT / "projects" / f"{self.project.meta.name.replace(' ', '_').lower()}.pixoo"),
            "Pixoo Studio (*.pixoo)",
        )
        if not path:
            return
        self.path = Path(path if path.endswith(".pixoo") else path + ".pixoo")
        self.file_save()

    def export_png(self) -> None:
        scr = self.current_screen()
        if not scr:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter PNG", str(ROOT / "assets" / f"{scr.id}.png"), "PNG (*.png)")
        if not path:
            return
        anim_t = time.monotonic() - self._anim_t0
        img = self.engine.scale_preview(
            self.engine.render_screen(scr, self.project, self.values, anim_t=anim_t),
            self.canvas._scale,
        )
        img.save(path)
        logger.info("PNG exporté %s", path)

    def edit_meta(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Paramètres projet")
        form = QFormLayout(dlg)
        name = QLineEdit(self.project.meta.name)
        ip = QLineEdit(self.project.meta.pixoo_ip)
        bright = QSpinBox(); bright.setRange(0, 100); bright.setValue(self.project.meta.brightness)
        fps = QSpinBox(); fps.setRange(5, 60); fps.setValue(self.project.meta.ui_fps)
        form.addRow("Nom", name)
        form.addRow("IP Pixoo", ip)
        form.addRow("Luminosité", bright)
        form.addRow("UI FPS", fps)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.project.meta.name = name.text().strip() or "Untitled"
            self.project.meta.pixoo_ip = ip.text().strip()
            self.project.meta.brightness = int(bright.value())
            self.project.meta.ui_fps = int(fps.value())
            self.anim_timer.setInterval(max(33, int(1000 / max(1, self.project.meta.ui_fps))))
            self.reload_all()

    def _open_docs(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        doc = ROOT / "docs" / "STUDIO.md"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(doc)))

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "À propos",
            "Pixoo Studio\n\n"
            "Studio graphique professionnel pour Divoom Pixoo 64.\n"
            "Plugins de données · animations · auto-send · system tray.",
        )

    def closeEvent(self, event) -> None:
        if self.tray and self.tray.isVisible():
            self.hide()
            event.ignore()
            if not getattr(self, "_tray_hint", False):
                self.tray.showMessage("Pixoo Studio", "Toujours actif dans la barre système", QSystemTrayIcon.MessageIcon.Information, 2000)
                self._tray_hint = True
        else:
            event.accept()


def psutil_prime() -> None:
    try:
        import psutil

        psutil.cpu_percent(interval=None)
    except Exception:
        pass
