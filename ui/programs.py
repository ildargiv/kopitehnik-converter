"""The "Programs" window: which helper programs were found and which office engine to use."""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from core import office

from .widgets import Card

LO_DOWNLOAD = "https://www.libreoffice.org/download/download-libreoffice/"


def summary(progs: office.Programs, t) -> str:
    """One line for the log: what was found."""
    found = [name for name, ok in (
        ("Word", progs.word), ("PowerPoint", progs.powerpoint), ("Excel", progs.excel),
        ("LibreOffice", progs.libreoffice), ("7-Zip", progs.sevenzip), ("WinRAR", progs.winrar),
    ) if ok]
    return t("progs_log", found=", ".join(found) if found else t("progs_none"))


class ProgramsDialog(QDialog):
    def __init__(self, parent, t, first_run: bool = False):
        super().__init__(parent)
        self.t = t
        self.setWindowTitle(t("progs_title"))
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)

        intro = QLabel(t("progs_intro_first") if first_run else t("progs_intro"))
        intro.setWordWrap(True)
        v.addWidget(intro)

        card = Card(collapsible=False)
        card.title.setText(t("progs_found"))
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnStretch(2, 1)
        card.add(self.grid)
        v.addWidget(card)

        eng = Card(collapsible=False)
        eng.title.setText(t("progs_engine_title"))
        row = QHBoxLayout()
        row.addWidget(QLabel(t("progs_engine")))
        row.addStretch(1)
        self.engine_combo = QComboBox()
        for key in (office.ENGINE_AUTO, office.ENGINE_MS, office.ENGINE_LO):
            self.engine_combo.addItem(t(f"engine_{key}"), key)
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(office.get_preference())))
        self.engine_combo.currentIndexChanged.connect(
            lambda *_: office.set_preference(self.engine_combo.currentData()))
        row.addWidget(self.engine_combo)
        eng.add(row)
        hint = QLabel(t("progs_engine_hint"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        eng.add(hint)
        lo_row = QHBoxLayout()
        lo_row.setSpacing(6)
        pick = QPushButton(t("progs_pick_lo"))
        pick.clicked.connect(self._pick_lo)
        lo_row.addWidget(pick)
        self.forget_btn = QPushButton(t("progs_forget_lo"))
        self.forget_btn.clicked.connect(self._forget_lo)
        lo_row.addWidget(self.forget_btn)
        download = QPushButton(t("progs_download_lo"))
        download.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(LO_DOWNLOAD)))
        lo_row.addWidget(download)
        lo_row.addStretch(1)
        eng.add(lo_row)
        self.error_label = QLabel()
        self.error_label.setObjectName("hint")
        self.error_label.setWordWrap(True)
        eng.add(self.error_label)
        v.addWidget(eng)

        buttons = QHBoxLayout()
        again = QPushButton(t("progs_recheck"))
        again.clicked.connect(lambda: self._fill(refresh=True))
        buttons.addWidget(again)
        buttons.addStretch(1)
        close = QPushButton(t("close"))
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        v.addLayout(buttons)
        self._fill()

    def _fill(self, refresh: bool = False):
        progs = office.detect(refresh=refresh)
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if progs.lo_custom:
            lo_state = self.t("lo_custom")
        elif progs.lo_installed:
            lo_state = self.t("lo_installed")
        elif progs.lo_bundled:
            lo_state = self.t("lo_bundled")
        else:
            lo_state = ""
        rows = [
            ("Microsoft Word", progs.word, "", self.t("use_word")),
            ("Microsoft PowerPoint", progs.powerpoint, "", self.t("use_powerpoint")),
            ("Microsoft Excel", progs.excel, "", self.t("use_excel")),
            ("LibreOffice", progs.libreoffice, lo_state, self.t("use_lo")),
            ("7-Zip", progs.sevenzip, "", self.t("use_7z")),
            ("WinRAR", progs.winrar, "", self.t("use_rar")),
            (self.t("pdf_editor"), progs.pymupdf, "", self.t("use_pymupdf")),
        ]
        for r, (name, ok, state, use) in enumerate(rows):
            mark = QLabel("✓" if ok else "✕")
            mark.setStyleSheet(f"color: {'#22c55e' if ok else '#f43f5e'}; font-weight: 700;")
            self.grid.addWidget(mark, r, 0)
            title = QLabel(name)
            title.setStyleSheet("font-weight: 600;")
            self.grid.addWidget(title, r, 1)
            desc = QLabel(use + (f" · {state}" if ok and state else "") + ("" if ok else " · " + self.t("not_found")))
            desc.setObjectName("hint")
            desc.setWordWrap(True)
            self.grid.addWidget(desc, r, 2)
        verdict = QLabel(self.t("progs_ok") if progs.any_office else self.t("progs_no_office"))
        verdict.setWordWrap(True)
        verdict.setStyleSheet(f"color: {'#22c55e' if progs.any_office else '#f59e0b'};")
        self.grid.addWidget(verdict, len(rows), 0, 1, 3)
        self.forget_btn.setVisible(bool(progs.lo_custom))

    def _pick_lo(self):
        start = os.environ.get("ProgramFiles", "C:\\")
        path, _ = QFileDialog.getOpenFileName(self, self.t("progs_pick_lo"), start, "soffice.exe (soffice.exe)")
        if not path:
            return
        try:
            office.set_custom_libreoffice(path)
            self.error_label.setText("")
        except office.OfficeError as exc:
            self.error_label.setText(str(exc))
        self._fill()

    def _forget_lo(self):
        office.set_custom_libreoffice(None)
        self._fill()
