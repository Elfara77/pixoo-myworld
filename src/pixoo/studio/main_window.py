"""Studio main window — edit projects, preview locally, sync with engine."""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pixoo.common.config_manager import ConfigManager, ConfigError
from pixoo.common.models import Project, Screen, default_project
from pixoo.engine.data_fetcher import DataFetcher
from pixoo.engine.renderer import Renderer
from pixoo.plugins.base import get_registry
from pixoo.studio.canvas import CanvasWidget
from pixoo.studio.plugin_config_wizard import PluginConfigWizard
from pixoo.studio.plugin_manager import PluginManagerWidget
from pixoo.studio.properties_panel import PropertiesPanel
from pixoo.studio.sync_client import SyncClient, VersionMismatchError
from pixoo.studio.template_manager import TemplateManager
logger = logging.getLogger("pixoo.studio")
ROOT = Path(__file__).resolve().parents[3]


def _new_id(prefix: str = "el") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class MainWindow(QMainWindow):
    def __init__(self, project_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Pixoo Studio")
        self.resize(1280, 800)

        self.path: Path | None = project_path
        self.project: Project = (
            ConfigManager.load(project_path) if project_path and project_path.exists() else default_project()
        )
        self.renderer = Renderer()
        self.registry = get_registry()
        self.fetcher = DataFetcher(self.registry, persist_cache=False)
        self.templates = TemplateManager()
        self.sync = SyncClient(
            f"http://{self.project.runtime.api_host}:{self.project.runtime.api_port}"
        )
        self.values: dict[str, Any] = {}
        self.current_screen_id: str | None = self.project.screens[0].id if self.project.screens else None
        self.current_element_id: str | None = None
        self._anim_t0 = time.monotonic()
        self._engine_owned = False

        self._build_ui()
        self._build_toolbar()
        self._build_menus()
        self._build_sources_dock()
        self.setStatusBar(QStatusBar())
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(max(33, int(1000 / max(5, self.project.runtime.ui_fps))))
        self.anim_timer.timeout.connect(self._refresh_preview)
        self.anim_timer.start()

        self.fetch_timer = QTimer(self)
        self.fetch_timer.setInterval(1000)
        self.fetch_timer.timeout.connect(self._fetch_local)
        self.fetch_timer.start()

        self.reload_lists()
        self._fetch_local()
        self._refresh_preview()
        if self.path:
            self.statusBar().showMessage(f"Loaded {self.path}", 4000)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Screens"))
        self.screen_list = QListWidget()
        self.screen_list.currentItemChanged.connect(self._on_screen_sel)
        ll.addWidget(self.screen_list, 1)
        row_s = QHBoxLayout()
        b_add_s = QPushButton("+ Screen")
        b_del_s = QPushButton("Del")
        b_add_s.clicked.connect(self._add_screen)
        b_del_s.clicked.connect(self._del_screen)
        row_s.addWidget(b_add_s)
        row_s.addWidget(b_del_s)
        ll.addLayout(row_s)

        ll.addWidget(QLabel("Elements"))
        self.element_list = QListWidget()
        self.element_list.currentItemChanged.connect(self._on_element_sel)
        ll.addWidget(self.element_list, 1)
        row_e = QHBoxLayout()
        self.add_type = QComboBox()
        for t in ("text", "gauge", "graph", "image"):
            self.add_type.addItem(t)
        b_add_e = QPushButton("+")
        b_del_e = QPushButton("Del")
        b_add_e.clicked.connect(self._add_element)
        b_del_e.clicked.connect(self._del_element)
        row_e.addWidget(self.add_type, 1)
        row_e.addWidget(b_add_e)
        row_e.addWidget(b_del_e)
        ll.addLayout(row_e)
        splitter.addWidget(left)

        center = QWidget()
        cl = QVBoxLayout(center)
        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel("Pixoo IP"))
        self.ip_edit = QLineEdit(self.project.meta.pixoo_ip)
        self.ip_edit.textChanged.connect(self._on_ip)
        meta_row.addWidget(self.ip_edit)
        meta_row.addWidget(QLabel("Bright"))
        self.bright = QSpinBox()
        self.bright.setRange(0, 100)
        self.bright.setValue(self.project.meta.brightness)
        self.bright.valueChanged.connect(self._on_bright)
        meta_row.addWidget(self.bright)
        self.grid_cb = QCheckBox("Grid")
        self.grid_cb.setChecked(True)
        meta_row.addWidget(self.grid_cb)
        cl.addLayout(meta_row)
        self.canvas = CanvasWidget()
        self.canvas.elementSelected.connect(self._select_element)
        self.canvas.elementMoved.connect(self._on_moved)
        self.grid_cb.toggled.connect(self.canvas.set_grid)
        cl.addWidget(self.canvas, 1)
        splitter.addWidget(center)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Properties"))
        self.props = PropertiesPanel()
        self.props.changed.connect(self._on_props)
        rl.addWidget(self.props)
        rl.addWidget(QLabel("Plugin inspector"))
        self.plugin_mgr = PluginManagerWidget()
        rl.addWidget(self.plugin_mgr, 1)
        sync_row = QHBoxLayout()
        self.btn_engine = QPushButton("Start engine")
        self.btn_push = QPushButton("Push config")
        self.btn_engine.clicked.connect(self._start_engine)
        self.btn_push.clicked.connect(self._push_config)
        sync_row.addWidget(self.btn_engine)
        sync_row.addWidget(self.btn_push)
        rl.addLayout(sync_row)
        self.sync_label = QLabel("Engine: offline")
        rl.addWidget(self.sync_label)
        splitter.addWidget(right)

        splitter.setSizes([240, 640, 320])
        root.addWidget(splitter)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        self.addToolBar(tb)
        act_new = QAction("New", self)
        act_open = QAction("Open", self)
        act_save = QAction("Save", self)
        act_save_as = QAction("Save as", self)
        act_new.triggered.connect(self._new)
        act_open.triggered.connect(self._open)
        act_save.triggered.connect(self._save)
        act_save_as.triggered.connect(self._save_as)
        for a in (act_new, act_open, act_save, act_save_as):
            tb.addAction(a)

    def _build_menus(self) -> None:
        m = self.menuBar().addMenu("&File")
        for text, slot, shortcut in (
            ("New", self._new, QKeySequence.StandardKey.New),
            ("Open…", self._open, QKeySequence.StandardKey.Open),
            ("Save", self._save, QKeySequence.StandardKey.Save),
            ("Save as…", self._save_as, QKeySequence.StandardKey.SaveAs),
            ("Quit", self.close, QKeySequence.StandardKey.Quit),
        ):
            act = QAction(text, self)
            act.triggered.connect(slot)
            act.setShortcut(shortcut)
            m.addAction(act)
        src = self.menuBar().addMenu("&Sources")
        act_add = QAction("Add source…", self)
        act_add.triggered.connect(self._wizard_source)
        src.addAction(act_add)
        tpl = self.menuBar().addMenu("&Templates")
        for info in self.templates.list_templates():
            act = QAction(info["name"], self)
            tid = info["id"]
            act.triggered.connect(lambda _=False, i=tid: self._import_template(i))
            tpl.addAction(act)

    def _build_sources_dock(self) -> None:
        dock = QDockWidget("Sources", self)
        self.sources_list = QListWidget()
        dock.setWidget(self.sources_list)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        row = QWidget()
        hl = QHBoxLayout(row)
        b_add = QPushButton("Add…")
        b_add.clicked.connect(self._wizard_source)
        hl.addWidget(b_add)
        # keep button accessible via menu; dock shows status
        self._refresh_sources_dock()

    # --------------------------------------------------------------- helpers
    def current_screen(self) -> Screen | None:
        if not self.current_screen_id:
            return None
        for s in self.project.screens:
            if s.id == self.current_screen_id:
                return s
        return None

    def current_element(self) -> dict[str, Any] | None:
        scr = self.current_screen()
        if not scr or not self.current_element_id:
            return None
        for el in scr.elements:
            if el.get("id") == self.current_element_id:
                return el
        return None

    def reload_lists(self) -> None:
        self.screen_list.blockSignals(True)
        self.screen_list.clear()
        for s in self.project.screens:
            item = QListWidgetItem(s.title or s.id)
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self.screen_list.addItem(item)
            if s.id == self.current_screen_id:
                self.screen_list.setCurrentItem(item)
        self.screen_list.blockSignals(False)
        self._reload_elements()

    def _reload_elements(self) -> None:
        self.element_list.blockSignals(True)
        self.element_list.clear()
        scr = self.current_screen()
        if scr:
            for el in scr.elements:
                label = f"{el.get('type')} · {el.get('id')}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, el.get("id"))
                self.element_list.addItem(item)
                if el.get("id") == self.current_element_id:
                    self.element_list.setCurrentItem(item)
        self.element_list.blockSignals(False)
        self.props.bind(self.current_element())

    # ---------------------------------------------------------------- events
    def _on_screen_sel(self, cur: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if not cur:
            return
        self.current_screen_id = cur.data(Qt.ItemDataRole.UserRole)
        self.current_element_id = None
        self._reload_elements()
        self._refresh_preview()

    def _on_element_sel(self, cur: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if not cur:
            return
        self._select_element(str(cur.data(Qt.ItemDataRole.UserRole)))

    def _select_element(self, eid: str) -> None:
        self.current_element_id = eid
        for i in range(self.element_list.count()):
            item = self.element_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == eid:
                self.element_list.blockSignals(True)
                self.element_list.setCurrentItem(item)
                self.element_list.blockSignals(False)
                break
        self.props.bind(self.current_element())
        self._refresh_preview()

    def _on_moved(self, eid: str, x: int, y: int) -> None:
        el = self.current_element() if self.current_element_id == eid else None
        if el is None:
            scr = self.current_screen()
            if scr:
                el = next((e for e in scr.elements if e.get("id") == eid), None)
        if el:
            el["x"], el["y"] = x, y
            if self.current_element_id == eid:
                self.props.bind(el)

    def _on_props(self) -> None:
        self._reload_elements()
        self._refresh_preview()

    def _on_ip(self, text: str) -> None:
        self.project.meta.pixoo_ip = text.strip()

    def _on_bright(self, v: int) -> None:
        self.project.meta.brightness = v

    def _add_screen(self) -> None:
        sid = _new_id("scr")
        self.project.screens.append(Screen(id=sid, title=f"Screen {len(self.project.screens)+1}"))
        self.current_screen_id = sid
        self.reload_lists()

    def _del_screen(self) -> None:
        if len(self.project.screens) <= 1:
            return
        self.project.screens = [s for s in self.project.screens if s.id != self.current_screen_id]
        self.current_screen_id = self.project.screens[0].id
        self.reload_lists()

    def _add_element(self) -> None:
        scr = self.current_screen()
        if not scr:
            return
        kind = self.add_type.currentText()
        eid = _new_id(kind[:2])
        base: dict[str, Any] = {"id": eid, "type": kind, "x": 4, "y": 4, "visible": True}
        if kind == "text":
            base.update({"content": "Text", "color": "#FFFFFF", "w": 56, "h": 10, "animation": "none"})
        elif kind == "gauge":
            base.update({"source": "system.cpu", "w": 56, "h": 8, "color": "#28DC64", "style": "bar"})
        elif kind == "graph":
            base.update({"source": "system.cpu", "w": 56, "h": 16, "color": "#3CC8FF"})
        elif kind == "image":
            base.update({"path": "", "w": 16, "h": 16})
        scr.elements.append(base)
        self.current_element_id = eid
        self._reload_elements()
        self._refresh_preview()

    def _del_element(self) -> None:
        scr = self.current_screen()
        if not scr or not self.current_element_id:
            return
        scr.elements = [e for e in scr.elements if e.get("id") != self.current_element_id]
        self.current_element_id = None
        self._reload_elements()
        self._refresh_preview()

    # ----------------------------------------------------------- data / draw
    def _fetch_local(self) -> None:
        try:
            self.values = self.fetcher.fetch_all(self.project)
            for sid, val in self.values.items():
                if isinstance(val, (int, float)) and not isinstance(val, bool) and "." not in sid:
                    if any(s.id == sid for s in self.project.sources):
                        hist = self.project.history.setdefault(sid, [])
                        hist.append(float(val))
                        if len(hist) > 200:
                            del hist[:-200]
        except Exception as exc:
            logger.debug("fetch_all: %s", exc)
        online = self.sync.is_reachable()
        self.sync_label.setText("Engine: online" if online else "Engine: offline")
        self._refresh_sources_dock()

    def _refresh_sources_dock(self) -> None:
        if not hasattr(self, "sources_list"):
            return
        self.sources_list.clear()
        stats = self.fetcher.stats_snapshot()
        for src in self.project.sources:
            st = stats.get(src.id) or {}
            ok = st.get("last_error") in (None, "")
            led = "●" if ok and st else "○"
            color_hint = "OK" if ok else "ERR"
            ms = st.get("last_ms")
            ms_s = f"{ms:.0f}ms" if isinstance(ms, (int, float)) else "—"
            err = st.get("last_error") or ""
            item = QListWidgetItem(f"{led} {src.id} [{src.plugin}] {color_hint} {ms_s} {err}")
            self.sources_list.addItem(item)

    def _wizard_source(self) -> None:
        dlg = PluginConfigWizard(self)
        if dlg.exec() and dlg.result_source():
            src = dlg.result_source()
            assert src is not None
            self.project.sources = [s for s in self.project.sources if s.id != src.id] + [src]
            self._refresh_sources_dock()
            self.statusBar().showMessage(f"Added source {src.id}", 3000)

    def _import_template(self, template_id: str) -> None:
        try:
            self.templates.apply_to_project(self.project, template_id, replace_screens=False)
            self.current_screen_id = self.project.screens[-1].id if self.project.screens else None
            self.reload_lists()
            self._refresh_sources_dock()
            self.statusBar().showMessage(f"Imported template {template_id}", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Template", str(exc))

    def _refresh_preview(self) -> None:
        scr = self.current_screen()
        if not scr:
            return
        anim_t = time.monotonic() - self._anim_t0
        frame = self.renderer.render(scr, self.project, self.values, anim_t=anim_t)
        self.canvas.set_frame(frame, list(scr.elements), self.current_element_id)

    # ----------------------------------------------------------- file / sync
    def _new(self) -> None:
        self.project = default_project()
        self.path = None
        self.current_screen_id = self.project.screens[0].id
        self.current_element_id = None
        self.ip_edit.setText(self.project.meta.pixoo_ip)
        self.bright.setValue(self.project.meta.brightness)
        self.reload_lists()

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open project", str(ROOT / "projects"), "Pixoo (*.pixoo)")
        if not path:
            return
        try:
            self.project = ConfigManager.load(path)
        except ConfigError as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self.path = Path(path)
        self.current_screen_id = self.project.screens[0].id if self.project.screens else None
        self.current_element_id = None
        self.ip_edit.setText(self.project.meta.pixoo_ip)
        self.bright.setValue(self.project.meta.brightness)
        self.reload_lists()

    def _save(self) -> None:
        if not self.path:
            self._save_as()
            return
        ConfigManager.save(self.project, self.path)
        self.statusBar().showMessage(f"Saved {self.path}", 3000)

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", str(ROOT / "projects" / "untitled.pixoo"), "Pixoo (*.pixoo)")
        if not path:
            return
        self.path = ConfigManager.save(self.project, path)
        self.statusBar().showMessage(f"Saved {self.path}", 3000)

    def _start_engine(self) -> None:
        if not self.path:
            self._save_as()
            if not self.path:
                return
        else:
            ConfigManager.save(self.project, self.path)
        ok = self.sync.start_engine(self.path, host=self.project.runtime.api_host, port=self.project.runtime.api_port)
        self._engine_owned = ok
        if ok:
            try:
                self.sync.check_version()
                self.statusBar().showMessage("Engine started", 4000)
            except VersionMismatchError as exc:
                QMessageBox.warning(self, "Version mismatch", str(exc))
        else:
            QMessageBox.warning(self, "Engine", "Could not start or reach the engine API.")

    def _push_config(self) -> None:
        try:
            resp = self.sync.push_config(self.project.model_dump(mode="json"))
            if not resp.get("accepted", True):
                QMessageBox.warning(self, "Push rejected", str(resp.get("message")))
            else:
                self.statusBar().showMessage("Config pushed to engine", 3000)
        except VersionMismatchError as exc:
            QMessageBox.warning(self, "Version mismatch", str(exc))
        except Exception as exc:
            QMessageBox.warning(self, "Push failed", str(exc))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._engine_owned:
            self.sync.shutdown_engine()
        try:
            self.fetcher.close()
        except Exception:
            pass
        super().closeEvent(event)
