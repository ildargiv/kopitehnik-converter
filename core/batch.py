"""Finding input files, unpacking archives and converting a batch."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .imaging import EXTENSIONS, ColorSettings, JobSettings, apply_color, apply_frame, save_image, save_images
from .office import OFFICE_EXTS, cached_pdf
from .sheet import compose, fit_photo, geometry, photo_area
from .loaders import ARCHIVE_EXTS, SUPPORTED_EXTS, LoadError, is_photo, load_pages


@dataclass
class SourceFile:
    path: Path
    root: Path | None = None   # folder the relative output path is computed from
    label: str = ""            # what to show in the UI (relative path)

    def __post_init__(self):
        if not self.label:
            try:
                self.label = str(self.path.relative_to(self.root)) if self.root else self.path.name
            except ValueError:
                self.label = self.path.name


def scan_folder(folder: Path) -> list[SourceFile]:
    """All supported files and archives under ``folder``, sorted by path."""
    if not folder or not folder.is_dir():
        return []
    found = []
    wanted = SUPPORTED_EXTS | ARCHIVE_EXTS
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames, key=str.lower):
            p = Path(dirpath) / name
            if p.suffix.lower() in wanted and not name.startswith("~$"):
                found.append(SourceFile(p, folder))
    return found


# --------------------------------------------------------------------------- archives

def _find_tool(names: list[str]) -> str | None:
    for name in names:
        hit = shutil.which(name)
        if hit:
            return hit
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(env)
        if not base:
            continue
        for rel in ("7-Zip/7z.exe", "WinRAR/UnRAR.exe", "WinRAR/WinRAR.exe"):
            p = Path(base) / rel
            if p.exists() and p.name.lower().split(".")[0] in [n.lower() for n in names]:
                return str(p)
    return None


def _zip_name(info: zipfile.ZipInfo) -> str:
    # Archives made by Windows Explorer store Cyrillic names in cp866 without the UTF-8 flag.
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp866")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def extract_archive(archive: Path, dest: Path) -> None:
    ext = archive.suffix.lower()
    dest.mkdir(parents=True, exist_ok=True)
    if ext == ".zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = _zip_name(info).replace("\\", "/")
                target = (dest / name).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    continue  # skip entries that try to escape the folder
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        return
    seven = _find_tool(["7z"])
    if seven:
        cmd = [seven, "x", "-y", f"-o{dest}", str(archive)]
    else:
        rar = _find_tool(["unrar", "winrar"]) if ext == ".rar" else None
        if not rar:
            raise LoadError("для RAR и 7z нужен установленный 7-Zip или WinRAR")
        cmd = [rar, "x", "-y", "-ibck", str(archive), str(dest) + os.sep]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    res = subprocess.run(cmd, capture_output=True, creationflags=flags, timeout=600)
    if res.returncode not in (0, 1):
        raise LoadError(f"архив не распаковался (код {res.returncode})")


# --------------------------------------------------------------------------- one file, ready pages

def process_file(path: Path, settings: JobSettings, dpi: int | None = None, read_from: Path | None = None) -> list:
    """Load ``path`` (or the edited copy ``read_from``) and apply frame and colour, as conversion does."""
    s = settings
    dpi = dpi or s.output.dpi
    pages = load_pages(read_from or path, dpi=dpi)
    offset = s.offsets.get(str(path), (0.0, 0.0))
    frame = s.frame if is_photo(path) else replace(s.frame, ratio="original")
    angle, crop = s.angles.get(str(path), 0.0), s.crops.get(str(path))
    return [apply_color(apply_frame(p, frame, offset, dpi=dpi, angle=angle, crop=crop), s.color_for(path))
            for p in pages]


# --------------------------------------------------------------------------- conversion

@dataclass
class BatchResult:
    converted: int = 0         # source files converted successfully
    pages: int = 0             # output files written
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


class Batch:
    """Converts a list of files. Callbacks are called from worker threads."""

    def __init__(
        self,
        files: list[SourceFile],
        out_dir: Path,
        settings: JobSettings,
        on_progress: Callable[[int, int, str], None] | None = None,
        on_log: Callable[[str, str], None] | None = None,
        on_file: Callable[[str, bool, str], None] | None = None,
        workers: int | None = None,
    ):
        self.files = files
        self.out_dir = out_dir
        self.settings = settings
        self.on_progress = on_progress or (lambda done, total, name: None)
        self.on_log = on_log or (lambda level, msg: None)
        # Called once per converted or failed file: (label, ok, pages or error text)
        self.on_file = on_file or (lambda label, ok, info: None)
        self.workers = workers or max(1, min(6, (os.cpu_count() or 2) - 1))
        self._stop = threading.Event()
        self._names_lock = threading.Lock()
        self._used_names: set[str] = set()
        self._sheet_items: dict[tuple[int, int], tuple[str, object]] = {}
        self._pdf_parts: dict[int, Path] = {}  # PDF output: one file per source, in list order

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # ---------------------------------------------------------------- naming

    def _target(self, src: SourceFile, rel_prefix: Path, page: int, pages: int) -> Path:
        ext = EXTENSIONS[self.settings.output.fmt]
        rel_dir = Path()
        if self.settings.output.keep_structure and src.root:
            try:
                rel_dir = src.path.parent.relative_to(src.root)
            except ValueError:
                pass
        stem = src.path.stem
        suffix = f"_p{page + 1:03d}" if pages > 1 else ""
        base = self.out_dir / rel_prefix / rel_dir
        candidate = base / f"{stem}{suffix}{ext}"
        with self._names_lock:
            # photo.png and photo.jpg in one folder must not overwrite each other.
            if str(candidate).lower() in self._used_names:
                candidate = base / f"{stem}_{src.path.suffix.lstrip('.').lower()}{suffix}{ext}"
            n = 2
            while str(candidate).lower() in self._used_names:
                candidate = base / f"{stem}_{n}{suffix}{ext}"
                n += 1
            self._used_names.add(str(candidate).lower())
        return candidate

    # ---------------------------------------------------------------- work

    def _source_pdf(self, src: SourceFile) -> Path | None:
        """The document's own PDF when it can be passed through untouched (text stays text)."""
        s = self.settings
        f = s.frame
        if s.sheet.enabled or f.rotate or f.mirror_h or f.mirror_v or s.color_for(src.path) != ColorSettings():
            return None
        ext = src.path.suffix.lower()
        if ext == ".pdf" or str(src.path) in s.replacements:
            return self.source_path(src)
        if ext in OFFICE_EXTS:
            return cached_pdf(src.path)
        return None

    def source_path(self, src: SourceFile) -> Path:
        """The file to read: an edited copy from the PDF editor replaces the original."""
        edited = self.settings.replacements.get(str(src.path))
        return Path(edited) if edited and Path(edited).exists() else src.path

    def _convert_one(self, src: SourceFile, rel_prefix: Path = Path(), index: int = 0) -> int:
        s = self.settings
        if s.output.fmt == "PDF":
            ready = self._source_pdf(src)
            if ready is not None:
                target = self._target(src, rel_prefix, 0, 1)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ready, target)
                self._pdf_parts[index] = target
                return 1
        pages = load_pages(self.source_path(src), dpi=s.output.dpi)
        if not pages:
            raise LoadError("в файле нет страниц")
        offset = s.offsets.get(str(src.path), (0.0, 0.0))
        # Crop presets are for photos; document pages keep their paper format.
        frame = s.frame if is_photo(src.path) else replace(s.frame, ratio="original")
        written = 0
        as_pdf = s.output.fmt == "PDF" and not s.sheet.enabled
        done: list = []
        for i, page in enumerate(pages):
            if self.stopped:
                break
            img = apply_frame(page, frame, offset, dpi=s.output.dpi, angle=s.angles.get(str(src.path), 0.0),
                              crop=s.crops.get(str(src.path)))
            img = apply_color(img, s.color_for(src.path))
            pages[i] = None  # free the full-size page early
            if as_pdf:
                done.append(img)  # every page of a file goes into one PDF
            elif s.sheet.enabled:
                # Keep only a cell-sized copy; the sheet is composed once everything is done.
                _, cell, _ = geometry(s.sheet, s.output.dpi)
                label = src.path.stem if len(pages) == 1 else f"{src.path.stem} {i + 1}"
                small = fit_photo(img, photo_area(s.sheet, cell, s.output.dpi), s.sheet)
                self._sheet_items[(index, i)] = (label, small)
            else:
                save_image(img, self._target(src, rel_prefix, i, len(pages)), s.output)
            written += 1
        if as_pdf and done:
            target = self._target(src, rel_prefix, 0, 1)
            save_images(done, target, s.output)
            self._pdf_parts[index] = target
            return 1
        return written

    def _expand_archives(self, tmp: Path) -> list[tuple[SourceFile, Path]]:
        """Replace archives with the files inside them."""
        jobs: list[tuple[SourceFile, Path]] = []
        for src in self.files:
            if src.path.suffix.lower() not in ARCHIVE_EXTS:
                jobs.append((src, Path()))
                continue
            dest = tmp / f"{len(jobs)}_{src.path.stem}"
            try:
                self.on_log("info", f"Распаковка {src.label}")
                extract_archive(src.path, dest)
            except Exception as exc:
                self.on_log("error", f"{src.label}: {exc}")
                self._result.failed.append((src.label, str(exc)))
                self.on_file(src.label, False, str(exc))
                continue
            rel_dir = Path()
            if src.root:
                try:
                    rel_dir = src.path.parent.relative_to(src.root)
                except ValueError:
                    pass
            inner = scan_folder(dest)
            inner = [f for f in inner if f.path.suffix.lower() not in ARCHIVE_EXTS]
            self.on_log("info", f"{src.label}: файлов внутри {len(inner)}")
            for f in inner:
                f.label = f"{src.label} › {f.label}"
                jobs.append((f, rel_dir / src.path.stem))
        return jobs

    def run(self) -> BatchResult:
        self._result = BatchResult()
        tmp = Path(tempfile.mkdtemp(prefix="converter_"))
        try:
            jobs = self._expand_archives(tmp)
            total = len(jobs)
            done = 0
            self.on_progress(0, total, "")
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = {pool.submit(self._guarded, src, prefix, n): src for n, (src, prefix) in enumerate(jobs)}
                for fut in as_completed(futures):
                    src = futures[fut]
                    done += 1
                    ok, info = fut.result()
                    if ok is None:
                        pass  # skipped because of stop
                    elif ok:
                        self._result.converted += 1
                        self._result.pages += info
                        extra = f" ({info} стр.)" if info > 1 else ""
                        self.on_log("ok", f"{src.label}{extra}")
                        self.on_file(src.label, True, str(info))
                    else:
                        self._result.failed.append((src.label, info))
                        self.on_log("error", f"{src.label}: {info}")
                        self.on_file(src.label, False, info)
                    self.on_progress(done, total, src.label)
            self._result.cancelled = self.stopped
            if self.settings.sheet.enabled and self._sheet_items and not self.stopped:
                self._write_sheets()
            elif self.settings.output.fmt == "PDF" and self.settings.output.merge_pdf and not self.stopped:
                self._merge_pdfs()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return self._result

    def _merge_pdfs(self) -> None:
        """PDF output with "one file": join the per-file PDFs into all.pdf."""
        parts = [self._pdf_parts[k] for k in sorted(self._pdf_parts)]
        if len(parts) < 2:
            return
        try:
            import pymupdf
        except ImportError:
            self.on_log("error", "Склеить PDF в один файл не получилось: нет PyMuPDF")
            return
        target = self.out_dir / "all.pdf"
        n = 2
        while target.exists():
            target = self.out_dir / f"all_{n}.pdf"
            n += 1
        merged = pymupdf.open()
        for part in parts:
            with pymupdf.open(part) as doc:
                merged.insert_pdf(doc)
        merged.save(target, garbage=3, deflate=True)
        merged.close()
        for part in parts:
            part.unlink(missing_ok=True)
        self._result.pages = 1
        self.on_log("info", f"Все файлы собраны в {target.name}")

    def _write_sheets(self) -> None:
        s = self.settings
        items = [self._sheet_items[k] for k in sorted(self._sheet_items)]
        sheets = compose(items, s.sheet, s.output.dpi)
        if s.output.fmt == "PDF":
            save_images(sheets, self.out_dir / "sheets.pdf", s.output)  # one PDF, a page per sheet
            self._result.pages = len(sheets)
            self.on_log("info", f"Листов: {len(sheets)} в sheets.pdf, фото на листе: {s.sheet.per_sheet}")
            return
        ext = EXTENSIONS[s.output.fmt]
        for n, sheet in enumerate(sheets, 1):
            save_image(sheet, self.out_dir / f"sheet_{n:03d}{ext}", s.output)
        self._result.pages = len(sheets)
        self.on_log("info", f"Листов: {len(sheets)}, фото на листе: {s.sheet.per_sheet}")

    def _guarded(self, src: SourceFile, prefix: Path, index: int = 0):
        if self.stopped:
            return None, 0
        try:
            return True, self._convert_one(src, prefix, index)
        except LoadError as exc:
            return False, str(exc)
        except MemoryError:
            return False, "не хватает памяти"
        except Exception as exc:  # keep the batch going whatever one file does
            return False, f"{type(exc).__name__}: {exc}"


def final_pages(files, settings: JobSettings, dpi: int, edited: dict[str, str] | None = None,
                errors: list[str] | None = None):
    """Yield every finished page of ``files``; with several photos per sheet, yield whole sheets."""
    edited = edited or {}
    sheet = settings.sheet
    items = []
    for path in files:
        path = Path(path)
        try:
            read_from = edited.get(str(path))
            pages = process_file(path, settings, dpi, Path(read_from) if read_from else None)
        except Exception as exc:  # one bad file must not stop the rest
            if errors is not None:
                errors.append(f"{path.name}: {exc}")
            continue
        for i, img in enumerate(pages):
            if sheet.enabled:
                _, cell, _ = geometry(sheet, dpi)
                label = path.stem if len(pages) == 1 else f"{path.stem} {i + 1}"
                items.append((label, fit_photo(img, photo_area(sheet, cell, dpi), sheet)))
            else:
                yield img
    if sheet.enabled and items:
        yield from compose(items, sheet, dpi)
