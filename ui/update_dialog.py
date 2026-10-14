"""The "new version" window: ask, download the installer, check its SHA-256, start it."""
from __future__ import annotations

import os
import subprocess
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from core import updater
from core.version import RELEASES_URL, VERSION

from .widgets import AnimatedButton


class _Download(QObject):
    progress = Signal(int, int)
    done = Signal(str, str)   # installer path, error text

    def __init__(self, parent, info):
        super().__init__(parent)
        self.info = info
        self.stop = False

    def start(self):
        def work():
            try:
                path = updater.download(self.info, self.progress.emit, lambda: self.stop)
                self.done.emit(str(path), "")
            except updater.HashMismatch:
                self.done.emit("", "hash")
            except InterruptedError:
                self.done.emit("", "cancel")
            except Exception as e:
                self.done.emit("", str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()


class UpdateDialog(QDialog):
    def __init__(self, parent, t, info: updater.UpdateInfo):
        super().__init__(parent)
        self._t, self._info, self._dl = t, info, None
        self.setWindowTitle(t("update_check"))
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(10)
        head = QLabel(t("update_available", v=info.version) + " " + t("update_current", v=VERSION))
        head.setWordWrap(True)
        v.addWidget(head)
        if info.notes.strip():
            notes = QLabel(info.notes.strip()[:600])
            notes.setObjectName("hint")
            notes.setWordWrap(True)
            v.addWidget(notes)
        self.status = QLabel("" if info.url else t("update_manual"))
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        v.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.later = AnimatedButton(t("update_later"))
        self.later.clicked.connect(self._cancel)
        self.go = AnimatedButton(t("update_install") if info.url else t("update_open"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._go)
        row.addWidget(self.later)
        row.addWidget(self.go)
        v.addLayout(row)

    def _go(self):
        if not self._info.url:
            QDesktopServices.openUrl(QUrl(self._info.page or RELEASES_URL))
            self.accept()
            return
        self.go.setEnabled(False)
        self.bar.show()
        self.status.setText(self._t("update_downloading"))
        self._dl = _Download(self, self._info)
        self._dl.progress.connect(self._progress)
        self._dl.done.connect(self._downloaded)
        self._dl.start()

    def _progress(self, got, total):
        self.bar.setRange(0, total or 0)
        self.bar.setValue(got)

    def _cancel(self):
        if self._dl:
            self._dl.stop = True
        self.reject()

    def _downloaded(self, path, err):
        t = self._t
        if err == "cancel":
            return
        if err:
            self.bar.hide()
            self.go.setEnabled(True)
            self.status.setText(t("update_bad_hash") if err == "hash" else t("update_dl_failed"))
            return
        self.status.setText(t("update_starting"))
        try:
            subprocess.Popen([path], close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except OSError:
            self.status.setText(t("update_dl_failed"))
            self.go.setEnabled(True)
            return
        self.accept()
        QApplication.quit()   # the installer cannot replace a running Converter.exe
