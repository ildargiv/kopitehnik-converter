"""KopiTehnik Converter: installer and uninstaller (one program, two modes).

    Setup.exe                  install with the window
    Setup.exe /S [/D=folder]   silent install  (/NODESKTOP, /NOSTART skip shortcuts)
    Uninstall.exe              uninstall with the window
    Uninstall.exe /S [/KEEPDATA]

Per-user install (no administrator rights): %LOCALAPPDATA%\\Programs\\KopiTehnik Converter,
shortcuts on the desktop and in the Start menu, an entry in Settings > Apps.
"""
from __future__ import annotations

import base64
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import winreg
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal, QObject, QLocale
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

APP_NAME = "KopiTehnik Converter"
APP_TITLE_RU = "КопиТехник Конвертор"
APP_TITLE_EN = "KopiTehnik Converter"
PUBLISHER = "Гайсин Ильдар Вильсурович"
EXE_NAME = "Converter.exe"
UNINSTALL_NAME = "Uninstall.exe"
REG_UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\KopiTehnikConverter"
REG_SETTINGS = r"Software\KopiTehnik"
VERSION = "2.0"
SITE = "https://vk.ru/icc_profil"

BG, SURFACE, BORDER = QColor("#0e0f14"), QColor("#16171e"), QColor("#2a2c38")
TEXT, MUTED = QColor("#eceef5"), QColor("#8a8fa3")
ACCENT, ACCENT2, SOFT = QColor("#7c5cff"), QColor("#937aff"), QColor("#2a2350")
GREEN, RED = QColor("#22c55e"), QColor("#f43f5e")

RU = {
    "welcome": "Установка программы",
    "welcome_sub": "Конвертор фото и документов с правкой цвета, редактором PDF и печатью.",
    "folder": "Папка установки", "browse": "Обзор…",
    "desk": "Ярлык на рабочем столе", "start": "Ярлык в меню «Пуск»",
    "notice": "Права администратора не нужны. Лицензии сторонних компонентов устанавливаются вместе с программой.",
    "install": "Установить", "cancel": "Отмена", "next": "Далее", "prev": "Назад", "close": "Закрыть",
    "installing": "Устанавливаю…", "copy": "Копирую файлы…", "short": "Создаю ярлыки…", "reg": "Регистрирую в системе…",
    "done": "Готово", "done_sub": "Конвертор установлен. Ярлык ждёт на рабочем столе и в меню «Пуск».",
    "run": "Запустить Конвертор", "finish": "Завершить", "ready_hint": "Установка завершена. Посмотрите, что умеет программа.",
    "err": "Не удалось установить", "retry": "Повторить",
    "busy": "Закройте Конвертор и повторите.",
    "un_title": "Удаление программы", "un_sub": "Конвертор будет удалён с этого компьютера.",
    "un_data": "Удалить также мои настройки", "un_btn": "Удалить", "un_run": "Удаляю…",
    "un_done": "Программа удалена", "un_done_sub": "Спасибо, что пользовались Конвертором.",
    "title": APP_TITLE_RU,
}
EN = {
    "welcome": "Install", "welcome_sub": "Photo and document converter with colour tools, a PDF editor and printing.",
    "folder": "Install folder", "browse": "Browse…",
    "desk": "Desktop shortcut", "start": "Start menu shortcut",
    "notice": "No administrator rights needed. Third-party licences are installed with the program.",
    "install": "Install", "cancel": "Cancel", "next": "Next", "prev": "Back", "close": "Close",
    "installing": "Installing…", "copy": "Copying files…", "short": "Creating shortcuts…", "reg": "Registering…",
    "done": "All set", "done_sub": "Converter is installed. Look for the shortcut on the desktop and in the Start menu.",
    "run": "Run Converter", "finish": "Finish", "ready_hint": "Installation finished. Take a look at what the program can do.",
    "err": "Installation failed", "retry": "Retry",
    "busy": "Close Converter and try again.",
    "un_title": "Uninstall", "un_sub": "Converter will be removed from this computer.",
    "un_data": "Also remove my settings", "un_btn": "Uninstall", "un_run": "Removing…",
    "un_done": "Program removed", "un_done_sub": "Thanks for using Converter.",
    "title": APP_TITLE_EN,
}
from installer_langs import SLIDES as _OTHER_SLIDES  # noqa: E402
from installer_langs import STRINGS as _OTHER  # noqa: E402

_CODE = QLocale.system().name().split("_")[0].lower()
_KINDS = ["files", "color", "sheet", "pdf", "print", "ok"]
LANG = RU if _CODE == "ru" else _OTHER.get(_CODE, EN)


def tt(key: str) -> str:
    return LANG[key]


# slides: (title, text, steps, kind)
SLIDES_RU = [
    ("Любые файлы в одно окно",
     "JPG, PNG, WebP, HEIC, PSD, PDF, SVG, Word, Excel, PowerPoint и архивы ZIP. Можно бросить целую папку.",
     ["Перетащите файлы или папку в окно", "Выберите формат: JPG, PNG, TIFF или PDF", "Нажмите «Конвертировать»"], "files"),
    ("Цвет одним движением",
     "Автокоррекция, пипетка баланса белого, яркость, контраст, насыщенность и каналы цвета. Для всех фото сразу или для одного.",
     ["Включите автокоррекцию или двигайте ползунки", "Переключатель «Оригинал» покажет разницу", "Настройки применятся ко всем фото"], "color"),
    ("Кадр и печатный лист",
     "Обрезка 3:2, 4:3, 1:1, A4 или свой размер, поворот и зеркало. Несколько фото на одном листе: 10×15, 3×4, контрольный лист, метки реза.",
     ["Выберите пропорцию и двигайте рамку мышью", "Задайте раскладку листа и копии", "Кнопка «Лист» покажет готовый результат"], "sheet"),
    ("Редактор PDF",
     "Впишите текст прямо на странице, передвиньте или исправьте любую строку, заметьте область. Исходный файл не меняется.",
     ["Откройте «Редактировать PDF»", "Щёлкните по строке или добавьте надпись", "Конвертируется исправленная копия"], "pdf"),
    ("Печать с предпросмотром",
     "Принтер, бумага от A6 до A3 и 10×15, поля, копии, диапазон листов, чёрно-белая печать. Или сохраните результат в PDF.",
     ["Нажмите «Печать»", "Проверьте лист в предпросмотре", "Выберите принтер и отправьте"], "print"),
    ("Всё под рукой",
     "Тёмная и светлая темы, русский и английский язык. Новые версии выходят в группе vk.ru/icc_profil, проверка есть в «О программе».",
     ["Пуск → КопиТехник Конвертор", "Командная строка: Converter.exe --convert <из> <в>", "Удаление: Параметры → Приложения"], "ok"),
]
SLIDES_EN = [
    ("Any file in one window",
     "JPG, PNG, WebP, HEIC, PSD, PDF, SVG, Word, Excel, PowerPoint and ZIP. Drop a whole folder if you like.",
     ["Drag files or a folder into the window", "Pick a format: JPG, PNG, TIFF or PDF", "Press Convert"], "files"),
    ("Colour in one move",
     "Auto correction, white balance picker, brightness, contrast, saturation and colour channels. For all photos at once or for one.",
     ["Turn on auto correction or move the sliders", "The Original switch shows the difference", "Settings apply to every photo"], "color"),
    ("Crop and print sheet",
     "Crop 3:2, 4:3, 1:1, A4 or a custom size, rotate and mirror. Several photos per sheet: 10×15, ID photos, contact sheet, cut marks.",
     ["Pick a ratio and drag the frame", "Set the sheet layout and copies", "The Sheet button shows the result"], "sheet"),
    ("PDF editor",
     "Type onto the page, move or fix any line, erase an area. The original file stays untouched.",
     ["Open Edit PDF", "Click a line or add a text label", "The edited copy is converted"], "pdf"),
    ("Print with preview",
     "Printer, paper from A6 to A3 and 10×15, margins, copies, page ranges, black and white. Or save the result as PDF.",
     ["Press Print", "Check the sheet in the preview", "Choose a printer and send"], "print"),
    ("Everything at hand",
     "Dark and light themes, Russian and English. New versions appear in the group vk.ru/icc_profil; there is a check in About.",
     ["Start → KopiTehnik Converter", "Command line: Converter.exe --convert <in> <out>", "Remove: Settings → Apps"], "ok"),
]
if LANG is RU:
    SLIDES = SLIDES_RU
elif LANG is EN:
    SLIDES = SLIDES_EN
else:
    SLIDES = [(t, x, st, k) for (t, x, st), k in zip(_OTHER_SLIDES[_CODE], _KINDS)]


# ---------------------------------------------------------------- system work

def base_dir() -> Path:
    return Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent / "payload"


def default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / APP_NAME


def hidden_run(args, **kw):
    return subprocess.run(args, creationflags=0x08000000, capture_output=True, **kw)


def powershell(script: str):
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    return hidden_run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc])


def _q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def special_folders() -> tuple[Path, Path]:
    """Desktop and Start-menu Programs folders (they follow OneDrive and custom locations)."""
    out = powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                     "[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('Programs')")
    lines = out.stdout.decode("utf-8", "replace").strip().splitlines()
    if len(lines) >= 2 and lines[0].strip() and lines[1].strip():
        return Path(lines[0].strip()), Path(lines[1].strip())
    home = Path.home()
    return home / "Desktop", Path(os.environ.get("APPDATA", str(home))) / "Microsoft/Windows/Start Menu/Programs"


def start_folder(programs: Path) -> Path:
    return programs / "КопиТехник"


def make_shortcuts(target: Path, folder: Path, desktop: bool, start: bool):
    desk, programs = special_folders()
    items = []
    if desktop:
        items.append((desk / f"{APP_TITLE_RU}.lnk", target / EXE_NAME, ""))
    if start:
        sf = start_folder(programs)
        sf.mkdir(parents=True, exist_ok=True)
        items.append((sf / f"{APP_TITLE_RU}.lnk", target / EXE_NAME, ""))
        items.append((sf / "Удалить Конвертор.lnk", target / UNINSTALL_NAME, ""))
    script = "$s=New-Object -ComObject WScript.Shell;"
    for lnk, exe, args in items:
        script += (f"$l=$s.CreateShortcut({_q(lnk)});$l.TargetPath={_q(exe)};$l.WorkingDirectory={_q(target)};"
                   f"$l.IconLocation={_q(str(target / EXE_NAME) + ',0')};$l.Arguments={_q(args)};$l.Save();")
    if items:
        powershell(script)


def remove_shortcuts():
    desk, programs = special_folders()
    for lnk in (desk / f"{APP_TITLE_RU}.lnk",):
        lnk.unlink(missing_ok=True)
    shutil.rmtree(start_folder(programs), ignore_errors=True)


def folder_size_kb(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) // 1024


def register(target: Path):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_UNINSTALL) as k:
        def s(name, val):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, str(val))
        s("DisplayName", APP_TITLE_RU)
        s("DisplayVersion", VERSION)
        s("Publisher", PUBLISHER)
        s("InstallLocation", target)
        s("DisplayIcon", target / EXE_NAME)
        s("UninstallString", f'"{target / UNINSTALL_NAME}"')
        s("QuietUninstallString", f'"{target / UNINSTALL_NAME}" /S')
        s("URLInfoAbout", SITE)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, folder_size_kb(target))


def installed_dir() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_UNINSTALL) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def delete_key_tree(root, path: str):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                delete_key_tree(root, f"{path}\\{sub}")
        winreg.DeleteKey(root, path)
    except OSError:
        pass


class Worker(QObject):
    progress = Signal(int, str)     # percent, status text
    finished = Signal(str)          # empty = success, else error text

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def start(self):
        def run():
            try:
                self.fn(lambda p, s: self.progress.emit(p, s))
                self.finished.emit("")
            except PermissionError:
                self.finished.emit(tt("busy"))
            except Exception as e:  # shown to the user
                self.finished.emit(f"{e.__class__.__name__}: {e}")
        threading.Thread(target=run, daemon=True).start()


def do_install(target: Path, desktop: bool, start: bool, report):
    src = base_dir()
    target.mkdir(parents=True, exist_ok=True)
    report(2, tt("copy"))
    exe_src = src / EXE_NAME
    total = exe_src.stat().st_size
    done = 0
    tmp = target / (EXE_NAME + ".new")
    with open(exe_src, "rb") as fi, open(tmp, "wb") as fo:
        while chunk := fi.read(1 << 20):
            fo.write(chunk)
            done += len(chunk)
            report(2 + int(done / total * 80), tt("copy"))
    os.replace(tmp, target / EXE_NAME)      # PermissionError if the program is running
    for name in (UNINSTALL_NAME, "THIRD_PARTY_NOTICES.txt", "MCP.md", "icon.ico"):
        if (src / name).exists():
            shutil.copy2(src / name, target / name)
    report(86, tt("short"))
    make_shortcuts(target, target, desktop, start)
    report(95, tt("reg"))
    register(target)
    report(100, tt("done"))


def do_uninstall(target: Path, keep_data: bool, report):
    report(10, tt("un_run"))
    remove_shortcuts()
    report(40, tt("un_run"))
    exe = target / EXE_NAME
    if exe.exists():
        exe.unlink()                         # PermissionError if running
    for p in list(target.iterdir()) if target.exists() else []:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    try:
        target.rmdir()
    except OSError:
        pass
    report(75, tt("un_run"))
    delete_key_tree(winreg.HKEY_CURRENT_USER, REG_UNINSTALL)
    if not keep_data:
        delete_key_tree(winreg.HKEY_CURRENT_USER, REG_SETTINGS)
    report(100, tt("un_done"))


# ---------------------------------------------------------------- showcase (animated feature slides)

class Showcase(QWidget):
    """Slides about the program: an animated picture, a title, a text and three steps. Cross-fades."""
    changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 330)
        self.idx = 0
        self.prev = -1
        self.fade = 1.0
        self.t = 0.0
        self.auto = True
        self.tick = QTimer(self, interval=16)
        self.tick.timeout.connect(self._step)
        self.tick.start()
        self.since = 0.0
        self.anim = QVariantAnimation(self, duration=450, startValue=0.0, endValue=1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._on_fade)

    def _on_fade(self, v):
        self.fade = float(v)

    def _step(self):
        self.t += 0.016
        self.since += 0.016
        if self.auto and self.since > 6.5:
            self.go(self.idx + 1)
        self.update()

    def go(self, i: int, manual: bool = False):
        i %= len(SLIDES)
        if manual:
            self.auto = False
        if i == self.idx:
            return
        self.prev, self.idx, self.since = self.idx, i, 0.0
        self.anim.stop()
        self.anim.start()
        self.changed.emit(i)

    def mousePressEvent(self, e):
        w = self.width()
        n = len(SLIDES)
        y = self.height() - 16
        if e.position().y() > y - 12:       # dots
            x0 = w / 2 - (n - 1) * 11
            for i in range(n):
                if abs(e.position().x() - (x0 + i * 22)) < 11:
                    self.go(i, True)
                    return
        self.go(self.idx + (1 if e.position().x() > w / 2 else -1), True)

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self.fade < 1.0 and self.prev >= 0:
            p.setOpacity(1.0 - self.fade)
            self._slide(p, self.prev, w, h, -20 * self.fade)
        p.setOpacity(self.fade)
        self._slide(p, self.idx, w, h, 20 * (1 - self.fade))
        p.setOpacity(1.0)
        n = len(SLIDES)
        x0 = w / 2 - (n - 1) * 11
        for i in range(n):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ACCENT2 if i == self.idx else BORDER)
            r = 4.5 if i == self.idx else 3.5
            p.drawEllipse(QPointF(x0 + i * 22, h - 16), r, r)

    def _slide(self, p: QPainter, i: int, w: int, h: int, dx: float):
        title, text, steps, kind = SLIDES[i]
        p.save()
        p.translate(dx, 0)
        art = QRectF(24, 18, 250, 230)
        self._art(p, kind, art)
        x = 300
        tw = w - x - 24
        f = QFont("Segoe UI", 17, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(TEXT)
        p.drawText(QRectF(x, 20, tw, 70), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, title)
        p.setFont(QFont("Segoe UI", 10))
        p.setPen(MUTED)
        p.drawText(QRectF(x, 66, tw, 90), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, text)
        y = 162
        for n, st in enumerate(steps, 1):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(SOFT)
            p.drawEllipse(QPointF(x + 11, y + 14), 11, 11)
            p.setPen(ACCENT2)
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(QRectF(x, y + 3, 22, 22), Qt.AlignmentFlag.AlignCenter, str(n))
            p.setPen(TEXT)
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(QRectF(x + 30, y, tw - 30, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, st)
            y += 42
        p.restore()

    def _art(self, p: QPainter, kind: str, r: QRectF):
        t = self.t
        # soft stage
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor("#1c1840"))
        g.setColorAt(1, QColor("#14151d"))
        p.setPen(QPen(BORDER, 1))
        p.setBrush(g)
        p.drawRoundedRect(r, 18, 18)
        c = r.center()
        p.setPen(Qt.PenStyle.NoPen)
        cx, cy = c.x(), c.y()
        if kind == "files":
            for k, label in enumerate(("JPG", "DOC", "HEIC")):
                ph = (t * 0.5 + k / 3) % 1.0
                x = r.left() + 30 + ph * (cx - r.left() - 10)
                y = r.top() + 40 + k * 55 + math.sin(ph * math.pi) * -10
                self._card(p, QRectF(x - 24, y - 17, 48, 34), label, 1.0 - max(0.0, ph - 0.75) * 4)
            self._arrow(p, cx + 8, cy, t)
            self._card(p, QRectF(cx + 40, cy - 40, 64, 80), "PDF", 1.0, ACCENT)
        elif kind == "color":
            for k in range(3):
                yy = r.top() + 60 + k * 50
                grad = QLinearGradient(r.left() + 30, 0, r.right() - 30, 0)
                cols = [("#ef4444", "#22c55e"), ("#22c55e", "#3b82f6"), ("#3b82f6", "#f59e0b")][k]
                grad.setColorAt(0, QColor(cols[0]))
                grad.setColorAt(1, QColor(cols[1]))
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(r.left() + 30, yy, r.width() - 60, 8), 4, 4)
                kx = r.left() + 30 + (r.width() - 60) * (0.5 + 0.4 * math.sin(t * 1.3 + k * 1.7))
                p.setBrush(QColor("white"))
                p.drawEllipse(QPointF(kx, yy + 4), 9, 9)
        elif kind == "sheet":
            page = QRectF(cx - 70, r.top() + 18, 140, 194)
            p.setBrush(QColor("#f4f5fa"))
            p.drawRoundedRect(page, 4, 4)
            n = int(t * 3) % 8 + 1
            for i in range(8):
                col, row = i % 2, i // 2
                cell = QRectF(page.left() + 12 + col * 60, page.top() + 12 + row * 44, 54, 38)
                if i < n:
                    gg = QLinearGradient(cell.topLeft(), cell.bottomRight())
                    gg.setColorAt(0, QColor("#7c5cff"))
                    gg.setColorAt(1, QColor("#22d3ee"))
                    p.setBrush(gg)
                else:
                    p.setBrush(QColor("#dfe1ea"))
                p.drawRoundedRect(cell, 3, 3)
            p.setPen(QPen(QColor("#f43f5e"), 1.2))
            for k in range(2):
                p.drawLine(QPointF(page.left() - 5, page.top() + 8 + k * 178), QPointF(page.left() + 2, page.top() + 8 + k * 178))
            p.setPen(Qt.PenStyle.NoPen)
        elif kind == "pdf":
            page = QRectF(cx - 80, r.top() + 18, 160, 194)
            p.setBrush(QColor("#f4f5fa"))
            p.drawRoundedRect(page, 4, 4)
            for k in range(7):
                y = page.top() + 24 + k * 22
                wd = 120 if k % 3 else 90
                hot = k == 3
                p.setBrush(QColor("#c9ccd9"))
                p.drawRoundedRect(QRectF(page.left() + 16, y, wd, 7), 3, 3)
            hy = page.top() + 24 + 3 * 22
            p.setBrush(QColor(124, 92, 255, 90))
            p.drawRoundedRect(QRectF(page.left() + 10 + 6 * math.sin(t * 2), hy - 5, 132, 17), 5, 5)
            p.setPen(QPen(ACCENT, 2))
            if int(t * 2) % 2 == 0:
                p.drawLine(QPointF(page.left() + 146, hy - 3), QPointF(page.left() + 146, hy + 9))
            p.setPen(Qt.PenStyle.NoPen)
        elif kind == "print":
            p.setBrush(QColor("#2b2d3b"))
            p.drawRoundedRect(QRectF(cx - 70, cy - 10, 140, 70), 12, 12)
            sheet_h = 70 * (0.5 - 0.5 * math.cos((t * 0.6 % 1.0) * 2 * math.pi))
            p.setBrush(QColor("#f4f5fa"))
            p.drawRect(QRectF(cx - 45, cy + 52 - sheet_h + 10, 90, sheet_h))
            p.setBrush(QColor("#f4f5fa"))
            p.drawRect(QRectF(cx - 40, cy - 70, 80, 62))
            p.setBrush(GREEN)
            p.drawEllipse(QPointF(cx + 54, cy + 8), 4, 4)
        else:  # ok
            prog = min(1.0, (t * 0.5) % 1.6)
            p.setBrush(QColor(34, 197, 94, 40))
            p.drawEllipse(c, 70 + 6 * math.sin(t * 2), 70 + 6 * math.sin(t * 2))
            p.setBrush(GREEN)
            p.drawEllipse(c, 52, 52)
            p.setPen(QPen(QColor("white"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            pts = [QPointF(cx - 22, cy + 2), QPointF(cx - 6, cy + 18), QPointF(cx + 24, cy - 16)]
            path = QPainterPath(pts[0])
            path.lineTo(pts[1])
            path.lineTo(pts[2])
            visible = QPainterPath()
            visible.addRect(QRectF(cx - 40, cy - 40, 80 * min(1.0, prog * 1.4), 80))
            p.setClipPath(visible)
            p.drawPath(path)
            p.setClipping(False)
            p.setPen(Qt.PenStyle.NoPen)

    def _card(self, p, rect, label, alpha, color=None):
        p.save()
        p.setOpacity(p.opacity() * max(0.0, min(1.0, alpha)))
        p.setBrush(color or QColor("#2b2d3b"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(QColor("white"))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        p.restore()

    def _arrow(self, p, x, y, t):
        p.setPen(QPen(ACCENT2, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        o = 4 * math.sin(t * 4)
        p.drawLine(QPointF(x - 8 + o, y), QPointF(x + 14 + o, y))
        p.drawLine(QPointF(x + 8 + o, y - 6), QPointF(x + 14 + o, y))
        p.drawLine(QPointF(x + 8 + o, y + 6), QPointF(x + 14 + o, y))
        p.setPen(Qt.PenStyle.NoPen)


# ---------------------------------------------------------------- window

QSS = f"""
QLabel {{ color: {TEXT.name()}; font-family: 'Segoe UI'; }}
QLabel#sub {{ color: {MUTED.name()}; }}
QLabel#title {{ font-size: 24px; font-weight: 600; }}
QLineEdit {{ background: {SURFACE.name()}; color: {TEXT.name()}; border: 1px solid {BORDER.name()}; border-radius: 8px; padding: 8px 10px; font-size: 13px; }}
QCheckBox {{ color: {TEXT.name()}; font-size: 13px; spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER.name()}; background: {SURFACE.name()}; }}
QCheckBox::indicator:checked {{ background: {ACCENT.name()}; border-color: {ACCENT.name()}; }}
QPushButton {{ background: {SURFACE.name()}; color: {TEXT.name()}; border: 1px solid {BORDER.name()}; border-radius: 9px; padding: 9px 20px; font-size: 13px; }}
QPushButton:hover {{ border-color: {ACCENT2.name()}; }}
QPushButton#primary {{ background: {ACCENT.name()}; border-color: {ACCENT.name()}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT2.name()}; }}
QPushButton#primary:disabled {{ background: {SURFACE.name()}; color: {MUTED.name()}; border-color: {BORDER.name()}; }}
QProgressBar {{ background: {SURFACE.name()}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENT.name()}, stop:1 #22d3ee); }}
"""


class Logo(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(56, 56)
        self.t = 0.0
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self):
        self.t += 0.033
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 56, 56)
        s = 0.5 + 0.5 * math.sin(self.t * 1.2)
        g.setColorAt(0, ACCENT)
        g.setColorAt(s, QColor("#22d3ee"))
        g.setColorAt(1, ACCENT2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(2, 2 + 2 * math.sin(self.t * 2), 52, 52), 14, 14)
        p.setPen(QColor("white"))
        p.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        p.drawText(QRectF(2, 2 + 2 * math.sin(self.t * 2), 52, 52), Qt.AlignmentFlag.AlignCenter, "К")


class Window(QWidget):
    def __init__(self, mode: str, target: Path | None = None, stage2: bool = False):
        super().__init__()
        self.mode = mode
        self.stage2 = stage2
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(760, 500)
        self.setWindowTitle(tt("title"))
        ico = base_dir() / "icon.ico"
        if ico.exists():
            self.setWindowIcon(QIcon(str(ico)))
        self.setStyleSheet(QSS)
        self._drag = None
        self.target = target or default_dir()
        self.error = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(22, 14, 12, 0)
        cap = QLabel(tt("title"))
        cap.setObjectName("sub")
        bar.addWidget(cap)
        bar.addStretch(1)
        x = QPushButton("✕")
        x.setFixedSize(34, 30)
        x.setStyleSheet("QPushButton{border:none;background:transparent;color:#8a8fa3;padding:0}QPushButton:hover{color:white;background:#f43f5e}")
        x.clicked.connect(self.close)
        bar.addWidget(x)
        outer.addLayout(bar)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.stack.addWidget(self._page_start())
        self.stack.addWidget(self._page_work())
        self.stack.addWidget(self._page_done())

    # ---- pages
    def _page_start(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(48, 10, 48, 28)
        head = QHBoxLayout()
        head.setSpacing(18)
        head.addWidget(Logo())
        tv = QVBoxLayout()
        title = QLabel(tt("welcome") if self.mode == "install" else tt("un_title"))
        title.setObjectName("title")
        sub = QLabel(tt("welcome_sub") if self.mode == "install" else tt("un_sub"))
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        tv.addWidget(title)
        tv.addWidget(sub)
        head.addLayout(tv, 1)
        v.addLayout(head)
        v.addSpacing(28)
        self.chk_desk = QCheckBox(tt("desk"))
        self.chk_start = QCheckBox(tt("start"))
        self.chk_desk.setChecked(True)
        self.chk_start.setChecked(True)
        if self.mode == "install":
            lab = QLabel(tt("folder"))
            lab.setObjectName("sub")
            v.addWidget(lab)
            row = QHBoxLayout()
            self.path = QLineEdit(str(self.target))
            b = QPushButton(tt("browse"))
            b.clicked.connect(self._browse)
            row.addWidget(self.path, 1)
            row.addWidget(b)
            v.addLayout(row)
            v.addSpacing(14)
            v.addWidget(self.chk_desk)
            v.addSpacing(6)
            v.addWidget(self.chk_start)
            v.addStretch(1)
            note = QLabel(tt("notice"))
            note.setObjectName("sub")
            note.setWordWrap(True)
            v.addWidget(note)
        else:
            self.chk_data = QCheckBox(tt("un_data"))
            v.addWidget(self.chk_data)
            v.addStretch(1)
        v.addSpacing(10)
        row = QHBoxLayout()
        row.addStretch(1)
        c = QPushButton(tt("cancel"))
        c.clicked.connect(self.close)
        self.go = QPushButton(tt("install") if self.mode == "install" else tt("un_btn"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._begin)
        row.addWidget(c)
        row.addWidget(self.go)
        v.addLayout(row)
        return w

    def _page_work(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(36, 0, 36, 26)
        self.show_case = Showcase()
        self.work_title = QLabel(tt("installing") if self.mode == "install" else tt("un_run"))
        self.work_title.setObjectName("sub")
        if self.mode == "install":
            v.addWidget(self.show_case, 1)
        else:
            v.addStretch(1)
            big = Logo()
            v.addWidget(big, 0, Qt.AlignmentFlag.AlignHCenter)
            v.addStretch(1)
        v.addWidget(self.work_title)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        v.addSpacing(10)
        row = QHBoxLayout()
        self.hint = QLabel("")
        self.hint.setObjectName("sub")
        row.addWidget(self.hint, 1)
        self.retry = QPushButton(tt("retry"))
        self.retry.hide()
        self.retry.clicked.connect(self._begin)
        self.next_btn = QPushButton(tt("next"))
        self.next_btn.setObjectName("primary")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(lambda: self.stack.setCurrentIndex(2))
        row.addWidget(self.retry)
        row.addWidget(self.next_btn)
        v.addLayout(row)
        return w

    def _page_done(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(48, 20, 48, 28)
        v.addStretch(1)
        self.done_logo = QLabel("✓")
        self.done_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_logo.setFixedSize(84, 84)
        self.done_logo.setStyleSheet("background:#22c55e;color:white;border-radius:42px;font-size:44px;font-weight:700")
        v.addWidget(self.done_logo, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(18)
        self.done_title = QLabel(tt("done") if self.mode == "install" else tt("un_done"))
        self.done_title.setObjectName("title")
        self.done_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_sub = QLabel(tt("done_sub") if self.mode == "install" else tt("un_done_sub"))
        self.done_sub.setObjectName("sub")
        self.done_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_sub.setWordWrap(True)
        v.addWidget(self.done_title)
        v.addWidget(self.done_sub)
        v.addSpacing(18)
        self.chk_run = QCheckBox(tt("run"))
        self.chk_run.setChecked(True)
        if self.mode == "install":
            v.addWidget(self.chk_run, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        fin = QPushButton(tt("finish"))
        fin.setObjectName("primary")
        fin.clicked.connect(self._finish)
        row.addWidget(fin)
        v.addLayout(row)
        return w

    # ---- logic
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tt("folder"), self.path.text())
        if d:
            p = Path(d)
            self.path.setText(str(p if p.name.lower() == APP_NAME.lower() else p / APP_NAME))

    def _begin(self):
        self.retry.hide()
        self.bar.setValue(0)
        self.work_title.setText(tt("installing") if self.mode == "install" else tt("un_run"))
        self.work_title.setStyleSheet("")
        self.hint.setText("")
        self.stack.setCurrentIndex(1)
        if self.mode == "install":
            target = Path(self.path.text().strip() or str(default_dir()))
            self.target = target
            d, s = self.chk_desk.isChecked(), self.chk_start.isChecked()
            fn = lambda rep: do_install(target, d, s, rep)
        else:
            keep = not self.chk_data.isChecked()
            fn = lambda rep: do_uninstall(self.target, keep, rep)
        self.worker = Worker(fn)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._ended)
        self.worker.start()

    def _progress(self, pct, text):
        self.bar.setValue(pct)
        self.work_title.setText(text)

    def _ended(self, err):
        if err:
            self.work_title.setText(f"{tt('err')}: {err}")
            self.work_title.setStyleSheet(f"color:{RED.name()}")
            self.retry.show()
            return
        self.bar.setValue(100)
        if self.mode == "install":
            self.hint.setText(tt("ready_hint"))
            self.next_btn.setEnabled(True)
        else:
            self.stack.setCurrentIndex(2)

    def _finish(self):
        if self.mode == "install" and self.chk_run.isChecked():
            subprocess.Popen([str(self.target / EXE_NAME)], cwd=str(self.target), close_fds=True)
        self.close()

    def closeEvent(self, e):
        if self.mode == "uninstall" and self.stage2:
            schedule_self_delete()
        e.accept()

    # ---- window chrome
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor("#15132b"))
        g.setColorAt(0.5, BG)
        g.setColorAt(1, QColor("#0b0c10"))
        p.setPen(QPen(BORDER, 1))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 16, 16)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 52:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


def schedule_self_delete():
    """A staged uninstaller runs from %TEMP%; remove it once the process has exited."""
    me = sys.executable
    subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & del /f /q "{me}"', shell=True, creationflags=0x08000000,
                     close_fds=True)


# ---------------------------------------------------------------- entry

def main() -> int:
    args = sys.argv[1:]
    low = [a.lower() for a in args]
    silent = "/s" in low
    uninstall = "--uninstall" in low or Path(sys.executable).name.lower() == UNINSTALL_NAME.lower()
    target = None
    for a in args:
        if a.upper().startswith("/D="):
            target = Path(a[3:].strip('"'))

    if uninstall:
        stage2 = "--stage2" in low
        if "--stage2" in low:
            target = Path(args[low.index("--stage2") + 1])
        else:
            target = target or installed_dir() or Path(sys.executable).parent
            # run from a copy in %TEMP% so the install folder (and this exe) can be deleted
            tmpexe = Path(tempfile.gettempdir()) / f"kt_uninstall_{os.getpid()}.exe"
            shutil.copy2(sys.executable, tmpexe)
            extra = ["/S"] if silent else []
            extra += ["/KEEPDATA"] if "/keepdata" in low else []
            subprocess.Popen([str(tmpexe), "--uninstall", "--stage2", str(target), *extra], close_fds=True)
            return 0
        sys._staged = True
        if silent:
            try:
                do_uninstall(target, "/keepdata" in low, lambda p, s: None)
            except PermissionError:
                schedule_self_delete()
                return 1
            schedule_self_delete()
            return 0
        app = QApplication(sys.argv)
        app.setFont(QFont("Segoe UI", 10))
        win = Window("uninstall", target, stage2=True)
        win.show()
        return app.exec()

    if silent:
        t = target or installed_dir() or default_dir()
        try:
            do_install(t, "/nodesktop" not in low, "/nostart" not in low, lambda p, s: None)
        except PermissionError:
            print(tt("busy"))
            return 1
        return 0

    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    win = Window("install", target or installed_dir())
    if "--shots" in low:
        return shots(app, win, Path(args[low.index("--shots") + 1]))
    win.show()
    return app.exec()


def shots(app, win, out: Path) -> int:
    """Debug: save screenshots of the pages and slides."""
    out.mkdir(parents=True, exist_ok=True)
    win.show()
    app.processEvents()
    win.grab().save(str(out / "1_start.png"))
    win.stack.setCurrentIndex(1)
    for i in range(len(SLIDES)):
        win.show_case.go(i, True)
        win.show_case.t = 1.3 + i
        win.bar.setValue(40 + i * 10)
        win.show_case.anim.setCurrentTime(450)
        app.processEvents()
        win.grab().save(str(out / f"2_slide{i}.png"))
    win.stack.setCurrentIndex(2)
    app.processEvents()
    win.grab().save(str(out / "3_done.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
