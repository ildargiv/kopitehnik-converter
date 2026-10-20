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
    """Look for a newer GitHub release once per launch; ask only when there is one, stay silent otherwise."""
    from ui.about import UpdateChecker
    from ui.update_dialog import UpdateDialog

    checker = UpdateChecker(win)
    checker.done.connect(lambda info, err: info and UpdateDialog(win, win.t, info).exec())
    checker.start()


def _emit(text: str, stream=None) -> None:
    """Writes a line as UTF-8 bytes: the Windows console (cp1251, cp866...) cannot encode every character of a file name."""
    stream = stream or sys.stdout
    data = (text + "\n").encode("utf-8")
    try:
        stream.buffer.write(data)
        stream.flush()
    except (AttributeError, ValueError, OSError):
        stream.write(data.decode("utf-8", "replace"))


def edit_cli(argv: list[str]) -> int:
    """Converter.exe --edit <file> [--ocr] [--out <result.pdf>]: only the PDF editor, no main window.

    The last stdout line is the saved PDF (UTF-8). Exit code: 0 saved, 1 closed without saving, 2 cannot open.
    No update check runs here and nothing is shared with a running main window.
    """
    args = list(argv)
    ocr_first = "--ocr" in args
    if ocr_first:
        args.remove("--ocr")
    out = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("--out needs a path", file=sys.stderr)
            return 2
        out = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        print("usage: Converter.exe --edit <file> [--ocr] [--out <result.pdf>]", file=sys.stderr)
        return 2
    src = Path(args[0])
    if not src.is_file():
        _emit(f"file not found: {src}", sys.stderr)
        return 2

    import shutil
    import tempfile

    from PySide6.QtCore import QSettings

    from core import office
    from ui.i18n import LANGUAGES, system_language, tr
    from ui.pdf_editor import PdfEditor
    from ui.theme import PALETTES, stylesheet

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("KopiTehnik")
    app.setApplicationName("KopiTehnik")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(QIcon(str(BASE / "assets" / "icon.png")))
    store = QSettings()
    lang = store.value("lang", system_language())
    lang = lang if lang in LANGUAGES else "en"
    theme = store.value("theme", "dark")
    theme = theme if theme in PALETTES else "dark"

    work = Path(tempfile.mkdtemp(prefix="kt_edit_"))
    try:
        ext = src.suffix.lower()
        scan = ocr_first
        try:
            if ext == ".pdf":
                pdf = src
            elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"):
                import pymupdf
                with pymupdf.open(src) as img:
                    pdf = work / "scan.pdf"
                    pdf.write_bytes(img.convert_to_pdf())
                scan = True
            else:
                pdf = work / "doc.pdf"
                office.to_pdf(src, pdf)
        except Exception as exc:
            _emit(f"cannot open {src.name}: {exc}", sys.stderr)
            return 2
        save_to = out if out else src.with_name(src.stem + "_edited.pdf")
        dlg = PdfEditor(None, lambda key, **kw: tr(lang, key, **kw), pdf, save_to, src.name, auto_ocr=scan)
        dlg.standalone = True
        dlg.setStyleSheet(stylesheet(PALETTES[theme]))
        dlg.exec()
        if not dlg.result:
            return 1
        _emit(str(dlg.result))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--mcp":
        from core.mcp_server import run   # MCP server for AI agents, speaks JSON over stdin/stdout
        return run()
    if len(sys.argv) >= 2 and sys.argv[1] == "--edit":
        return edit_cli(sys.argv[2:])
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
