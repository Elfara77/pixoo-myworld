"""Fenêtre principale du Pixoo Designer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .datasources import resolve_all, resolve_source
from .model import Project, Screen, default_project, new_element, _nid
from .widgets import (
    ElementListPanel,
    InspectorPanel,
    PreviewWidget,
    ScreenListPanel,
    SourceEditorPanel,
)

ROOT = Path(__file__).resolve().parents[2]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pixoo 64 Designer")
        self.resize(1280, 820)

        self.project = default_project()
        self.path: Path | None = None
        self.current_screen_id: str | None = self.project.screens[0].id if self.project.screens else None
        self.current_element_id: str | None = None
        self.values: dict = {}

        self.preview = PreviewWidget()
        self.screens_panel = ScreenListPanel()
        self.elements_panel = ElementListPanel()
        self.inspector = InspectorPanel()
        self.sources_panel = SourceEditorPanel()

        center = QWidget()
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        design = QWidget()
        dl = QHBoxLayout(design)
        left = QVBoxLayout()
        left.addWidget(self.screens_panel, 1)
        left.addWidget(self.elements_panel, 1)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(280)
        dl.addWidget(left_w)
        dl.addWidget(self.preview, 1)
        dl.addWidget(self.inspector, 1)
        self.tabs.addTab(design, "Design")
        self.tabs.addTab(self.sources_panel, "Sources de données")
        cl.addWidget(self.tabs)
        self.setCentralWidget(center)

        self._build_menus()
        self._build_toolbar()
        self.statusBar().showMessage("Prêt — projet démo chargé")

        # signals
        self.screens_panel.screenSelected.connect(self._select_screen)
        self.screens_panel.addRequested.connect(self._add_screen)
        self.screens_panel.removeRequested.connect(self._remove_screen)
        self.screens_panel.duplicateRequested.connect(self._dup_screen)
        self.elements_panel.elementSelected.connect(self._select_element)
        self.elements_panel.addRequested.connect(self._add_element)
        self.elements_panel.removeRequested.connect(self._remove_element)
        self.elements_panel.moveRequested.connect(self._move_element)
        self.inspector.changed.connect(self._on_changed)
        self.sources_panel.changed.connect(self._on_changed)
        self.sources_panel.testRequested.connect(self._test_source)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(2000)
        self.refresh_timer.timeout.connect(self.refresh_values)
        self.refresh_timer.start()

        self.reload_all()
        self.refresh_values()

    # --- UI chrome ---
    def _build_menus(self) -> None:
        m = self.menuBar()
        file_m = m.addMenu("&Fichier")
        act_new = QAction("&Nouveau", self, shortcut=QKeySequence.StandardKey.New, triggered=self.file_new)
        act_open = QAction("&Ouvrir…", self, shortcut=QKeySequence.StandardKey.Open, triggered=self.file_open)
        act_save = QAction("&Enregistrer", self, shortcut=QKeySequence.StandardKey.Save, triggered=self.file_save)
        act_save_as = QAction("Enregistrer &sous…", self, shortcut=QKeySequence.StandardKey.SaveAs, triggered=self.file_save_as)
        act_export = QAction("Exporter aperçu PNG…", self, triggered=self.export_png)
        act_quit = QAction("&Quitter", self, shortcut=QKeySequence.StandardKey.Quit, triggered=self.close)
        for a in (act_new, act_open, act_save, act_save_as, act_export, act_quit):
            file_m.addAction(a)
            if a is act_save_as:
                file_m.addSeparator()

        view_m = m.addMenu("&Affichage")
        for scale, label in ((6, "Zoom ×6"), (8, "Zoom ×8"), (10, "Zoom ×10")):
            view_m.addAction(label, lambda s=scale: self._set_zoom(s))
        view_m.addAction("Rafraîchir valeurs", self.refresh_values)

        tools_m = m.addMenu("&Outils")
        tools_m.addAction("Paramètres projet…", self.edit_meta)
        tools_m.addAction("Pousser écran courant → Pixoo", self.push_pixoo)
        tools_m.addAction("Réinitialiser projet démo", self._load_demo)

        help_m = m.addMenu("&Aide")
        help_m.addAction("À propos", self._about)
        help_m.addAction("Ouvrir documentation Designer", self._open_docs)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Principal")
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction("Nouveau", self.file_new)
        tb.addAction("Ouvrir", self.file_open)
        tb.addAction("Sauver", self.file_save)
        tb.addSeparator()
        tb.addAction("Rafraîchir", self.refresh_values)
        tb.addAction("Paramètres", self.edit_meta)
        tb.addAction("→ Pixoo", self.push_pixoo)
        tb.addSeparator()
        tb.addAction("Zoom +", lambda: self._set_zoom(self.preview._scale + 1))
        tb.addAction("Zoom −", lambda: self._set_zoom(self.preview._scale - 1))

    # --- project ops ---
    def current_screen(self) -> Screen | None:
        return self.project.screen_by_id(self.current_screen_id or "")

    def current_element(self):
        scr = self.current_screen()
        if not scr or not self.current_element_id:
            return None
        for el in scr.elements:
            if el.id == self.current_element_id:
                return el
        return None

    def reload_all(self) -> None:
        self.screens_panel.reload(self.project, self.current_screen_id)
        scr = self.current_screen()
        self.elements_panel.reload(scr, self.current_element_id)
        self.inspector.bind(self.project, scr, self.current_element())
        self.sources_panel.reload(self.project)
        self._update_preview()
        name = self.project.meta.name
        dirty = "" if self.path else " •"
        self.setWindowTitle(f"Pixoo 64 Designer — {name}{dirty}")

    def refresh_values(self) -> None:
        self.values = resolve_all(self.project.sources)
        # append history preview lightly
        for sid, val in self.values.items():
            if val is None:
                continue
            hist = self.project.history_preview.setdefault(sid, [])
            hist.append(float(val))
            if len(hist) > 120:
                del hist[:-120]
        self._update_preview()
        n_ok = sum(1 for v in self.values.values() if v is not None)
        self.statusBar().showMessage(
            f"Sources OK {n_ok}/{len(self.project.sources)}  ·  "
            f"écran {self.current_screen().title if self.current_screen() else '—'}"
        )

    def _update_preview(self) -> None:
        self.preview.show_screen(self.current_screen(), self.project, self.values)

    def _on_changed(self) -> None:
        self.screens_panel.reload(self.project, self.current_screen_id)
        self.elements_panel.reload(self.current_screen(), self.current_element_id)
        self._update_preview()

    def _select_screen(self, sid: str) -> None:
        self.current_screen_id = sid
        self.current_element_id = None
        self.reload_all()

    def _select_element(self, eid: str) -> None:
        self.current_element_id = eid
        self.inspector.bind(self.project, self.current_screen(), self.current_element())
        self._update_preview()

    def _add_screen(self) -> None:
        scr = Screen(id=_nid("scr"), title=f"Screen {len(self.project.screens) + 1}")
        scr.elements.append(new_element("text", text=scr.title, color="#3CC8FF"))
        self.project.screens.append(scr)
        self.current_screen_id = scr.id
        self.reload_all()

    def _remove_screen(self) -> None:
        if not self.current_screen_id or len(self.project.screens) <= 1:
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
        data["id"] = _nid("scr")
        data["title"] = scr.title + " copy"
        for el in data.get("elements") or []:
            el["id"] = _nid("el")
        clone = Screen.from_dict(data)
        self.project.screens.append(clone)
        self.current_screen_id = clone.id
        self.reload_all()

    def _add_element(self, etype: str) -> None:
        scr = self.current_screen()
        if not scr:
            return
        el = new_element(etype)  # type: ignore[arg-type]
        if self.project.sources and etype in ("value", "bar", "pie", "sparkline", "status_dot"):
            el.source_id = self.project.sources[0].id
        scr.elements.append(el)
        self.current_element_id = el.id
        self.reload_all()

    def _remove_element(self) -> None:
        scr = self.current_screen()
        if not scr or not self.current_element_id:
            return
        scr.elements = [e for e in scr.elements if e.id != self.current_element_id]
        self.current_element_id = None
        self.reload_all()

    def _move_element(self, delta: int) -> None:
        scr = self.current_screen()
        if not scr or not self.current_element_id:
            return
        ids = [e.id for e in scr.elements]
        try:
            i = ids.index(self.current_element_id)
        except ValueError:
            return
        j = i + delta
        if j < 0 or j >= len(scr.elements):
            return
        scr.elements[i], scr.elements[j] = scr.elements[j], scr.elements[i]
        self.reload_all()

    def _set_zoom(self, scale: int) -> None:
        self.preview.set_scale(scale)
        self._update_preview()

    def _test_source(self) -> None:
        src = self.sources_panel.current_source()
        if not src:
            return
        val, detail = resolve_source(src)
        self.sources_panel.set_test_result(f"valeur={val!r}  |  {detail}")
        self.refresh_values()

    # --- file ---
    def edit_meta(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Paramètres projet")
        form = QFormLayout(dlg)
        name = QLineEdit(self.project.meta.name)
        ip = QLineEdit(self.project.meta.pixoo_ip)
        bright = QSpinBox()
        bright.setRange(0, 100)
        bright.setValue(int(self.project.meta.brightness))
        notes = QLineEdit(self.project.meta.notes)
        form.addRow("Nom", name)
        form.addRow("IP Pixoo", ip)
        form.addRow("Luminosité", bright)
        form.addRow("Notes", notes)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        form.addRow(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.project.meta.name = name.text().strip() or "Untitled"
            self.project.meta.pixoo_ip = ip.text().strip()
            self.project.meta.brightness = int(bright.value())
            self.project.meta.notes = notes.text()
            self.reload_all()

    def file_new(self) -> None:
        from .model import ProjectMeta

        self.project = Project(meta=ProjectMeta(name="Untitled"))
        self.project.screens = [Screen(id=_nid("scr"), title="Screen 1")]
        self.project.screens[0].elements.append(new_element("text", text="Screen 1"))
        self.path = None
        self.current_screen_id = self.project.screens[0].id
        self.reload_all()

    def _load_demo(self) -> None:
        self.project = default_project()
        self.path = None
        self.current_screen_id = self.project.screens[0].id
        self.reload_all()

    def file_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir projet", str(ROOT / "projects"), "Pixoo Designer (*.pixoo.json *.json)"
        )
        if not path:
            return
        try:
            self.project = Project.load(path)
            self.path = Path(path)
            self.current_screen_id = self.project.screens[0].id if self.project.screens else None
            self.reload_all()
            self.refresh_values()
        except Exception as exc:
            QMessageBox.critical(self, "Ouverture", str(exc))

    def file_save(self) -> None:
        if not self.path:
            self.file_save_as()
            return
        try:
            self.project.save(self.path)
            self.statusBar().showMessage(f"Enregistré {self.path}")
            self.setWindowTitle(f"Pixoo 64 Designer — {self.project.meta.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Enregistrement", str(exc))

    def file_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer projet",
            str(ROOT / "projects" / f"{self.project.meta.name.replace(' ', '_').lower()}.pixoo.json"),
            "Pixoo Designer (*.pixoo.json)",
        )
        if not path:
            return
        if not path.endswith(".json"):
            path += ".pixoo.json"
        self.path = Path(path)
        self.file_save()

    def export_png(self) -> None:
        from .render import render_screen, scale_preview

        scr = self.current_screen()
        if not scr:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter PNG", str(ROOT / "assets" / f"{scr.id}.png"), "PNG (*.png)")
        if not path:
            return
        img = scale_preview(render_screen(scr, self.project, self.values), 8)
        img.save(path)
        self.statusBar().showMessage(f"PNG exporté {path}")

    def push_pixoo(self) -> None:
        from .render import render_screen

        scr = self.current_screen()
        if not scr:
            return
        ip = self.project.meta.pixoo_ip
        try:
            from pixoo_monitor.pixoo_client import PixooClient

            img = render_screen(scr, self.project, self.values)
            client = PixooClient(ip, size=64)
            client.set_brightness(int(self.project.meta.brightness))
            client.push_image(img)
            self.statusBar().showMessage(f"Poussé « {scr.title} » → {ip}")
        except Exception as exc:
            QMessageBox.warning(self, "Pixoo", f"Envoi impossible:\n{exc}")

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "À propos",
            "Pixoo 64 Designer\n\n"
            "Éditeur graphique pour composer des écrans 64×64,\n"
            "lier des sources (builtin / commande / HTTP),\n"
            "prévisualiser et pousser vers un Divoom Pixoo 64.",
        )

    def _open_docs(self) -> None:
        doc = ROOT / "docs" / "DESIGNER.md"
        self.statusBar().showMessage(f"Documentation: {doc}")
        try:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(doc)))
        except Exception:
            pass
