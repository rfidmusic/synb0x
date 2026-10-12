#!/usr/bin/env python3
"""Synb0x Firmware Patcher: a window around apply.py (PyQt6).

    python3 synb0x_patcher_gui.py          (pip install PyQt6)

Choose your stock 3.1.9 BLACKBOX.bin (from 1010music's download), pick a Synb0x version and where to save; it is
patched exactly as apply.py does, checked by SHA-256 before and after, and never written over the stock file. The
patches are the release JSON files (docs/blackbox-mod-*.json): no firmware is included in this program.
"""
import glob
import hashlib
import json
import os
import subprocess
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QRadioButton, QVBoxLayout, QWidget)

import apply

APP_NAME = "Synb0x Firmware Patcher"
ABOUT = {
    "3.1.t": "Filter Morph: LP → notch → HP, modulatable. Filter envelope, Filt tab, KEY / FENV sources, "
             "glide, CPU meter.",
    "3.1.s": "Filter Type: LP / HP / BP. Filter envelope, Filt tab, KEY / FENV sources, glide, CPU meter.",
}
VOLUMES = "/Volumes" if sys.platform == "darwin" else ""


def patch_dirs():
    """Where the release patches are: bundled with the app, else the repository's docs/."""
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "patches"))
    dirs.append(os.path.join(apply.ROOT, "docs"))
    return dirs


def load_patches():
    """{version: patch}, newest version first."""
    found = {}
    for d in patch_dirs():
        for f in glob.glob(os.path.join(d, "blackbox-mod-*.json")):
            try:
                p = json.load(open(f))
                found.setdefault(p["version"], p)
            except (OSError, ValueError, KeyError):
                continue
    return dict(sorted(found.items(), reverse=True))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(760, 600)
        self.setAcceptDrops(True)
        self.patches = load_patches()
        self.stock_path = None
        self.stock_ok = False
        self.out_dir = None                     # None: next to the stock file
        self.written = None

        intro = QLabel("Makes Synb0x firmware for the <b>original</b> 1010music Blackbox (not the Blackbox 2) from your "
                       "own stock 3.1.9 <code>BLACKBOX.bin</code>. Download it from "
                       "<a href='https://1010music.com/downloads'>1010music.com/downloads</a> and use the "
                       "<code>BLACKBOX.bin</code> inside the zip. Unofficial; not affiliated with 1010music. Keep "
                       "the stock file to go back.")
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        intro.setTextFormat(Qt.TextFormat.RichText)

        # 1. stock file
        step1 = QGroupBox("1. Stock firmware")
        choose = QPushButton("Choose BLACKBOX.bin…")
        choose.clicked.connect(self.choose_stock)
        self.stock_label = QLabel("No file chosen (or drag it onto this window).")
        self.stock_label.setWordWrap(True)
        self.stock_label.setMinimumHeight(2 * self.stock_label.fontMetrics().height())
        self.stock_status = QLabel("")
        self.stock_status.setWordWrap(True)
        l1 = QVBoxLayout(step1)
        r1 = QHBoxLayout()
        r1.addWidget(choose)
        r1.addWidget(self.stock_label, 1)
        l1.addLayout(r1)
        l1.addWidget(self.stock_status)

        # 2. version
        step2 = QGroupBox("2. Synb0x version")
        l2 = QVBoxLayout(step2)
        self.versions = QButtonGroup(self)
        self.version_buttons = {}
        for i, (v, p) in enumerate(self.patches.items()):
            b = QRadioButton(f"Synb0x {v}" + ("  (latest)" if i == 0 else ""))
            b.setChecked(i == 0)
            self.versions.addButton(b)
            self.version_buttons[v] = b
            l2.addWidget(b)
            d = QLabel(ABOUT.get(v, "") + f"<br><small>Result SHA-256: <code>{p['output_sha256']}</code></small>")
            d.setWordWrap(True)
            d.setTextFormat(Qt.TextFormat.RichText)
            d.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            d.setContentsMargins(24, 0, 0, 6)
            l2.addWidget(d)
            b.toggled.connect(self.update_state)
        if not self.patches:
            l2.addWidget(QLabel("No patch files found (docs/blackbox-mod-*.json)."))

        # 3. where
        step3 = QGroupBox("3. Save to")
        l3 = QVBoxLayout(step3)
        r3 = QHBoxLayout()
        self.out_label = QLabel("")
        self.out_label.setWordWrap(True)
        self.out_label.setMinimumHeight(3 * self.out_label.fontMetrics().height())
        self.out_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        pick = QPushButton("Choose Folder or SD Card…")
        pick.setToolTip("Saving to the root of the Blackbox's microSD card installs it there directly")
        pick.clicked.connect(self.choose_out)
        reset = QPushButton("Next to the stock file")
        reset.clicked.connect(self.reset_out)
        r3.addWidget(pick)
        r3.addWidget(reset)
        r3.addStretch(1)
        l3.addLayout(r3)
        l3.addWidget(self.out_label)

        self.make_btn = QPushButton("Make Synb0x Firmware")
        self.make_btn.setDefault(True)
        self.make_btn.clicked.connect(self.make)
        self.reveal_btn = QPushButton("Show in Finder" if sys.platform == "darwin" else "Show Folder")
        self.reveal_btn.clicked.connect(self.reveal)
        self.reveal_btn.setEnabled(False)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.TextFormat.RichText)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        r4 = QHBoxLayout()
        r4.addWidget(self.result, 1)
        r4.addWidget(self.reveal_btn)
        r4.addWidget(self.make_btn)

        install = QLabel("To install: copy <code>BLACKBOX.bin</code> to the root of the Blackbox's microSD card, then "
                         "hold BACK + INFO while powering on. The startup screen and TOOLS show the Synb0x version. "
                         "To go back, install your stock <code>BLACKBOX.bin</code> the same way.")
        install.setWordWrap(True)
        install.setTextFormat(Qt.TextFormat.RichText)
        small = QFont(install.font())
        small.setPointSizeF(max(8.0, small.pointSizeF() - 1))
        install.setFont(small)

        lay = QVBoxLayout()
        lay.addWidget(intro)
        lay.addWidget(step1)
        lay.addWidget(step2)
        lay.addWidget(step3)
        lay.addStretch(1)
        lay.addLayout(r4)
        lay.addWidget(install)
        box = QWidget()
        box.setLayout(lay)
        self.setCentralWidget(box)
        self.update_state()

    # --- the stock file
    def choose_stock(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the stock BLACKBOX.bin", VOLUMES,
                                              "Firmware (*.bin);;All files (*)")
        if path:
            self.set_stock(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]
        if files:
            self.set_stock(files[0])

    def set_stock(self, path):
        self.stock_path = path
        self.written = None
        self.stock_label.setText(path)
        try:
            digest = sha256_file(path)
        except OSError as e:
            self.stock_ok = False
            self.stock_status.setText(f"✗ Can't read it: {e}")
            self.update_state()
            return
        stock = next(iter(self.patches.values()), {}).get("stock_sha256")
        made = [v for v, p in self.patches.items() if p["output_sha256"] == digest]
        self.stock_ok = digest == stock
        if self.stock_ok:
            self.stock_status.setText("✓ Stock 3.1.9 firmware (SHA-256 matches)")
        elif made:
            self.stock_status.setText(f"✗ This is already Synb0x {made[0]}. Choose the stock BLACKBOX.bin from "
                                      "1010music's 3.1.9 download.")
        else:
            self.stock_status.setText("✗ Not the stock 3.1.9 firmware (SHA-256 differs). Download blackbox 3.1.9 "
                                      "from 1010music.com/downloads and use the BLACKBOX.bin inside the zip.")
        self.update_state()

    # --- where
    def choose_out(self):
        path = QFileDialog.getExistingDirectory(self, "Save BLACKBOX.bin in (the SD card's root installs it there)",
                                                VOLUMES)
        if path:
            self.out_dir = path
            self.written = None
        self.update_state()

    def reset_out(self):
        self.out_dir = None
        self.written = None
        self.update_state()

    def version(self):
        for v, b in self.version_buttons.items():
            if b.isChecked():
                return v
        return None

    def out_path(self):
        v = self.version()
        if not v:
            return None
        if self.out_dir:
            return os.path.join(self.out_dir, "BLACKBOX.bin")
        if self.stock_path:
            return os.path.join(os.path.dirname(os.path.abspath(self.stock_path)), f"Synb0x {v}", "BLACKBOX.bin")
        return None

    def update_state(self, *_):
        out = self.out_path()
        self.out_label.setText(out or "Next to the stock file, in a folder named after the version.")
        self.make_btn.setEnabled(bool(self.stock_ok and out))
        self.reveal_btn.setEnabled(bool(self.written))
        if not self.written:
            self.result.setText("")

    # --- making it
    def make(self):
        v = self.version()
        out = self.out_path()
        if not (self.stock_ok and v and out):
            return
        if os.path.abspath(out) == os.path.abspath(self.stock_path):
            QMessageBox.warning(self, APP_NAME, "That would overwrite your stock file. Choose another folder and keep "
                                "the stock one as a backup.")
            return
        if os.path.exists(out):
            r = QMessageBox.question(self, APP_NAME, f"{out} already exists. Replace it?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Cancel)
            if r != QMessageBox.StandardButton.Yes:
                return
        try:
            data = apply.patch_image(open(self.stock_path, "rb").read(), self.patches[v])
            os.makedirs(os.path.dirname(out), exist_ok=True)
            tmp = out + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, out)
            digest = sha256_file(out)
        except (apply.PatchError, OSError) as e:
            QMessageBox.critical(self, APP_NAME, str(e))
            return
        ok = digest == self.patches[v]["output_sha256"]
        self.written = out
        self.update_state()
        self.result.setText((f"✓ Synb0x {v} written ({len(data):,} bytes).<br>" if ok else
                             "✗ The written file doesn't match the release. Try again or use another card.<br>")
                            + f"<small>SHA-256 <code>{digest}</code></small>")

    def reveal(self):
        if not self.written:
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", self.written], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", os.path.normpath(self.written)], check=False)
        else:
            subprocess.run(["xdg-open", os.path.dirname(self.written)], check=False)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = Window()
    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if files:
        w.set_stock(files[0])
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
