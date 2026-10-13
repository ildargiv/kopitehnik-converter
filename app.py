"""Entry point: python app.py"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def convert_cli(src: str, dst: str) -> int:
    """Converter.exe --convert <input folder> <output folder>: convert with saved defaults, no window."""
    from PySide6.QtGui import QGuiApplication

    from core.batch import Batch, scan_folder
    from core.imaging import JobSettings

    app = QGuiApplication(sys.argv[:1])  # Qt renders PDF, SVG and documents
    out = Path(dst)
    out.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    res = Batch(scan_folder(Path(src)), out, JobSettings(),
                on_log=lambda lvl, msg: lines.append(f"{lvl}: {msg}")).run()
    lines.append(f"converted={res.converted} pages={res.pages} failed={len(res.failed)}")
    (out / "convert_log.txt").write_text("\n".join(lines), encoding="utf-8")
    del app
    return 1 if res.failed else 0


def _check_updates_quietly(win) -> None:
    """With a version file configured, tell about a new version once per launch; stay silent otherwise."""
    from core.version import GROUP_URL, UPDATE_URL
    if not UPDATE_URL:
        return
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox
    from ui.about import UpdateChecker

    checker = UpdateChecker(win)

    def done(info, err):
        if info is None:
            return
        box = QMessageBox(win)
        box.setWindowTitle(win.t("update_check"))
        box.setText(win.t("update_available", v=info.version))
        get = box.addButton(win.t("update_open"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(win.t("close"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is get:
            QDesktopServices.openUrl(QUrl(info.url or GROUP_URL))

    checker.done.connect(done)
    checker.start()


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--mcp":
        from core.mcp_server import run   # MCP server for AI agents, speaks JSON over stdin/stdout
        return run()
    if len(sys.argv) == 4 and sys.argv[1] == "--ocr":
        from core import ocr  # Converter.exe --ocr <scanned.pdf> <searchable.pdf>
        ocr.build_pdf(sys.argv[2], sys.argv[3])
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "--convert":
        return convert_cli(sys.argv[2], sys.argv[3])
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setOrganizationName("KopiTehnik")
    app.setApplicationName("KopiTehnik")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(QIcon(str(BASE / "assets" / "icon.png")))
    win = MainWindow()
    win.show()
    _check_updates_quietly(win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
