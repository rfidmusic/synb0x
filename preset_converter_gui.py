#!/usr/bin/env python3
"""Synb0x Preset Converter: a window around convert_presets.py (PyQt6).

    python3 preset_converter_gui.py          (pip install PyQt6)

Add an SD card, a Presets folder, a preset folder or a single preset.xml (buttons or drag and drop); every preset.xml
below is listed with what will change. Then either replace them in place (each original kept as preset.xml.bak) or
make converted copies "<name> syn". Presets already saved on Synb0x are skipped. The conversion itself is
convert_presets.py's, unchanged.
"""
import os
import subprocess
import sys

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QFileDialog, QHBoxLayout, QHeaderView,
                             QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QRadioButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

import convert_presets as cp

APP_NAME = "Synb0x Preset Converter"
STATUS_TEXT = {"convert": "Will convert", "synb0x": "Already Synb0x", "copy": "Converted copy", "exists": "Copy exists"}
VOLUMES = "/Volumes" if sys.platform == "darwin" else ""


class Worker(QObject):
    """Writes the checked presets off the UI thread (copying samples can take a while)."""
    progress = pyqtSignal(int, str, str, str)   # index, folder, backup path, error ("" = none)
    finished = pyqtSignal()

    def __init__(self, infos):
        super().__init__()
        self.infos = infos

    def run(self):
        for i, info in enumerate(self.infos):
            try:
                if not info["in_place"] and os.path.exists(info["dest"]):
                    raise FileExistsError(f"{os.path.basename(info['dest'])} already exists")
                bak = cp.write(info) or ""
                self.progress.emit(i, info["folder"], bak, "")
            except Exception as e:              # report and carry on with the rest
                self.progress.emit(i, info["folder"], "", str(e) or e.__class__.__name__)
        self.finished.emit()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 600)
        self.setAcceptDrops(True)
        self.folders = []                       # preset folders added, in order
        self.infos = {}                         # folder -> inspect() result
        self.items = {}                         # folder -> tree row
        self.dest_root = None                   # copies: None = next to the originals
        self.thread = None
        self.done, self.failed = [], []

        intro = QLabel("Converts Blackbox presets saved before Synb0x (stock 3.1.9, blackbox-mod 3.1.n) so filtered "
                       "pads sound as they did, on Synb0x 3.1.s and 3.1.t. Presets already saved on Synb0x are "
                       "skipped, so running it again is safe.")
        intro.setWordWrap(True)

        card = QPushButton("Add SD Card or Folder…")
        card.setToolTip("Every preset.xml in it is found: a whole card, its Presets folder, or one preset folder")
        card.clicked.connect(self.choose_folder)
        one = QPushButton("Add preset.xml…")
        one.clicked.connect(self.choose_file)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        top = QHBoxLayout()
        top.addWidget(card)
        top.addWidget(one)
        top.addWidget(self.clear_btn)
        top.addStretch(1)
        top.addWidget(QLabel("or drag them here"))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Preset", "Status", "Details"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setWordWrap(True)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 260)
        self.tree.itemChanged.connect(self.update_summary)

        # mode
        self.in_place = QRadioButton("Replace in place (each original kept as preset.xml.bak)")
        self.copies = QRadioButton("Make copies “<name> syn”")
        self.in_place.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.in_place)
        mode_group.addButton(self.copies)
        mode = QHBoxLayout()
        mode.addWidget(QLabel("Convert:"))
        mode.addWidget(self.in_place)
        mode.addWidget(self.copies)
        mode.addStretch(1)

        # where copies go
        self.next_to = QRadioButton("next to the originals")
        self.elsewhere = QRadioButton("in a folder:")
        self.next_to.setChecked(True)
        dest_group = QButtonGroup(self)
        dest_group.addButton(self.next_to)
        dest_group.addButton(self.elsewhere)
        self.dest_label = QLabel("")
        self.dest_btn = QPushButton("Choose…")
        self.dest_btn.clicked.connect(self.choose_dest)
        self.copy_row = QWidget()
        out = QHBoxLayout(self.copy_row)
        out.setContentsMargins(0, 0, 0, 0)
        out.addSpacing(24)
        out.addWidget(QLabel("Save copies"))
        out.addWidget(self.next_to)
        out.addWidget(self.elsewhere)
        out.addWidget(self.dest_btn)
        out.addWidget(self.dest_label, 1)

        self.summary = QLabel("")
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.reveal_btn = QPushButton("Show in Finder" if sys.platform == "darwin" else "Show Folder")
        self.reveal_btn.setEnabled(False)
        self.reveal_btn.clicked.connect(self.reveal)
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setDefault(True)
        self.convert_btn.setEnabled(False)
        self.convert_btn.clicked.connect(self.convert)
        bottom = QHBoxLayout()
        bottom.addWidget(self.summary, 1)
        bottom.addWidget(self.progress)
        bottom.addWidget(self.reveal_btn)
        bottom.addWidget(self.convert_btn)

        note = QLabel("To undo a conversion in place: delete preset.xml and rename preset.xml.bak back to preset.xml. "
                      "The filter keeps Synb0x's 24 dB slope (stock 12 dB): the same cutoff, a little steeper.")
        note.setWordWrap(True)
        small = QFont(note.font())
        small.setPointSizeF(max(8.0, small.pointSizeF() - 1))
        note.setFont(small)

        lay = QVBoxLayout()
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addLayout(mode)
        lay.addWidget(self.copy_row)
        lay.addLayout(bottom)
        lay.addWidget(note)
        box = QWidget()
        box.setLayout(lay)
        self.setCentralWidget(box)

        self.in_place.toggled.connect(self.refresh)
        self.elsewhere.toggled.connect(self.dest_toggled)
        self.refresh()

    # --- adding presets
    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose an SD card, a Presets folder or a preset folder",
                                                VOLUMES)
        if path:
            self.add_paths([path])

    def choose_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose preset.xml files", VOLUMES, "Presets (preset.xml)")
        if paths:
            self.add_paths(paths)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def add_paths(self, paths):
        empty = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for p in paths:
                if not os.path.exists(p):
                    continue
                found = cp.presets_in(p)
                if not found:
                    empty.append(os.path.basename(os.path.normpath(p)) or p)
                for f in found:
                    if f not in self.folders:
                        self.folders.append(f)
        finally:
            QApplication.restoreOverrideCursor()
        if empty:
            QMessageBox.information(self, APP_NAME, "No preset.xml found in: " + ", ".join(empty))
        self.refresh()

    def clear(self):
        self.folders = []
        self.refresh()

    # --- where copies go
    def choose_dest(self):
        path = QFileDialog.getExistingDirectory(self, "Save converted copies in")
        if path:
            self.dest_root = path
            self.elsewhere.setChecked(True)
        self.refresh()

    def dest_toggled(self, on):
        if on and not self.dest_root:
            self.choose_dest()
            if not self.dest_root:
                self.next_to.setChecked(True)
        self.refresh()

    # --- the list
    def refresh(self, *_):
        in_place = self.in_place.isChecked()
        self.copy_row.setEnabled(not in_place)
        self.dest_label.setText(self.dest_root if self.elsewhere.isChecked() and self.dest_root else "")
        self.reveal_btn.setEnabled(False)
        self.done, self.failed = [], []
        self.tree.blockSignals(True)
        self.tree.clear()
        self.infos, self.items = {}, {}
        root = self.dest_root if self.elsewhere.isChecked() else None
        for f in self.folders:
            try:
                info = cp.inspect(f, root, in_place)
            except Exception as e:
                info = {"folder": f, "name": os.path.basename(f), "status": "error", "error": str(e), "notes": []}
            if info is None:
                continue
            self.infos[f] = info
            row = QTreeWidgetItem([info["name"], "", ""])
            row.setToolTip(0, f)
            self.items[f] = row
            self.tree.addTopLevelItem(row)
            if info["status"] == "convert":
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(0, Qt.CheckState.Checked)
                row.setText(1, STATUS_TEXT["convert"])
                where = "in place" if in_place else "→ " + os.path.basename(info["dest"])
                row.setText(2, f"{info['pads']} pad(s) {where}")
                for n in info["notes"]:
                    child = QTreeWidgetItem(["", "", n.strip()])
                    child.setToolTip(2, n.strip())
                    row.addChild(child)
                row.setExpanded(True)
            elif info["status"] == "error":
                row.setText(1, "Can't read")
                row.setText(2, info["error"])
            else:
                row.setText(1, STATUS_TEXT[info["status"]])
                row.setText(2, cp.describe(info).removeprefix("skipped (").removesuffix(")"))
                if info["status"] == "synb0x" and os.path.exists(os.path.join(f, "preset.xml.bak")):
                    row.setText(1, "Converted")
                    row.setText(2, "converted earlier; the original is in preset.xml.bak")
                row.setDisabled(True)
        self.tree.blockSignals(False)
        self.update_summary()

    def checked(self):
        return [self.infos[f] for f, row in self.items.items()
                if self.infos[f]["status"] == "convert" and row.checkState(0) == Qt.CheckState.Checked]

    def update_summary(self, *_):
        if not self.folders:
            self.summary.setText("Add an SD card, a folder or a preset.xml to start.")
        else:
            self.summary.setText(f"{len(self.infos)} preset(s) found, {len(self.checked())} to convert.")
        self.convert_btn.setEnabled(bool(self.checked()) and self.thread is None)

    # --- converting
    def convert(self):
        infos = self.checked()
        if not infos:
            return
        if self.in_place.isChecked():
            r = QMessageBox.question(
                self, APP_NAME,
                f"Replace {len(infos)} preset.xml file(s) in place?\n\nEach original is kept beside it as "
                "preset.xml.bak. Keep the card in until this finishes.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if r != QMessageBox.StandardButton.Yes:
                return
        self.convert_btn.setEnabled(False)
        self.progress.setRange(0, len(infos))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.done, self.failed = [], []
        self.thread = QThread()
        self.worker = Worker(infos)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.on_finished)      # once the thread has really stopped
        self.thread.start()

    def on_progress(self, i, folder, bak, error):
        self.progress.setValue(i + 1)
        row = self.items.get(folder)
        info = self.infos[folder]
        self.tree.blockSignals(True)
        if error:
            self.failed.append(info["name"])
            if row:
                row.setText(1, "Failed")
                row.setText(2, error)
        else:
            self.done.append(info)
            if row:
                row.setText(1, "Converted ✓")
                row.setText(2, f"{info['pads']} pad(s), original kept as {os.path.basename(bak)}" if bak
                            else f"{info['pads']} pad(s) → {info['dest']}")
                row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                row.setData(0, Qt.ItemDataRole.CheckStateRole, None)
        self.tree.blockSignals(False)

    def on_finished(self):
        self.thread.deleteLater()
        self.worker.deleteLater()
        self.thread = None
        self.progress.setVisible(False)
        self.reveal_btn.setEnabled(bool(self.done))
        msg = f"{len(self.done)} preset(s) converted."
        if self.failed:
            msg += f" {len(self.failed)} failed: " + ", ".join(self.failed) + "."
        self.summary.setText(msg)
        self.convert_btn.setEnabled(False)

    def reveal(self):
        if not self.done:
            return
        info = self.done[-1]
        path = os.path.join(info["folder"], "preset.xml") if info["in_place"] else info["dest"]
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", os.path.normpath(path)], check=False)
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)], check=False)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = Window()
    w.add_paths([a for a in sys.argv[1:] if os.path.exists(a)])
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
