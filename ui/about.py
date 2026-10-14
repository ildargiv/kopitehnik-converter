"""The "About" window: what the program is and who made it."""
from __future__ import annotations

import sys
from pathlib import Path

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from .widgets import AnimatedButton, LogoMark

from core import updater
from core.version import VERSION


def _icon_path() -> Path:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "assets" / "icon.png"


class UpdateChecker(QObject):
    """Runs updater.check() in a thread; emits (info or None, error text)."""
    done = Signal(object, str)

    def start(self):
        def work():
            try:
                self.done.emit(updater.check(), "")
            except Exception as e:  # network down, bad file
                self.done.emit(None, str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()


class AboutDialog(QDialog):
    def __init__(self, parent, t):
        super().__init__(parent)
        self.setWindowTitle(t("about"))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(LogoMark("К"))
        titles = QVBoxLayout()
        title = QLabel(t("app_title"))
        title.setObjectName("appTitle")
        titles.addWidget(title)
        titles.addWidget(QLabel(t("about_version", v=VERSION)))
        head.addLayout(titles, 1)
        v.addLayout(head)

        desc = QLabel(t("about_desc"))
        desc.setWordWrap(True)
        v.addWidget(desc)

        dev = QLabel(f"<b>{t('about_dev')}:</b> {t('about_dev_name')}")
        dev.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(dev)
        site_url = t("about_site_url")
        site = QLabel(f"<b>{t('about_site')}:</b> <a href=\"https://{site_url}\" style=\"color:#937aff\">{site_url}</a>")
        site.setTextFormat(Qt.TextFormat.RichText)
        site.setOpenExternalLinks(False)
        site.setCursor(Qt.CursorShape.PointingHandCursor)
        site.linkActivated.connect(lambda link: QDesktopServices.openUrl(QUrl(link)))
        v.addWidget(site)
        site_note = QLabel(t("about_site_note"))
        site_note.setObjectName("hint")
        site_note.setWordWrap(True)
        v.addWidget(site_note)
        self.upd_status = QLabel("")
        self.upd_status.setWordWrap(True)
        self.upd_status.setOpenExternalLinks(True)
        self.upd_btn = AnimatedButton(t("update_check"))
        self.upd_btn.clicked.connect(self._check)
        self._checker = UpdateChecker(self)
        self._checker.done.connect(self._checked)
        self._t = t
        upd_row = QHBoxLayout()
        upd_row.addWidget(self.upd_btn)
        upd_row.addWidget(self.upd_status, 1)
        v.addLayout(upd_row)
        mcp_btn = AnimatedButton(t("mcp_button"))
        mcp_btn.clicked.connect(lambda: self._mcp(parent))
        v.addWidget(mcp_btn)
        rights = QLabel(t("about_rights"))
        rights.setObjectName("hint")
        rights.setWordWrap(True)
        v.addWidget(rights)

        row = QHBoxLayout()
        row.addStretch(1)
        ok = AnimatedButton(t("close"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addLayout(row)

    def _mcp(self, parent):
        from .mcp_info import McpDialog
        dlg = McpDialog(self, self._t)
        dlg.setStyleSheet(self.styleSheet() or (parent.styleSheet() if parent else ""))
        dlg.exec()

    def _check(self):
        self.upd_btn.setEnabled(False)
        self.upd_status.setText(self._t("update_checking"))
        self._checker.start()

    def _checked(self, info, err):
        t = self._t
        self.upd_btn.setEnabled(True)
        if err:
            self.upd_status.setText(t("update_failed"))
        elif info is None:
            self.upd_status.setText(t("update_latest", v=VERSION))
        else:
            self.upd_status.setText(t("update_available", v=info.version))
            from .update_dialog import UpdateDialog
            UpdateDialog(self, t, info).exec()
