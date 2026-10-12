"""The tools the MCP server offers. Every argument is plain text or numbers, every result is text (plus a picture
for ``preview``), so an agent that cannot see the screen can do everything the program does."""
from __future__ import annotations

import base64
import io
import sys
import tempfile
import time
from dataclasses import fields
from pathlib import Path

from . import pdftools
from .batch import Batch, SourceFile, final_pages, scan_folder
from .imaging import (EXTENSIONS, RATIOS, SIZE_PRESETS, UNIT_TO_INCH, ColorSettings, FrameSettings, JobSettings,
                      OutputSettings)
from .loaders import ARCHIVE_EXTS, HEIF_SUPPORTED, RASTER_EXTS, SUPPORTED_EXTS, LoadError, load_pages
from .mcp_server import Context, Tool, ToolError
from .sheet import PAPERS as SHEET_PAPERS
from .sheet import PRESETS, SheetSettings, apply_preset, geometry
from .version import VERSION

FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "tif": "TIFF", "tiff": "TIFF", "pdf": "PDF"}
COLOR_KEYS = [f.name for f in fields(ColorSettings) if f.name != "wb"]
TEMP = Path(tempfile.gettempdir()) / "KopiTehnik-mcp"


# --------------------------------------------------------------------------- schema pieces

def _num(desc: str, **kw) -> dict:
    return {"type": "number", "description": desc, **kw}


def _int(desc: str, **kw) -> dict:
    return {"type": "integer", "description": desc, **kw}


def _str(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


def _bool(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


def _obj(props: dict, required: list[str] | None = None, desc: str = "") -> dict:
    out = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = required
    if desc:
        out["description"] = desc
    return out


FILES_PROPS = {
    "files": {"type": "array", "items": {"type": "string"},
              "description": "Полные пути к файлам (папка в списке означает все файлы в ней, включая вложенные)."},
    "folder": _str("Папка с исходными файлами; берутся все поддерживаемые файлы, включая вложенные папки и архивы."),
}

COLOR_SCHEMA = _obj({
    **{k: _int("-100..100, 0 без изменений", minimum=-100, maximum=100) for k in COLOR_KEYS if k != "auto"},
    "auto": _int("0..100: сила автокоррекции (растяжка уровней по каждому каналу)", minimum=0, maximum=100),
    "wb": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
           "description": "Усиление каналов [R, G, B] для баланса белого, 1.0 без изменений"},
}, desc="Коррекция цвета. gamma это средние тона, cyan/magenta/yellow противоположны red/green/blue.")

SHEET_PROPS = {
    "preset": _str("Готовая раскладка: " + ", ".join(PRESETS) + " (описания в app_info)."),
    "paper": _str("Бумага листа: " + ", ".join(SHEET_PAPERS)),
    "landscape": _bool("Лист альбомный"),
    "cols": _int("Столбцов в сетке (если не задан размер фото)", minimum=1),
    "rows": _int("Строк в сетке", minimum=1),
    "photo_w_cm": _num("Точная ширина фото, см (вместе с photo_h_cm; сетка подбирается сама)"),
    "photo_h_cm": _num("Точная высота фото, см"),
    "margin_mm": _num("Поля листа, мм"),
    "gap_mm": _num("Зазор между фото, мм"),
    "fill": _bool("true: фото заполняет ячейку и обрезается, false: фото целиком внутри ячейки"),
    "captions": _bool("Подписать имя файла под фото"),
    "copies": _int("Копий каждого фото; 0 = заполнить каждым фото целые листы", minimum=0),
    "auto_rotate": _bool("Поворачивать фото на 90°, если так лучше ложится в ячейку"),
    "cut_marks": _bool("Метки реза на полях"),
}

PROCESSING_PROPS = {
    "ratio": _str("Кадр: original, 3:2, 4:3, 5:4, 7:5, 1:1, 16:9, a4 или custom (тогда size_w, size_h, unit)"),
    "size_w": _num("custom: ширина"), "size_h": _num("custom: высота"),
    "unit": {"type": "string", "enum": ["cm", "mm", "in"], "description": "custom: единицы размера"},
    "fit": _bool("custom: true вписать фото целиком с полями, false обрезать под размер"),
    "fill_color": _str("custom+fit: цвет полей, #rrggbb (по умолчанию белый)"),
    "orientation": {"type": "string", "enum": ["auto", "portrait", "landscape"],
                    "description": "Ориентация кадра: auto по самому фото"},
    "rotate": {"type": "integer", "enum": [0, 90, 180, 270], "description": "Поворот по часовой стрелке, градусы"},
    "mirror_h": _bool("Зеркало по горизонтали"), "mirror_v": _bool("Зеркало по вертикали"),
    "color": COLOR_SCHEMA,
    "sheet": _obj(SHEET_PROPS, desc="Несколько фото на одном листе. Если задан, результат это листы."),
    "dpi": _int("Разрешение, 72..1200 (по умолчанию 300)", minimum=72, maximum=1200),
}

OUTPUT_PROPS = {
    "format": {"type": "string", "enum": ["JPEG", "PNG", "TIFF", "PDF"], "description": "Формат результата (по умолчанию JPEG)"},
    "quality": _int("Качество JPEG 1..100 (по умолчанию 95)", minimum=1, maximum=100),
    "merge_pdf": _bool("PDF: склеить всё в один файл all.pdf"),
    "keep_structure": _bool("Повторить вложенные папки источника в результате (по умолчанию true)"),
}


# --------------------------------------------------------------------------- argument handling

def _path(value, what: str = "path") -> Path:
    if not value or not isinstance(value, str):
        raise ToolError(f"нужен параметр {what} (полный путь)")
    p = Path(value).expanduser()
    if not p.exists():
        raise ToolError(f"нет такого пути: {p}")
    return p


def _sources(args: dict) -> list[SourceFile]:
    out: list[SourceFile] = []
    if args.get("folder"):
        folder = _path(args["folder"], "folder")
        if not folder.is_dir():
            raise ToolError(f"{folder} не папка")
        out.extend(scan_folder(folder))
    for f in args.get("files") or []:
        p = _path(f, "files")
        if p.is_dir():
            out.extend(scan_folder(p))
        elif p.suffix.lower() in SUPPORTED_EXTS | ARCHIVE_EXTS:
            out.append(SourceFile(p))
        else:
            raise ToolError(f"формат {p.suffix} не поддерживается: {p}")
    if not out:
        raise ToolError("нет файлов: укажите files или folder с поддерживаемыми файлами")
    return out


def _color(data) -> ColorSettings:
    data = dict(data or {})
    for k, v in data.items():
        if k == "wb":
            if not isinstance(v, list) or len(v) != 3:
                raise ToolError("color.wb: нужны три числа [R, G, B]")
        elif k not in COLOR_KEYS:
            raise ToolError(f"color.{k}: неизвестный параметр, есть {', '.join(COLOR_KEYS + ['wb'])}")
        else:
            data[k] = max(0 if k == "auto" else -100, min(100, int(v)))
    return ColorSettings.from_dict(data)


def _sheet(data) -> SheetSettings:
    s = SheetSettings()
    if not data:
        return s
    data = dict(data)
    preset = data.pop("preset", None)
    if preset:
        if preset not in PRESETS:
            raise ToolError(f"sheet.preset «{preset}»: есть {', '.join(PRESETS)}")
        apply_preset(s, preset)
    names = {f.name for f in fields(SheetSettings)} - {"enabled", "preset"}
    for k, v in data.items():
        if k not in names:
            raise ToolError(f"sheet.{k}: неизвестный параметр, есть {', '.join(sorted(names))}")
        setattr(s, k, type(getattr(s, k))(v) if not isinstance(getattr(s, k), bool) else bool(v))
    if s.paper not in SHEET_PAPERS:
        raise ToolError(f"sheet.paper «{s.paper}»: есть {', '.join(SHEET_PAPERS)}")
    s.enabled = True
    if data.get("photo_w_cm") or data.get("photo_h_cm"):
        s.preset = "custom"
    return s


def build_settings(args: dict) -> JobSettings:
    """JobSettings from the flat tool arguments."""
    fmt_raw = str(args.get("format", "JPEG")).lower().lstrip(".")
    fmt = FORMATS.get(fmt_raw)
    if not fmt:
        raise ToolError(f"format «{args.get('format')}»: JPEG, PNG, TIFF или PDF")
    out = OutputSettings(fmt=fmt, quality=int(args.get("quality", 95)), dpi=int(args.get("dpi", 300)),
                         keep_structure=bool(args.get("keep_structure", True)), merge_pdf=bool(args.get("merge_pdf", False)))
    frame = FrameSettings()
    ratio = str(args.get("ratio", "original")).lower()
    if ratio != "custom" and ratio not in RATIOS:
        raise ToolError(f"ratio «{ratio}»: {', '.join(RATIOS)} или custom")
    frame.ratio = ratio
    if ratio == "custom":
        if not (args.get("size_w") and args.get("size_h")):
            raise ToolError("ratio=custom: нужны size_w и size_h")
        frame.size_w, frame.size_h = float(args["size_w"]), float(args["size_h"])
        frame.unit = args.get("unit", "cm")
        if frame.unit not in UNIT_TO_INCH:
            raise ToolError("unit: cm, mm или in")
        frame.fit = bool(args.get("fit", False))
        frame.fill = args.get("fill_color", "#ffffff")
    orient = args.get("orientation", "auto")
    frame.auto_orient = orient == "auto"
    frame.portrait = orient == "portrait"
    rot = int(args.get("rotate", 0))
    if rot not in (0, 90, 180, 270):
        raise ToolError("rotate: 0, 90, 180 или 270")
    frame.rotate = rot
    frame.mirror_h, frame.mirror_v = bool(args.get("mirror_h", False)), bool(args.get("mirror_v", False))
    return JobSettings(color=_color(args.get("color")), frame=frame, output=out, sheet=_sheet(args.get("sheet")))


def _snapshot(folder: Path) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in folder.rglob("*") if p.is_file()} if folder.exists() else {}


def image_stats(img) -> dict:
    """Numbers an agent without eyes can use to judge a picture."""
    from PIL import ImageStat
    small = img.convert("RGB")
    small.thumbnail((256, 256))
    st = ImageStat.Stat(small)
    grey = small.convert("L")
    hist = grey.histogram()
    n = sum(hist) or 1
    mean = round(st.mean[0] * 0.299 + st.mean[1] * 0.587 + st.mean[2] * 0.114, 1)
    return {"mean_rgb": [round(v, 1) for v in st.mean], "brightness_0_255": mean,
            "contrast_stddev": round(ImageStat.Stat(grey).stddev[0], 1),
            "dark_pixels_pct": round(sum(hist[:16]) * 100 / n, 1),
            "bright_pixels_pct": round(sum(hist[240:]) * 100 / n, 1)}


# --------------------------------------------------------------------------- tools

def app_info(args, ctx) -> dict:
    from . import office
    from .printjob import PAPERS as PRINT_PAPERS
    from .printjob import printers
    progs = office.detect()
    names, default = printers()
    return {
        "program": "КопиТехник Конвертор", "version": VERSION,
        "input_formats": sorted(e.lstrip(".") for e in SUPPORTED_EXTS), "archives": sorted(e.lstrip(".") for e in ARCHIVE_EXTS),
        "output_formats": list(EXTENSIONS), "heic_supported": HEIF_SUPPORTED, "pdf_editing": progs.pymupdf,
        "office": {"word": progs.word, "powerpoint": progs.powerpoint, "excel": progs.excel,
                   "libreoffice": progs.libreoffice or None, "note": "документы Word/Excel/PowerPoint конвертируются, "
                   "если есть Microsoft Office или LibreOffice"},
        "frame_ratios": list(RATIOS) + ["custom"], "common_print_sizes": [f"{w:g}x{h:g} {u}" for w, h, u in SIZE_PRESETS],
        "color_parameters": COLOR_KEYS + ["wb"],
        "sheet_papers_cm": {k: list(v) for k, v in SHEET_PAPERS.items()},
        "sheet_presets": {k: {kk: vv for kk, vv in v.items() if kk in (
            "paper", "landscape", "cols", "rows", "photo_w_cm", "photo_h_cm", "copies", "cut_marks")} for k, v in PRESETS.items()},
        "print_papers_mm": {k: list(mm) for k, mm, _ in PRINT_PAPERS},
        "printers": names, "default_printer": default or None,
        "tools_hint": "convert, make_sheet, preview, inspect_file, list_files, pdf_info, pdf_get_text, pdf_find_text, "
                      "pdf_edit, pdf_pages, list_printers, print_files",
    }


def list_files(args, ctx) -> dict:
    folder = _path(args.get("folder"), "folder")
    if not folder.is_dir():
        raise ToolError(f"{folder} не папка")
    found = scan_folder(folder)
    limit = int(args.get("limit", 500))
    return {"folder": str(folder), "count": len(found), "shown": min(limit, len(found)),
            "files": [{"path": str(f.path), "relative": f.label, "kb": round(f.path.stat().st_size / 1024, 1),
                       "archive": f.path.suffix.lower() in ARCHIVE_EXTS} for f in found[:limit]]}


def inspect_file(args, ctx) -> dict:
    p = _path(args.get("path"))
    ext = p.suffix.lower()
    info: dict = {"path": str(p), "kb": round(p.stat().st_size / 1024, 1), "type": ext.lstrip(".")}
    if ext not in SUPPORTED_EXTS:
        info["supported"] = False
        return info
    info["supported"] = True
    if ext == ".pdf":
        try:
            info.update(pdftools.info(p))
            return info
        except pdftools.PdfToolError:
            pass
    from PIL import Image
    if ext in RASTER_EXTS:
        with Image.open(p) as im:
            info.update(width=im.width, height=im.height, mode=im.mode, format=im.format,
                        dpi=[round(float(v), 1) for v in im.info["dpi"]] if im.info.get("dpi") else None,
                        icc_profile=bool(im.info.get("icc_profile")), frames=getattr(im, "n_frames", 1))
            dpi = max(im.info["dpi"]) if im.info.get("dpi") else 300
            info["print_size_cm_at_file_dpi"] = [round(im.width / dpi * 2.54, 1), round(im.height / dpi * 2.54, 1)]
    pages = load_pages(p, dpi=int(args.get("dpi", 100)), preview_size=800 if ext in RASTER_EXTS else None)
    if pages:
        info["pages_loaded"] = len(pages)
        info["stats"] = image_stats(pages[0])
        if ext not in RASTER_EXTS:
            info["page_px"] = list(pages[0].size)
    return info


def convert(args, ctx) -> dict:
    sources = _sources(args)
    settings = build_settings(args)
    if not args.get("out_dir"):
        raise ToolError("нужен out_dir: папка для результата")
    out = Path(args["out_dir"]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    before = _snapshot(out)
    log: list[str] = []
    batch = Batch(sources, out, settings,
                  on_progress=lambda done, total, name: ctx.progress(done, max(total, 1), name),
                  on_log=lambda lvl, msg: log.append(f"{lvl}: {msg}") if lvl != "ok" else None)
    res = batch.run()
    after = _snapshot(out)
    produced = sorted(p for p, m in after.items() if before.get(p) != m)
    return {"converted_files": res.converted, "output_files_count": len(produced), "failed": [
        {"file": f, "error": e} for f, e in res.failed], "output_dir": str(out),
        "outputs": produced[:200], "log": log[:50], "settings": _describe(settings)}


def _describe(s: JobSettings) -> dict:
    d = {"format": s.output.fmt, "dpi": s.output.dpi, "ratio": s.frame.ratio}
    if s.sheet.enabled:
        d["sheet"] = {"paper": s.sheet.paper, "landscape": s.sheet.landscape, "photos_per_sheet": s.sheet.per_sheet}
    return d


def make_sheet(args, ctx) -> dict:
    a = dict(args)
    sheet = dict(a.pop("sheet", None) or {})
    for k in SHEET_PROPS:
        if k in a:
            sheet[k] = a.pop(k)
    if not sheet:
        raise ToolError("укажите preset или параметры листа (paper, cols/rows или photo_w_cm/photo_h_cm)")
    a["sheet"] = sheet
    return convert(a, ctx)


def preview(args, ctx):
    sources = _sources(args)
    settings = build_settings(args)
    settings.output.dpi = int(args.get("dpi", 100 if settings.sheet.enabled else 150))
    number = int(args.get("page", 1))
    errors: list[str] = []
    files = [s.path for s in sources if s.path.suffix.lower() not in ARCHIVE_EXTS]
    if not files:
        raise ToolError("в архивах превью не строится, распакуйте или укажите файлы")
    page = None
    total = 0
    for total, img in enumerate(final_pages(files, settings, settings.output.dpi, errors), 1):
        if total == number:
            page = img
            break
    if page is None:
        raise ToolError(errors[0] if errors else f"страницы {number} нет")
    side = int(args.get("max_side", 1100))
    shown = page.copy()
    shown.thumbnail((side, side))
    TEMP.mkdir(parents=True, exist_ok=True)
    path = TEMP / f"preview_{int(time.time() * 1000)}.jpg"
    shown.convert("RGB").save(path, "JPEG", quality=85)
    for old in sorted(TEMP.glob("preview_*.jpg"))[:-20]:
        old.unlink(missing_ok=True)
    buf = io.BytesIO()
    shown.convert("RGB").save(buf, "JPEG", quality=80)
    dpi = settings.output.dpi
    info = {"page": number, "pixels": list(page.size), "size_cm_at_dpi": [round(page.width / dpi * 2.54, 1),
            round(page.height / dpi * 2.54, 1)], "dpi": dpi, "preview_file": str(path), "stats": image_stats(page)}
    if errors:
        info["errors"] = errors
    if settings.sheet.enabled:
        info["sheet"] = {"photos_per_sheet": settings.sheet.per_sheet}
    image = {"type": "image", "data": base64.b64encode(buf.getvalue()).decode(), "mimeType": "image/jpeg"}
    return info, [image]


# ---- PDF

def _pdf_output(args: dict, src: Path, suffix: str = "_edited") -> Path:
    if args.get("output"):
        out = Path(args["output"]).expanduser()
        if out.resolve() == src.resolve():
            raise ToolError("output совпадает с исходным файлом, укажите другое имя")
        return out
    return pdftools.unique_path(src.with_name(src.stem + suffix + ".pdf"))


def pdf_info(args, ctx) -> dict:
    return pdftools.info(_path(args.get("path")))


def pdf_get_text(args, ctx) -> dict:
    return pdftools.get_text(_path(args.get("path")), args.get("pages"), int(args.get("max_chars", 30000)))


def pdf_find_text(args, ctx) -> dict:
    return pdftools.find_text(_path(args.get("path")), args.get("query", ""), args.get("pages"),
                              bool(args.get("case_sensitive", False)))


def pdf_edit(args, ctx) -> dict:
    src = _path(args.get("path"))
    return pdftools.edit(src, _pdf_output(args, src), args.get("operations") or [])


def pdf_pages(args, ctx) -> dict:
    op = args.get("operation")
    if op == "merge":
        files = [_path(f, "files") for f in args.get("files") or []]
        if not args.get("output"):
            raise ToolError("merge: нужен output (файл результата)")
        return pdftools.pages_op("merge", Path(args["output"]).expanduser(), files=files)
    src = _path(args.get("path"))
    if op == "split":
        out = Path(args.get("output_dir") or src.parent / (src.stem + "_split")).expanduser()
        return pdftools.pages_op("split", out, path=src, every=int(args.get("every", 1)))
    return pdftools.pages_op(op, _pdf_output(args, src, "_" + str(op)), path=src, pages=args.get("pages"),
                             angle=int(args.get("angle", 90)))


# ---- printing

def list_printers(args, ctx) -> dict:
    from .printjob import printers
    names, default = printers()
    return {"printers": names, "default": default or None, "pdf_virtual_printer": "укажите printer=\"pdf\" и output"}


def print_files(args, ctx) -> dict:
    from PySide6.QtGui import QPageLayout  # noqa: F401  (fails early if Qt print support is missing)
    from PySide6.QtPrintSupport import QPrinter

    from .printjob import (PAPER_BY_KEY, PDF_PRINTER, make_printer, parse_range, print_pages, printers)
    sources = _sources(args)
    files = [s.path for s in sources if s.path.suffix.lower() not in ARCHIVE_EXTS]
    settings = build_settings({**args, "format": "JPEG"})
    dpi = int(args.get("dpi", 300))
    if dpi not in range(72, 1201):
        raise ToolError("dpi: 72..1200")
    settings.output.dpi = dpi
    paper = str(args.get("paper", "a4")).lower()
    if paper not in PAPER_BY_KEY:
        raise ToolError(f"paper «{paper}»: {', '.join(PAPER_BY_KEY)}")
    mode = args.get("scale", "fit")
    if mode not in ("fit", "fill", "actual"):
        raise ToolError("scale: fit, fill или actual")
    errors: list[str] = []
    pages = list(final_pages(files, settings, dpi, None, errors))
    if not pages:
        raise ToolError("печатать нечего: " + ("; ".join(errors) or "нет страниц"))
    wanted = None
    if args.get("pages"):
        picked = parse_range(str(args["pages"]), len(pages))
        if not picked:
            raise ToolError(f"pages «{args['pages']}»: пример 1-3,5; всего листов {len(pages)}")
        wanted = set(picked)
    orient = args.get("orientation", "auto")
    landscape = (pages[0].width > pages[0].height) if orient == "auto" else orient == "landscape"
    target = str(args.get("printer", "default"))
    to_pdf = target.lower() in ("pdf", PDF_PRINTER)
    names, default = printers()
    if not to_pdf:
        name = default if target == "default" else target
        if not name or name not in names:
            raise ToolError(f"принтер «{target}» не найден, есть: {', '.join(names) or 'нет принтеров'}")
    else:
        name = PDF_PRINTER
    summary = {"sheets_rendered": len(pages), "sheets_to_print": len(wanted) if wanted else len(pages),
               "paper": paper, "landscape": landscape, "printer": "PDF-файл" if to_pdf else name,
               "copies": int(args.get("copies", 1)), "errors": errors}
    if args.get("dry_run"):
        summary["dry_run"] = "ничего не отправлено"
        return summary
    if to_pdf:
        if not args.get("output"):
            raise ToolError("printer=pdf: нужен output (путь к .pdf)")
        out = Path(args["output"]).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(out))
        summary["output"] = str(out)
    else:
        printer = make_printer(name)
    printer.setDocName(files[0].stem if len(files) == 1 else "KopiTehnik")
    done = print_pages(pages, printer, name, paper, landscape, dpi, mode=mode, margin_mm=float(args.get("margin_mm", 0)),
                       gray=args.get("color", "color") == "gray", rotate=bool(args.get("rotate_to_fit", True)),
                       copies=1 if to_pdf else max(1, int(args.get("copies", 1))), wanted=wanted)
    summary["pages_sent"] = done
    return summary


# --------------------------------------------------------------------------- registry

def build_tools() -> list[Tool]:
    convert_props = {**FILES_PROPS, **PROCESSING_PROPS, **OUTPUT_PROPS,
                     "out_dir": _str("Папка для результата (создаётся)")}
    sheet_tool_props = {**FILES_PROPS, **{k: v for k, v in PROCESSING_PROPS.items() if k not in ("sheet", "ratio")},
                        **OUTPUT_PROPS, **SHEET_PROPS, "ratio": PROCESSING_PROPS["ratio"],
                        "out_dir": _str("Папка для результата (создаётся)")}
    preview_props = {**FILES_PROPS, **PROCESSING_PROPS, "page": _int("Какую готовую страницу или лист показать (с 1)", minimum=1),
                     "max_side": _int("Длинная сторона картинки в пикселях (по умолчанию 1100)", minimum=200, maximum=3000)}
    print_props = {**FILES_PROPS, **PROCESSING_PROPS,
                   "printer": _str("Имя принтера из list_printers, default или pdf (сохранить в файл)"),
                   "output": _str("printer=pdf: куда записать PDF"),
                   "paper": _str("Бумага: a4, a3, a5, a6, 10x15, 13x18, 15x21, 20x30, letter"),
                   "orientation": PROCESSING_PROPS["orientation"],
                   "copies": _int("Копий", minimum=1, maximum=999),
                   "pages": _str("Какие листы печатать, например 1-3,5 (по умолчанию все)"),
                   "color": {"type": "string", "enum": ["color", "gray"], "description": "Цветная или чёрно-белая печать"},
                   "scale": {"type": "string", "enum": ["fit", "fill", "actual"],
                             "description": "fit вписать в поля, fill закрыть всю бумагу с обрезкой, actual реальный размер по dpi"},
                   "margin_mm": _num("Поля, мм (не меньше, чем может принтер)"),
                   "rotate_to_fit": _bool("Поворачивать страницу под ориентацию бумаги (по умолчанию true)"),
                   "dry_run": _bool("Только посчитать листы, ничего не отправлять")}
    path_prop = {"path": _str("Полный путь к PDF (или документу Word/Excel/PowerPoint: его сначала переведут в PDF)")}
    return [
        Tool("app_info", "Возможности программы: форматы, раскладки листов, бумага, найденные Office/LibreOffice и принтеры. "
             "Вызовите первым.", _obj({}), app_info, True),
        Tool("list_files", "Найти все поддерживаемые файлы в папке (с вложенными).",
             _obj({"folder": _str("Папка"), "limit": _int("Сколько показать (по умолчанию 500)")}, ["folder"]), list_files, True),
        Tool("inspect_file", "Сведения о файле: размеры, dpi, страницы, цвет в числах (яркость, контраст, тёмные и светлые доли).",
             _obj({"path": _str("Путь к файлу")}, ["path"]), inspect_file, True),
        Tool("convert", "Конвертировать фото и документы в JPEG, PNG, TIFF или PDF с кадрированием, поворотом, коррекцией цвета "
             "и, при желании, раскладкой на листы. Исходные файлы не меняются.",
             _obj(convert_props, ["out_dir"]), convert),
        Tool("make_sheet", "Расположить несколько фото на одном листе (фото 10x15 и 9x12 на A4, документы 3x4, 3.5x4.5, 4x6, "
             "контрольный лист или своя сетка/размер). Результат: листы sheet_001.jpg или sheets.pdf.",
             _obj(sheet_tool_props, ["out_dir"]), make_sheet),
        Tool("preview", "Построить результат (кадр, цвет, лист) и показать как картинку; в тексте размеры и числа яркости "
             "и контраста для проверки без зрения. Файл ничего не записывает кроме временной картинки.",
             _obj(preview_props), preview, True),
        Tool("pdf_info", "PDF: число страниц, размеры, поворот, есть ли текст или это скан.", _obj(path_prop, ["path"]), pdf_info, True),
        Tool("pdf_get_text", "PDF: текст по строкам с положением [x0,y0,x1,y1] в пунктах от левого верхнего угла, шрифтом, "
             "размером и цветом. По этим данным ставятся правки в pdf_edit.",
             _obj({**path_prop, "pages": _str("Страницы, например 1-3,5 (по умолчанию все)"),
                   "max_chars": _int("Ограничение размера ответа")}, ["path"]), pdf_get_text, True),
        Tool("pdf_find_text", "PDF: найти текст, получить страницу и прямоугольник каждого места.",
             _obj({**path_prop, "query": _str("Что искать"), "pages": _str("Страницы"),
                   "case_sensitive": _bool("Учитывать регистр")}, ["path", "query"]), pdf_find_text, True),
        Tool("pdf_edit", "Правка PDF списком операций, результат в НОВЫЙ файл (исходный не меняется). Операции: "
             "replace_text {find, replace, page?, case_sensitive?, shrink_to_fit?, font?, size?, color?, bold?, italic?} "
             "заменяет текст с тем же видом; add_text {page, x, y, text, size?, color?, font?, bold?, italic?, white_bg?, angle?} "
             "вписывает надпись (x,y: верх-лево первой строки); erase {page, rect:[x0,y0,x1,y1], mode: white|text, fill?} "
             "стирает область; add_image {page, rect, path} вставляет картинку. Координаты в пунктах (1/72 дюйма) от "
             "левого верхнего угла страницы как она показана.",
             _obj({**path_prop, "output": _str("Файл результата (по умолчанию имя_edited.pdf рядом)"),
                   "operations": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
                       "op": {"type": "string", "enum": ["replace_text", "add_text", "erase", "add_image"]}},
                       "required": ["op"], "additionalProperties": True}}}, ["path", "operations"]), pdf_edit),
        Tool("pdf_pages", "PDF: операции со страницами. merge склеить files в output; extract оставить pages (порядок можно "
             "менять, например 3,1,2); delete убрать pages; rotate повернуть pages (по умолчанию все) на angle; split разрезать "
             "на файлы по every страниц.",
             _obj({"operation": {"type": "string", "enum": ["merge", "extract", "delete", "rotate", "split"]},
                   "path": _str("Исходный PDF (кроме merge)"), "files": {"type": "array", "items": {"type": "string"},
                   "description": "merge: PDF по порядку"}, "pages": _str("Номера страниц, 1-3,5"),
                   "angle": _int("rotate: 90, 180, 270 или -90"), "every": _int("split: страниц в одном файле"),
                   "output": _str("Файл результата"), "output_dir": _str("split: папка для частей")},
                  ["operation"]), pdf_pages),
        Tool("list_printers", "Установленные принтеры и принтер по умолчанию.", _obj({}), list_printers, True),
        Tool("print_files", "Напечатать файлы с теми же настройками, что в программе: кадр, цвет, листы по несколько фото, "
             "бумага, копии, диапазон листов, цветная или чёрно-белая печать. printer=pdf записывает результат в PDF вместо "
             "бумаги. dry_run=true только считает листы. ВНИМАНИЕ: обычный запуск реально печатает на бумагу.",
             _obj(print_props), print_files),
    ]
