"""Editing PDF files without a window: read text with positions, replace, add, erase, insert pictures,
merge, split, rotate. The same operations the PDF editor does by hand, for programs that cannot see the screen.

Coordinates are points (1/72 inch) of the page *as shown*: origin at the top-left corner, y grows downwards.
PyMuPDF (AGPL) is imported only when a function runs, so the rest of the program does not depend on it."""
from __future__ import annotations

import re

import os
from pathlib import Path

FONTS_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
# Font name -> files for regular, bold, italic, bold italic (same list as the PDF editor).
FONTS = {
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "Courier New": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
}
EXTRA_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"),
              Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
LEADING = 1.2
PAD = 2.0


class PdfToolError(Exception):
    pass


def _fitz():
    try:
        import pymupdf
    except ImportError as exc:
        raise PdfToolError("для правки PDF нужен PyMuPDF, в этой сборке его нет") from exc
    return pymupdf


# --------------------------------------------------------------------------- helpers

def font_file(name: str, bold: bool, italic: bool) -> str | None:
    files = FONTS.get(name, FONTS["Arial"])
    for f in (files[bold + 2 * italic], files[0]):
        if (FONTS_DIR / f).exists():
            return str(FONTS_DIR / f)
    for d in EXTRA_DIRS:   # other systems: DejaVu covers Cyrillic too
        cand = d / ("DejaVuSans-BoldOblique.ttf" if bold and italic else "DejaVuSans-Bold.ttf" if bold
                    else "DejaVuSans-Oblique.ttf" if italic else "DejaVuSans.ttf")
        if cand.exists():
            return str(cand)
    return None


def guess_font(pdf_font: str) -> str:
    """Closest font we have for a font name found in the PDF."""
    low = pdf_font.lower()
    for key, name in (("times", "Times New Roman"), ("cour", "Courier New"), ("calibri", "Calibri"),
                      ("segoe", "Segoe UI"), ("verdana", "Verdana"), ("serif", "Times New Roman")):
        if key in low and "sans" not in low:
            return name
    return "Arial"


NAMED_COLORS = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
                "blue": "#0000ff", "yellow": "#ffff00", "gray": "#808080", "grey": "#808080",
                "orange": "#ffa500", "purple": "#800080"}


def parse_color(value, default=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if value in (None, ""):
        return default
    s = str(value).strip().lower()
    s = NAMED_COLORS.get(s, s).lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    try:
        return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))   # type: ignore[return-value]
    except (ValueError, IndexError):
        raise PdfToolError(f"не понял цвет «{value}», нужен вид #rrggbb")


def hex_color(c: int) -> str:
    return "#%06x" % (c & 0xFFFFFF)


def parse_pages(spec, total: int, default_all: bool = True) -> list[int]:
    """'1-3, 5, 8-' (or a list of numbers) -> 0-based page indexes in the written order."""
    if spec in (None, "", "all", "все"):
        if default_all:
            return list(range(total))
        raise PdfToolError("не указаны страницы")
    if isinstance(spec, int):
        spec = str(spec)
    if isinstance(spec, list):
        spec = ",".join(str(x) for x in spec)
    out: list[int] = []
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                lo = int(a) if a else 1
                hi = int(b) if b else total
            else:
                lo = hi = int(part)
        except ValueError:
            raise PdfToolError(f"не понял номера страниц «{spec}», пример: 1-3,5")
        if lo < 1 or hi < lo or hi > total:
            raise PdfToolError(f"страницы «{part}» вне документа (в нём {total})")
        out.extend(range(lo - 1, hi))
    if not out:
        raise PdfToolError("не указаны страницы")
    return out


def _open(path):
    fitz = _fitz()
    p = Path(path)
    if not p.is_file():
        raise PdfToolError(f"нет файла {p}")
    if p.suffix.lower() != ".pdf":
        from .office import OFFICE_EXTS, cached_pdf
        if p.suffix.lower() not in OFFICE_EXTS:
            raise PdfToolError(f"{p.name}: это не PDF и не документ Office")
        p = cached_pdf(p)
    doc = fitz.open(p)
    if doc.needs_pass:
        doc.close()
        raise PdfToolError(f"{p.name} защищён паролем")
    return doc


def unique_path(path: Path) -> Path:
    n = 2
    cand = path
    while cand.exists():
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return cand


def _shown(rect, page):
    return rect * page.rotation_matrix


def _rect_list(r) -> list[float]:
    return [round(float(v), 1) for v in (r.x0, r.y0, r.x1, r.y1)]


def _need_rect(op: dict, key: str = "rect"):
    r = op.get(key)
    if not r or len(r) != 4:
        raise PdfToolError(f"нужен прямоугольник {key}: [x0, y0, x1, y1] в пунктах от левого верхнего угла")
    x0, y0, x1, y1 = (float(v) for v in r)
    return _fitz().Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _page_of(doc, op: dict):
    n = op.get("page")
    if n in (None, ""):
        raise PdfToolError("у операции нужен номер страницы page (с 1)")
    n = int(n)
    if not 1 <= n <= doc.page_count:
        raise PdfToolError(f"страницы {n} нет, в документе {doc.page_count}")
    return doc[n - 1]


# --------------------------------------------------------------------------- reading

class Hit:
    """One place where the searched text was found."""

    def __init__(self, rect, style, line_id, start, end, line_text, line_rect, uniform):
        self.rect, self.style, self.line_id, self.start, self.end = rect, style, line_id, start, end
        self.line_text, self.line_rect, self.uniform = line_text, line_rect, uniform


def _span_style(span, origin_x: float) -> dict:
    fname = span.get("font", "")
    fl = span.get("flags", 0)
    return {"font": guess_font(fname), "size": span["size"], "color": hex_color(span.get("color", 0)),
            "bold": bool(fl & 16) or "bold" in fname.lower(),
            "italic": bool(fl & 2) or "italic" in fname.lower() or "oblique" in fname.lower(),
            "origin": (origin_x, span["origin"][1])}


def search(page, query: str, case_sensitive: bool = False) -> list[Hit]:
    """Places of ``query`` on the page (unrotated page space). Works within a line and is case-insensitive
    for every alphabet (PyMuPDF's own search only does Latin)."""
    fitz = _fitz()
    hits: list[Hit] = []
    for bi, block in enumerate(page.get_text("rawdict").get("blocks", [])):
        for li, line in enumerate(block.get("lines", [])):
            chars = [(ch["c"], ch["bbox"], span, ch["origin"][0]) for span in line.get("spans", [])
                     for ch in span.get("chars", [])]
            if not chars:
                continue
            text = "".join(" " if c[0] == " " else c[0] for c in chars)   # no-break spaces count as spaces
            query = query.replace(" ", " ")
            if case_sensitive:
                hay, needle = text, query
            else:
                hay, needle = text.casefold(), query.casefold()
                if len(hay) != len(text):        # casefold changed the length (ß): fall back to lower()
                    hay, needle = text.lower(), query.lower()
            start = hay.find(needle) if needle else -1
            if start < 0:
                continue
            line_rect = fitz.Rect(chars[0][1])
            for c in chars:
                line_rect |= fitz.Rect(c[1])
            looks = {(sp.get("font"), round(sp["size"], 1), sp.get("color"), sp.get("flags", 0) & 18)
                     for sp in line.get("spans", []) if any(ch["c"].strip() for ch in sp.get("chars", []))}
            while start >= 0:
                part = chars[start:start + len(needle)]
                rect = fitz.Rect(part[0][1])
                for c in part:
                    rect |= fitz.Rect(c[1])
                hits.append(Hit(rect, _span_style(part[0][2], part[0][3]), (bi, li), start, start + len(needle),
                                text, line_rect, len(looks) <= 1))
                start = hay.find(needle, start + len(needle))
    return hits


# --------------------------------------------------------------------------- reading

def info(path) -> dict:
    doc = _open(path)
    try:
        pages = []
        for i, page in enumerate(doc, 1):
            r = page.rect
            text = page.get_text("text")
            pages.append({
                "page": i, "width_pt": round(r.width, 1), "height_pt": round(r.height, 1),
                "width_mm": round(r.width / 72 * 25.4, 1), "height_mm": round(r.height / 72 * 25.4, 1),
                "rotation": page.rotation, "text_chars": len(text.strip()), "images": len(page.get_images()),
            })
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        scanned = all(p["text_chars"] == 0 and p["images"] for p in pages) if pages else False
        return {"path": str(path), "pages": doc.page_count, "metadata": meta, "page_info": pages,
                "looks_scanned": scanned,
                "note": "текста нет, только картинки: редактировать надо как рисунок" if scanned else ""}
    finally:
        doc.close()


def get_text(path, pages=None, max_chars: int = 30000) -> dict:
    """Text of the chosen pages as lines with position, font, size and colour (page as shown)."""
    doc = _open(path)
    try:
        out = []
        used = 0
        truncated = False
        for idx in parse_pages(pages, doc.page_count):
            page = doc[idx]
            lines = []
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    spans = [s for s in line.get("spans", []) if s.get("text", "")]
                    if not any(s["text"].strip() for s in spans):
                        continue
                    first = next(s for s in spans if s["text"].strip())
                    text = "".join(s["text"] for s in spans).rstrip()
                    fl = first.get("flags", 0)
                    fname = first.get("font", "")
                    item = {"text": text, "bbox": _rect_list(_shown(_fitz().Rect(line["bbox"]), page)),
                            "font": fname, "size": round(first["size"], 1), "color": hex_color(first.get("color", 0)),
                            "bold": bool(fl & 16) or "bold" in fname.lower(),
                            "italic": bool(fl & 2) or "italic" in fname.lower() or "oblique" in fname.lower()}
                    used += len(text) + 80
                    if used > max_chars:
                        truncated = True
                        break
                    lines.append(item)
                if truncated:
                    break
            lines.sort(key=lambda it: (round((it["bbox"][1] + it["bbox"][3]) / 6), it["bbox"][0]))   # reading order
            out.append({"page": idx + 1, "width_pt": round(page.rect.width, 1),
                        "height_pt": round(page.rect.height, 1), "lines": lines})
            if truncated:
                break
        res = {"path": str(path), "pages": out}
        if truncated:
            res["truncated"] = "ответ обрезан, запросите нужные страницы отдельно (параметр pages)"
        return res
    finally:
        doc.close()


def find_text(path, query: str, pages=None, case_sensitive: bool = False) -> dict:
    fitz = _fitz()
    if not query:
        raise PdfToolError("пустой запрос")
    doc = _open(path)
    try:
        hits = []
        for idx in parse_pages(pages, doc.page_count):
            page = doc[idx]
            for h in search(page, query, case_sensitive):
                hits.append({"page": idx + 1, "rect": _rect_list(_shown(h.rect, page)), "line": h.line_text.strip()})
        return {"path": str(path), "query": query, "count": len(hits), "hits": hits[:500]}
    finally:
        doc.close()


# --------------------------------------------------------------------------- editing operations

def _write_line(page, point, line: str, font: str, size: float, color, bold: bool, italic: bool, morph=None):
    kwargs = {"fontsize": size, "color": color, "rotate": page.rotation}
    ff = font_file(font, bold, italic)
    if ff:
        kwargs.update(fontfile=ff, fontname="F" + Path(ff).stem)
    elif any(ord(ch) > 255 for ch in line):
        raise PdfToolError("не нашёл шрифт с кириллицей (нужны шрифты Windows или DejaVu)")
    if not ff:
        page.insert_text(point, line, morph=morph, **kwargs)
        return
    # Word by word: the font's space glyph would be read back as U+00A0 and break text search. The words
    # follow the writing direction of the page (the text is turned with the page).
    dx, dy = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}.get(page.rotation % 360, (1, 0))
    font_obj = _fitz().Font(fontfile=ff)
    adv = 0.0
    for m in re.finditer(r"\S+|\s+", line):
        if m.group().strip():
            page.insert_text(_fitz().Point(point.x + dx * adv, point.y + dy * adv), m.group(), morph=morph, **kwargs)
        adv += font_obj.text_length(m.group(), fontsize=size)


def _text_width(text: str, font: str, size: float, bold: bool, italic: bool) -> float:
    fitz = _fitz()
    ff = font_file(font, bold, italic)
    f = fitz.Font(fontfile=ff) if ff else fitz.Font("helv")
    return f.text_length(text, fontsize=size)


def op_replace_text(doc, op: dict) -> dict:
    """Change text keeping its look. A line made of one style is rewritten whole, so the text after the
    replaced words moves with them; a line of mixed styles has only the found words rewritten."""
    fitz = _fitz()
    find = op.get("find") or ""
    if not find:
        raise PdfToolError("replace_text: нужен find")
    new = str(op.get("replace", ""))
    case = bool(op.get("case_sensitive", False))
    limit = int(op.get("max", 0)) or None       # how many places to change, 0 = all
    pages = parse_pages(op.get("page"), doc.page_count) if op.get("page") not in (None, "", "all")         else list(range(doc.page_count))
    done = 0
    warnings: list[str] = []
    for idx in pages:
        page = doc[idx]
        hits = search(page, find, case)
        if limit:
            hits = hits[:max(0, limit - done)]
        if not hits:
            continue
        lines: dict = {}
        for h in hits:
            lines.setdefault(h.line_id, []).append(h)
        jobs = []   # (text to write, style, origin x, baseline y, width the text had)
        for group in lines.values():
            first = group[0]
            if first.uniform:
                text = first.line_text
                for h in sorted(group, key=lambda h: h.start, reverse=True):
                    text = text[:h.start] + new + text[h.end:]
                text = text.rstrip()
                rect, st = first.line_rect, first.style
                ox = rect.x0
                jobs.append((rect, text, st, ox, st["origin"][1], True))
            else:
                for h in group:
                    jobs.append((h.rect, new, h.style, h.style["origin"][0], h.style["origin"][1], False))
        for rect, *_ in jobs:
            inset = rect.height * 0.15
            page.add_redact_annot(fitz.Rect(rect.x0, rect.y0 + inset, rect.x1, rect.y1 - inset), fill=False)
        # Only text goes; pictures and lines under it stay.
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        for rect, text, st, ox, oy, whole in jobs:
            font = op.get("font") or st["font"]
            size = float(op.get("size") or st["size"])
            bold = bool(op["bold"]) if "bold" in op else st["bold"]
            italic = bool(op["italic"]) if "italic" in op else st["italic"]
            color = parse_color(op.get("color") or st["color"])
            width = max((_text_width(s, font, size, bold, italic) for s in text.split(chr(10))), default=0)
            if op.get("shrink_to_fit", False) and width > rect.width + 0.5:
                size = max(4.0, size * rect.width / width)
                width = rect.width
            limit_x = page.rect.x1 - 10
            if ox + width > limit_x:
                warnings.append(f"стр. {idx + 1}: текст «{text[:30]}» выходит за правый край страницы")
            elif width > rect.width + 1.0 and not whole:
                warnings.append(f"стр. {idx + 1}: после «{new[:20]}» текст в строке мог наложиться, проверьте pdf_get_text")
            for i, line in enumerate(text.split(chr(10))):
                if line.strip():
                    _write_line(page, fitz.Point(ox, oy + i * size * LEADING), line, font, size, color, bold, italic)
        done += len(hits)
    res = {"op": "replace_text", "find": find, "replaced": done}
    if warnings:
        res["warnings"] = warnings[:10]
    return res


def op_add_text(doc, op: dict) -> dict:
    fitz = _fitz()
    page = _page_of(doc, op)
    text = str(op.get("text", ""))
    if not text:
        raise PdfToolError("add_text: нужен text")
    if "x" not in op or "y" not in op:
        raise PdfToolError("add_text: нужны x и y (пункты от левого верхнего угла; это верх первой строки)")
    size = float(op.get("size", 12))
    font = op.get("font") or "Arial"
    bold, italic = bool(op.get("bold", False)), bool(op.get("italic", False))
    color = parse_color(op.get("color"))
    angle = float(op.get("angle", 0))
    x, y = float(op["x"]), float(op["y"]) + size * 0.8     # y of the baseline of the first line
    derot = page.derotation_matrix
    lines = text.split("\n")
    width = max((_text_width(s, font, size, bold, italic) for s in lines), default=0) or size
    height = size * 0.25 + size * 0.8 + (len(lines) - 1) * size * LEADING
    morph = None
    if angle:
        c = fitz.Point(x + width / 2, float(op["y"]) + height / 2)
        morph = (c * derot, fitz.Matrix(-angle))
    if op.get("white_bg"):
        box = fitz.Rect(x - PAD, float(op["y"]) - PAD, x + width + PAD, float(op["y"]) + height + PAD) * derot
        if morph:
            page.draw_quad(box.quad.morph(*morph), color=None, fill=(1, 1, 1), overlay=True)
        else:
            page.draw_rect(box.normalize(), color=None, fill=(1, 1, 1), overlay=True)
    for i, line in enumerate(lines):
        if line.strip():
            _write_line(page, fitz.Point(x, y + i * size * LEADING) * derot, line, font, size, color, bold, italic, morph)
    return {"op": "add_text", "page": int(op["page"]),
            "rect": [round(x, 1), round(float(op["y"]), 1), round(x + width, 1), round(float(op["y"]) + height, 1)]}


def op_erase(doc, op: dict) -> dict:
    fitz = _fitz()
    page = _page_of(doc, op)
    rect = _need_rect(op) * page.derotation_matrix
    rect.normalize()
    mode = str(op.get("mode", "white"))
    if mode == "text":      # remove the text, keep the background
        page.add_redact_annot(rect, fill=False)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    else:                   # paint the area (text, pictures and lines under it go)
        fill = parse_color(op.get("fill", "#ffffff"), (1, 1, 1))
        page.add_redact_annot(rect, fill=fill)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
    return {"op": "erase", "page": int(op["page"]), "mode": mode}


def op_add_image(doc, op: dict) -> dict:
    fitz = _fitz()
    page = _page_of(doc, op)
    src = Path(op.get("path", ""))
    if not src.is_file():
        raise PdfToolError(f"add_image: нет файла {src}")
    rect = _need_rect(op) * page.derotation_matrix
    rect.normalize()
    page.insert_image(rect, filename=str(src), rotate=page.rotation,
                      keep_proportion=bool(op.get("keep_proportion", True)), overlay=True)
    return {"op": "add_image", "page": int(op["page"]), "path": str(src)}


OPS = {"replace_text": op_replace_text, "add_text": op_add_text, "erase": op_erase, "add_image": op_add_image}


def edit(path, output, operations: list[dict]) -> dict:
    """Apply the operations in order and save to ``output`` (the source file is never changed)."""
    if not operations:
        raise PdfToolError("пустой список operations")
    doc = _open(path)
    try:
        results = []
        for n, op in enumerate(operations, 1):
            kind = op.get("op")
            if kind not in OPS:
                raise PdfToolError(f"операция {n}: неизвестный op «{kind}», есть {', '.join(OPS)}")
            try:
                results.append(OPS[kind](doc, op))
            except PdfToolError as exc:
                raise PdfToolError(f"операция {n} ({kind}): {exc}") from exc
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out, garbage=3, deflate=True)
        return {"output": str(out), "pages": doc.page_count, "results": results}
    finally:
        doc.close()


# --------------------------------------------------------------------------- page operations

def pages_op(operation: str, output, path=None, files=None, pages=None, angle: int = 90, every: int = 1) -> dict:
    fitz = _fitz()
    out = Path(output)
    if operation == "merge":
        if not files or len(files) < 2:
            raise PdfToolError("merge: нужен список files из двух и больше PDF")
        merged = fitz.open()
        try:
            for f in files:
                with _open(f) as d:
                    merged.insert_pdf(d)
            out.parent.mkdir(parents=True, exist_ok=True)
            merged.save(out, garbage=3, deflate=True)
            return {"output": str(out), "pages": merged.page_count}
        finally:
            merged.close()
    if not path:
        raise PdfToolError(f"{operation}: нужен path")
    doc = _open(path)
    try:
        total = doc.page_count
        if operation == "extract":       # also reorders: pages "3,1,2"
            doc.select(parse_pages(pages, total, default_all=False))
        elif operation == "delete":
            gone = set(parse_pages(pages, total, default_all=False))
            if len(gone) >= total:
                raise PdfToolError("нельзя удалить все страницы")
            doc.select([i for i in range(total) if i not in gone])
        elif operation == "rotate":
            if angle % 90:
                raise PdfToolError("angle должен быть кратен 90")
            for i in parse_pages(pages, total):
                doc[i].set_rotation((doc[i].rotation + angle) % 360)
        elif operation == "split":
            step = max(1, int(every))
            out.mkdir(parents=True, exist_ok=True)
            files_out = []
            for start in range(0, total, step):
                part = fitz.open()
                part.insert_pdf(doc, from_page=start, to_page=min(total, start + step) - 1)
                target = out / f"{Path(path).stem}_{start + 1:03d}-{min(total, start + step):03d}.pdf"
                part.save(target, garbage=3, deflate=True)
                part.close()
                files_out.append(str(target))
            return {"output_dir": str(out), "files": files_out}
        else:
            raise PdfToolError("operation: merge, extract, delete, rotate или split")
        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out, garbage=3, deflate=True)
        return {"output": str(out), "pages": doc.page_count}
    finally:
        doc.close()
