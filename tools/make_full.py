"""Build the "full" version: Converter.exe plus its own copy of LibreOffice.

    python tools/make_full.py [path to LibreOffice folder]

Without an argument the LibreOffice installed on this computer is used. The result is
dist/Converter-full/ (Converter.exe and a LibreOffice folder next to it) and
dist/Converter-full.zip. The program finds the LibreOffice folder next to itself, so
Word and PowerPoint files open on computers without any office suite.
Run `pyinstaller converter.spec` first so dist/Converter.exe exists.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.office import _find_installed_lo  # noqa: E402

# Parts of LibreOffice a headless conversion never needs.
SKIP_DIRS = {"help", "readmes", "sdk"}


def main() -> int:
    exe = ROOT / "dist" / "Converter.exe"
    if not exe.exists():
        print("Сначала соберите программу: pyinstaller converter.spec")
        return 1
    if len(sys.argv) > 1:
        lo_root = Path(sys.argv[1])
    else:
        soffice = _find_installed_lo()
        if not soffice:
            print("LibreOffice не найден. Установите его или укажите папку: python tools/make_full.py <папка>")
            return 1
        lo_root = Path(soffice).parent.parent
    if not (lo_root / "program" / "soffice.exe").exists():
        print(f"В {lo_root} нет program/soffice.exe")
        return 1
    out = ROOT / "dist" / "Converter-full"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    shutil.copy2(exe, out / exe.name)
    print(f"Копирую LibreOffice из {lo_root}…")
    shutil.copytree(lo_root, out / "LibreOffice",
                    ignore=lambda d, names: [n for n in names if n.lower() in SKIP_DIRS])
    print("Упаковываю zip…")
    archive = shutil.make_archive(str(out), "zip", out)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 2**20
    print(f"Готово: {out} ({size:.0f} МБ), архив {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
