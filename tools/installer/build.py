"""Build the installer.

    python tools/installer/build.py

1. pyinstaller converter.spec            -> dist/Converter.exe        (skip with --no-app)
2. Uninstall.exe                         (the same program, no payload)
3. dist/KopiTehnik-Converter-Setup.exe   (installer with Converter.exe, Uninstall.exe, licences inside)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "build" / "installer"
PAYLOAD = HERE / "payload"
EXCLUDES = ["tkinter", "unittest", "numpy", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf",
            "PySide6.QtSvg", "PySide6.QtWebEngineCore", "PySide6.QtPrintSupport", "PySide6.QtOpenGL"]


def run(*a):
    print(">", *a)
    subprocess.run([str(x) for x in a], check=True)


def pyi(name: str, out: Path, datas: list[tuple[Path, str]]):
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
            "--name", name, "--icon", ROOT / "assets" / "icon.ico",
            "--distpath", out, "--workpath", WORK / name, "--specpath", WORK]
    for ex in EXCLUDES:
        args += ["--exclude-module", ex]
    for src, dst in datas:
        args += ["--add-data", f"{src};{dst}"]
    run(*args, HERE / "setup_app.py")


def main() -> int:
    if "--no-app" not in sys.argv:
        run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", ROOT / "dist",
            "--workpath", ROOT / "build", ROOT / "converter.spec")
    exe = ROOT / "dist" / "Converter.exe"
    PAYLOAD.mkdir(exist_ok=True)
    shutil.copy2(exe, PAYLOAD / "Converter.exe")
    shutil.copy2(ROOT / "assets" / "icon.ico", PAYLOAD / "icon.ico")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.txt", PAYLOAD / "THIRD_PARTY_NOTICES.txt")
    shutil.copy2(ROOT / "MCP.md", PAYLOAD / "MCP.md")
    pyi("Uninstall", WORK / "uninst", [(PAYLOAD / "icon.ico", ".")])
    shutil.copy2(WORK / "uninst" / "Uninstall.exe", PAYLOAD / "Uninstall.exe")
    files = [(PAYLOAD / n, ".") for n in ("Converter.exe", "Uninstall.exe", "icon.ico", "THIRD_PARTY_NOTICES.txt", "MCP.md")]
    pyi("KopiTehnik-Converter-Setup", ROOT / "dist", files)
    print("Готово:", ROOT / "dist" / "KopiTehnik-Converter-Setup.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
