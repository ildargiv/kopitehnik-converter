"""Office documents (Word, PowerPoint, Excel, OpenDocument) through an office engine.

Two engines are supported:
- Microsoft Office, driven through COM with a small VBScript (no extra Python packages);
- LibreOffice, either installed on the computer or shipped next to the program
  in a ``LibreOffice`` folder (the "full" build).

Every engine turns the document into a PDF; pages are then rendered like any PDF.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

WORD_EXTS = {".doc", ".docx", ".docm", ".dot", ".dotx", ".rtf", ".odt", ".wps"}
SLIDE_EXTS = {".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".odp"}
SHEET_EXTS = {".xls", ".xlsx", ".xlsm", ".ods"}
OFFICE_EXTS = WORD_EXTS | SLIDE_EXTS | SHEET_EXTS

ENGINE_AUTO, ENGINE_MS, ENGINE_LO = "auto", "msoffice", "libreoffice"
TIMEOUT = 300  # seconds for one document

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_lock = threading.Lock()  # office engines do not like parallel conversions
_preference = ENGINE_AUTO
_custom_lo: str | None = None  # soffice.exe chosen by hand in the "Programs" window
_cache: "Programs | None" = None


class OfficeError(Exception):
    pass


# --------------------------------------------------------------------------- detection

@dataclass
class Programs:
    word: bool = False
    powerpoint: bool = False
    excel: bool = False
    lo_installed: str | None = None   # path to soffice.exe
    lo_bundled: str | None = None
    lo_custom: str | None = None
    sevenzip: str | None = None
    winrar: str | None = None
    pymupdf: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def libreoffice(self) -> str | None:
        """A hand-picked copy wins, then the installed one (usually newer than the bundled copy)."""
        return self.lo_custom or self.lo_installed or self.lo_bundled

    @property
    def any_office(self) -> bool:
        return bool(self.word or self.powerpoint or self.excel or self.libreoffice)


def _reg_has(progid: str) -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\CLSID"):
            return True
    except OSError:
        return False


def _program_dirs() -> list[Path]:
    dirs = []
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        v = os.environ.get(env)
        if v and Path(v) not in dirs:
            dirs.append(Path(v))
    return dirs


def _find_installed_lo() -> str | None:
    try:
        import winreg

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (0, getattr(winreg, "KEY_WOW64_32KEY", 0)):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\LibreOffice\UNO\InstallPath", 0,
                                        winreg.KEY_READ | view) as k:
                        p = Path(winreg.QueryValueEx(k, "")[0]) / "soffice.exe"
                        if p.exists():
                            return str(p)
                except OSError:
                    continue
    except ImportError:
        pass
    for base in _program_dirs():
        for rel in ("LibreOffice/program/soffice.exe", "Programs/LibreOffice/program/soffice.exe"):
            p = base / rel
            if p.exists():
                return str(p)
    hit = shutil.which("soffice")
    return hit


def app_dir() -> Path:
    """Folder of the exe (or of app.py when running from source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _find_bundled_lo() -> str | None:
    roots = [app_dir()]
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS))
    for root in roots:
        for name in ("LibreOffice", "libreoffice", "LibreOfficePortable/App/libreoffice"):
            p = root / name / "program" / "soffice.exe"
            if p.exists():
                return str(p)
    return None


def _find_exe(rel_paths: list[str], names: list[str]) -> str | None:
    for base in _program_dirs():
        for rel in rel_paths:
            p = base / rel
            if p.exists():
                return str(p)
    for n in names:
        hit = shutil.which(n)
        if hit:
            return hit
    return None


def detect(refresh: bool = False) -> Programs:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    try:
        import pymupdf  # noqa: F401

        has_mupdf = True
    except ImportError:
        has_mupdf = False
    _cache = Programs(
        word=_reg_has("Word.Application"),
        powerpoint=_reg_has("PowerPoint.Application"),
        excel=_reg_has("Excel.Application"),
        lo_installed=_find_installed_lo(),
        lo_bundled=_find_bundled_lo(),
        lo_custom=_custom_lo if _custom_lo and Path(_custom_lo).exists() else None,
        sevenzip=_find_exe(["7-Zip/7z.exe"], ["7z"]),
        winrar=_find_exe(["WinRAR/UnRAR.exe", "WinRAR/WinRAR.exe"], ["unrar", "winrar"]),
        pymupdf=has_mupdf,
    )
    return _cache


def set_preference(engine: str) -> None:
    global _preference
    _preference = engine if engine in (ENGINE_AUTO, ENGINE_MS, ENGINE_LO) else ENGINE_AUTO


def get_preference() -> str:
    return _preference


def set_custom_libreoffice(path: str | None) -> None:
    """Use this soffice.exe (or the soffice.exe inside this folder); None forgets it."""
    global _custom_lo
    if path:
        p = Path(path)
        for cand in (p, p / "soffice.exe", p / "program" / "soffice.exe"):
            if cand.is_file() and cand.name.lower() == "soffice.exe":
                _custom_lo = str(cand)
                break
        else:
            raise OfficeError("в этой папке нет soffice.exe")
    else:
        _custom_lo = None
    detect(refresh=True)


def _ms_app_for(ext: str, progs: Programs) -> str | None:
    if ext in WORD_EXTS and progs.word:
        return "word"
    if ext in SLIDE_EXTS and progs.powerpoint:
        return "powerpoint"
    if ext in SHEET_EXTS and progs.excel:
        return "excel"
    return None


def engine_for(path: Path) -> str | None:
    """Which engine will convert ``path``: "msoffice", "libreoffice" or None."""
    progs = detect()
    ext = path.suffix.lower()
    ms = _ms_app_for(ext, progs)
    lo = progs.libreoffice
    if _preference == ENGINE_LO or (_preference == ENGINE_AUTO and ext in (".odt", ".odp", ".ods")):
        order = [ENGINE_LO, ENGINE_MS]   # OpenDocument files look best in LibreOffice
    else:
        order = [ENGINE_MS, ENGINE_LO]
    for e in order:
        if e == ENGINE_MS and ms:
            return ENGINE_MS
        if e == ENGINE_LO and lo:
            return ENGINE_LO
    return None


def can_convert(path: Path) -> bool:
    return path.suffix.lower() in OFFICE_EXTS and engine_for(path) is not None


# --------------------------------------------------------------------------- conversion

_VBS = {
    "word": r'''
Set app = CreateObject("Word.Application")
app.Visible = False
app.DisplayAlerts = 0
On Error Resume Next
Set doc = app.Documents.Open(WScript.Arguments(0), False, True, False)
If Err.Number <> 0 Then
  WScript.StdErr.Write Err.Description
  app.Quit 0
  WScript.Quit 2
End If
doc.ExportAsFixedFormat WScript.Arguments(1), 17
rc = Err.Number
doc.Close 0
app.Quit 0
If rc <> 0 Then WScript.Quit 3
''',
    "powerpoint": r'''
Set app = CreateObject("PowerPoint.Application")
On Error Resume Next
Set pres = app.Presentations.Open(WScript.Arguments(0), True, False, False)
If Err.Number <> 0 Then
  WScript.StdErr.Write Err.Description
  app.Quit
  WScript.Quit 2
End If
pres.SaveAs WScript.Arguments(1), 32
rc = Err.Number
pres.Close
app.Quit
If rc <> 0 Then WScript.Quit 3
''',
    "excel": r'''
Set app = CreateObject("Excel.Application")
app.Visible = False
app.DisplayAlerts = False
On Error Resume Next
Set wb = app.Workbooks.Open(WScript.Arguments(0), 0, True)
If Err.Number <> 0 Then
  WScript.StdErr.Write Err.Description
  app.Quit
  WScript.Quit 2
End If
wb.ExportAsFixedFormat 0, WScript.Arguments(1)
rc = Err.Number
wb.Close False
app.Quit
If rc <> 0 Then WScript.Quit 3
''',
}


def _convert_ms(src: Path, pdf: Path, app: str) -> None:
    script = pdf.parent / f"{app}.vbs"
    script.write_text(_VBS[app], encoding="utf-16")  # cscript reads UTF-16 with BOM, keeps Cyrillic paths
    cmd = ["cscript.exe", "//NoLogo", str(script), str(src.resolve()), str(pdf)]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise OfficeError("Microsoft Office не ответил вовремя") from exc
    if res.returncode != 0 or not pdf.exists():
        err = (res.stderr or b"").decode("cp866", errors="replace").strip()
        raise OfficeError(f"Microsoft Office не смог открыть файл{': ' + err if err else ''}")


def _convert_lo(src: Path, out_dir: Path, soffice: str) -> Path:
    profile = out_dir / "lo_profile"
    cmd = [
        soffice, "--headless", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to", "pdf", "--outdir", str(out_dir), str(src.resolve()),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise OfficeError("LibreOffice не ответил вовремя") from exc
    pdf = out_dir / (src.stem + ".pdf")
    if not pdf.exists():
        err = (res.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        raise OfficeError("LibreOffice не смог открыть файл" + (f": {err[-1]}" if err else ""))
    return pdf


def to_pdf(src: Path, dest: Path) -> str:
    """Convert an office document to ``dest`` (a PDF). Returns the engine used."""
    engine = engine_for(src)
    if engine is None:
        raise OfficeError("нужен Microsoft Office или LibreOffice (меню «Программы»)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="kt_office_"))
    try:
        with _lock:
            if engine == ENGINE_MS:
                pdf = tmp / "out.pdf"
                _convert_ms(src, pdf, _ms_app_for(src.suffix.lower(), detect()))
            else:
                # LibreOffice names the PDF after the source; copy the source to a safe name first.
                safe = tmp / ("doc" + src.suffix.lower())
                shutil.copyfile(src, safe)
                pdf = _convert_lo(safe, tmp, detect().libreoffice)
        shutil.move(str(pdf), str(dest))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return engine


_session_dir: Path | None = None
_pdf_cache: dict[tuple[str, float, str], Path] = {}
_cache_lock = threading.Lock()
_key_locks: dict[tuple[str, float, str], threading.Lock] = {}
_next_name = 0


def cached_pdf(path: Path) -> Path:
    """PDF made from ``path``, converted once per session (preview and conversion share it)."""
    global _session_dir
    st = path.stat()
    key = (str(path.resolve()).lower(), st.st_mtime, engine_for(path) or "")
    global _next_name
    with _cache_lock:
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:  # the same file asked twice at once (preview + conversion) is converted once
        with _cache_lock:
            hit = _pdf_cache.get(key)
            if hit and hit.exists():
                return hit
            if _session_dir is None:
                _session_dir = Path(tempfile.mkdtemp(prefix="kt_session_"))
                import atexit

                atexit.register(shutil.rmtree, _session_dir, True)
            # A unique name per conversion: parallel threads must never share an output file.
            dest = _session_dir / f"{_next_name}.pdf"
            _next_name += 1
        to_pdf(path, dest)
        with _cache_lock:
            _pdf_cache[key] = dest
        return dest


def load_office(path: Path, dpi: int, max_pages: int | None, render_pdf) -> list:
    """Render an office document page by page with ``render_pdf(pdf_path, dpi, max_pages)``."""
    return render_pdf(cached_pdf(path), dpi, max_pages)
