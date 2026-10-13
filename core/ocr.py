"""Reading scanned pages: clean the scan up, find the text lines (RapidOCR, local, no cloud), guess their look.

Steps: ``prepare`` (straighten, cut the margins, even out light, remove noise, contrast) -> ``recognize``
(lines with their place and size) -> ``style_lines`` (font, size, weight, colour). The PDF editor turns the
lines into ordinary text objects.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

MAX_SIDE = 3600          # longest side in pixels worked on (about 300 dpi for A4)
DESC = set("рудцщфgjpqy,;()[]{}/|_@§")     # glyphs that go below the baseline
_engine = None


def models_dir() -> Path:
    """Where the recognition models live: next to the program when bundled, else the user's folder."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    bundled = base / "assets" / "ocr_models"
    if bundled.exists():
        return bundled
    root = Path(os.environ.get("APPDATA", Path.home())) / "KopiTehnikConverter" / "ocr_models"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------------------------------------
# 1. Preparing the scan
# ---------------------------------------------------------------------------------------------------------
@dataclass
class Prepared:
    image: np.ndarray                 # cleaned page, BGR
    angle: float = 0.0                # degrees the page was turned (counter-clockwise positive)
    crop: tuple[int, int, int, int] = (0, 0, 0, 0)   # x0, y0, x1, y1 cut out of the turned page
    notes: list[str] = field(default_factory=list)


def _binary_text(gray: np.ndarray) -> np.ndarray:
    """Dark text on light paper as a white-on-black mask."""
    blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
    return cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 41, 18)


def estimate_skew(gray: np.ndarray, limit: float = 12.0) -> float:
    """Tilt of the text lines in degrees (positive: lines rise to the right), by the sharpest row profile."""
    s = 1000.0 / max(gray.shape)
    small = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else gray
    bw = _binary_text(small)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    ys, xs = np.nonzero(bw)
    if len(xs) < 200:
        return 0.0
    pts = np.stack([xs, ys], 1).astype(np.float32)
    cx, cy = small.shape[1] / 2, small.shape[0] / 2
    pts[:, 0] -= cx
    pts[:, 1] -= cy
    h = small.shape[0]

    def score(a: float) -> float:
        t = np.tan(np.radians(a))
        rows = np.round(pts[:, 1] + pts[:, 0] * t + h).astype(np.int64)  # rotate: y' = y + x*tan(a)
        hist = np.bincount(rows, minlength=2 * h + 2).astype(np.float64)
        return float(np.sum(np.diff(hist) ** 2))

    best = max(np.arange(-limit, limit + 0.01, 0.5), key=score)
    fine = max(np.arange(best - 0.5, best + 0.51, 0.1), key=score)
    return float(fine)


def _rotate(img: np.ndarray, angle: float, fill) -> np.ndarray:
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, M, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=fill)


def _paper_box(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    """The bright sheet on a darker background (scanner lid, table); None when the page fills the picture."""
    h, w = gray.shape
    s = 800.0 / max(h, w)
    small = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 3)
    t, mask = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Otsu separates sheet from background only when the background really is darker
    if np.mean(small[mask > 0]) - np.mean(small[mask == 0] if (mask == 0).any() else small) < 25:
        return None
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    x, y, bw, bh = cv2.boundingRect(c)
    if bw * bh < 0.35 * small.size or bw * bh > 0.97 * small.size:
        return None
    return int(x / s), int(y / s), int((x + bw) / s), int((y + bh) / s)


def _inner_rect(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    """Largest rim-trimmed rectangle that is all paper: rows and columns that are mostly bright."""
    h, w = gray.shape
    s = 600.0 / max(h, w)
    small = cv2.GaussianBlur(cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), (0, 0), 2)
    paper = float(np.percentile(small, 70))
    bright = small > 0.62 * paper
    x0, y0, x1, y1 = 0, 0, bright.shape[1], bright.shape[0]
    while True:                               # shave the edge with the most dark pixels until all is paper
        sub = bright[y0:y1, x0:x1]
        if sub.size == 0 or (y1 - y0) < 20 or (x1 - x0) < 20:
            return None
        edges = {"l": sub[:, 0].mean(), "r": sub[:, -1].mean(), "t": sub[0].mean(), "b": sub[-1].mean()}
        k, v = min(edges.items(), key=lambda kv: kv[1])
        if v > 0.985:
            break
        x0, y0, x1, y1 = x0 + (k == "l"), y0 + (k == "t"), x1 - (k == "r"), y1 - (k == "b")
    m = 3
    x0, y0, x1, y1 = x0 + m, y0 + m, x1 - m, y1 - m
    return int(x0 / s), int(y0 / s), int(x1 / s), int(y1 / s)


def _content_box(gray: np.ndarray, margin: float) -> tuple[int, int, int, int]:
    """Box round the printed text, with ``margin`` (fraction of the side) left around it."""
    bw = cv2.morphologyEx(_binary_text(gray), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    bw = cv2.dilate(bw, np.ones((9, 25), np.uint8))
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    boxes = [cv2.boundingRect(c) for c in cnts if cv2.contourArea(c) > 0.00005 * h * w]
    if not boxes:
        return 0, 0, w, h
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    mx, my = int(margin * w), int(margin * h)
    return max(0, x0 - mx), max(0, y0 - my), min(w, x1 + mx), min(h, y1 + my)


def prepare(img: np.ndarray, deskew: bool = True, crop: bool = True, clean: bool = True) -> Prepared:
    """Straighten, cut the margins, even out the light, remove noise and strengthen contrast."""
    notes: list[str] = []
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    box = _paper_box(gray) if crop else None
    if box:                                    # take the sheet out of its dark surroundings first
        x0, y0, x1, y1 = box
        img = img[y0:y1, x0:x1]
        gray = gray[y0:y1, x0:x1]
        notes.append("sheet cut out of the background")
    angle = estimate_skew(gray) if deskew else 0.0
    if abs(angle) >= 0.15:
        # rows are y' = y + x*tan(a): lines that rise to the right need turning clockwise by a
        bg = tuple(int(v) for v in np.percentile(img.reshape(-1, 3), 90, axis=0))
        img = _rotate(img, -angle, bg)
        notes.append(f"straightened by {angle:+.1f} degrees")
    else:
        angle = 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if box or abs(angle):
        inner = _inner_rect(gray) if crop else None   # turning leaves dark wedges in the corners: cut them
        if inner:
            x0, y0, x1, y1 = inner
            img, gray = img[y0:y1, x0:x1], gray[y0:y1, x0:x1]

    if clean:
        # light: divide every channel by its blurred background, so shadows and tint go
        k = max(31, (min(img.shape[:2]) // 25) | 1)
        chans = []
        for c in cv2.split(img):
            bgc = cv2.morphologyEx(c, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
            bgc = cv2.medianBlur(cv2.resize(bgc, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA), k // 4 | 1)
            bgc = cv2.resize(bgc, (c.shape[1], c.shape[0]), interpolation=cv2.INTER_LINEAR)
            chans.append(cv2.divide(c, np.maximum(bgc, 1), scale=250))
        img = cv2.merge(chans)
        # noise: a light blur keeps strokes, then specks (isolated dots) are painted over with paper
        img = cv2.fastNlMeansDenoisingColored(img, None, 4, 4, 5, 15) if max(img.shape[:2]) <= 3000 else \
            cv2.bilateralFilter(img, 5, 25, 25)
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ink = (g < 150).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        small_ids = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] <= 14]
        if small_ids:
            # a speck stands alone; a full stop or a dot over a letter has other ink close by
            near = cv2.boxFilter(ink.astype(np.float32), -1, (41, 41), normalize=False)
            lone = []
            for i in small_ids:
                x, y, bw_, bh_ = (int(v) for v in stats[i, :4])
                if near[y + bh_ // 2, x + bw_ // 2] - stats[i, cv2.CC_STAT_AREA] < 1:
                    lone.append(i)
            speck = np.isin(lab, lone)
            if speck.any():
                img[cv2.dilate(speck.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0] = 255
        # contrast: stretch so paper is white and the ink is dark, keeping stamps and signatures in colour
        lo, hi = np.percentile(g, 0.5), np.percentile(g, 60)
        lut = np.clip((np.arange(256, dtype=np.float32) - lo) / max(1.0, hi - lo) * 255, 0, 255)
        lut = (255 * (lut / 255) ** 1.15).astype(np.uint8)
        img = cv2.LUT(img, lut)
        notes.append("light evened out, noise removed, contrast raised")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cb = _content_box(gray, 0.04) if crop else (0, 0, img.shape[1], img.shape[0])
    if crop and (cb[2] - cb[0]) * (cb[3] - cb[1]) < 0.985 * gray.size:
        # keep a page-like frame: only the empty outer rim goes, never into the text
        h, w = gray.shape
        x0, y0, x1, y1 = cb
        pad = int(0.03 * max(w, h))
        cb = (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))
        img = img[cb[1]:cb[3], cb[0]:cb[2]]
        notes.append("margins trimmed")
    else:
        cb = (0, 0, img.shape[1], img.shape[0])
    return Prepared(img, angle, cb, notes)


# ---------------------------------------------------------------------------------------------------------
# 2. Reading the lines
# ---------------------------------------------------------------------------------------------------------
@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float                 # ink box, pixels
    conf: float = 1.0
    baseline: float = 0.0     # pixels
    size_px: float = 0.0
    font: str = "Times New Roman"
    bold: bool = False
    italic: bool = False
    color: str = "#000000"
    dens: float = 1.0


def get_engine():
    """RapidOCR with the Russian and English (Cyrillic + Latin) models; loads once."""
    global _engine
    if _engine is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        _engine = RapidOCR(params={
            "Global.model_root_dir": str(models_dir()),
            "Global.log_level": "error",
            "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.lang_type": LangRec.ESLAV,
            "Rec.model_type": ModelType.MOBILE,
            "Det.limit_side_len": 2048, "Det.limit_type": "max", "Det.box_thresh": 0.4, "Det.thresh": 0.25, "Det.unclip_ratio": 1.4,
        })
    return _engine


def _ink_box(bw: np.ndarray, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Shrink a detector box to the ink inside it."""
    H, W = bw.shape
    x0, y0, x1, y1 = box
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    sub = bw[y0:y1, x0:x1]
    if sub.size == 0 or not sub.any():
        return x0, y0, x1, y1
    sub = sub.copy()
    sub[:, sub.sum(0) > 0.8 * sub.shape[0]] = 0          # a vertical table rule is not part of the text either
    # a table rule or an underline is ink across (nearly) the whole width: it is not part of the text's height
    row_ink = sub.sum(1)
    rows = (row_ink > max(1, 0.012 * sub.shape[1])) & (row_ink < 0.9 * sub.shape[1])
    cols = sub.sum(0) > 0
    ry, rx = np.nonzero(rows)[0], np.nonzero(cols)[0]
    if len(ry) == 0 or len(rx) == 0:
        return x0, y0, x1, y1
    return x0 + int(rx[0]), y0 + int(ry[0]), x0 + int(rx[-1]) + 1, y0 + int(ry[-1]) + 1


def recognize(img: np.ndarray, min_conf: float = 0.35) -> list[Line]:
    """Text lines of a (prepared) page, top to bottom, with their boxes in pixels."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bw = (_binary_text(gray) > 0).astype(np.uint8)
    out = get_engine()(img)
    if out is None or out.boxes is None or len(out.txts) == 0:
        return []
    raw: list[Line] = []
    for poly, txt, sc in zip(out.boxes, out.txts, out.scores):
        txt = re.sub(r"^(\d+(?:\.\d+)*\.)(?=[A-Za-zА-Яа-яЁё])", r"\1 ", (txt or "").strip())
        if not txt or float(sc) < min_conf:
            continue
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        x0, y0, x1, y1 = _ink_box(bw, (int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1))
        raw.append(Line(txt, x0, y0, x1, y1, float(sc)))
    raw += _missed_lines(img, bw, raw, out_engine=get_engine(), min_conf=min_conf)
    return merge_lines(raw)


def _missed_lines(img, bw, found: list[Line], out_engine, min_conf: float) -> list[Line]:
    """Text bands the detector skipped (a speck or a stamp can fool it): read them with the recogniser alone."""
    if not found:
        return []
    H, W = bw.shape
    free = bw.copy()
    for ln in found:
        free[max(0, int(ln.y0) - 3):int(ln.y1) + 3, max(0, int(ln.x0) - 3):int(ln.x1) + 3] = 0
    free = cv2.morphologyEx(free, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    med_h = float(np.median([l.y1 - l.y0 for l in found]))
    glue = cv2.dilate(free, cv2.getStructuringElement(cv2.MORPH_RECT, (int(med_h * 1.2), max(3, int(med_h * 0.25)))))
    n, _, stats, _ = cv2.connectedComponentsWithStats(glue, connectivity=8)
    out: list[Line] = []
    for i in range(1, n):
        x, y, w, h, _a = (int(v) for v in stats[i])
        if not (0.6 * med_h <= h <= 2.2 * med_h) or w < 6 * med_h:
            continue
        x0, y0, x1, y1 = _ink_box(bw, (x, y, x + w, y + h))
        pad = int(0.25 * med_h)
        crop = img[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
        try:
            res = out_engine(crop, use_det=False, use_cls=False, use_rec=True)
        except Exception:
            continue
        if res is None or not res.txts:
            continue
        txt, sc = (res.txts[0] or "").strip(), float(res.scores[0])
        if txt and sc >= max(min_conf, 0.6):
            out.append(Line(txt, x0, y0, x1, y1, sc))
    return out


def merge_lines(lines: list[Line]) -> list[Line]:
    """Pieces of one printed line (the detector splits at big gaps) become one line, top to bottom."""
    lines = sorted(lines, key=lambda l: (l.y0 + l.y1) / 2)
    rows: list[list[Line]] = []
    for ln in lines:
        cy = (ln.y0 + ln.y1) / 2
        for row in rows:
            ref = row[0]
            rh = max(ref.y1 - ref.y0, ln.y1 - ln.y0)
            if abs(cy - (ref.y0 + ref.y1) / 2) < 0.4 * rh:
                row.append(ln)
                break
        else:
            rows.append([ln])
    out: list[Line] = []
    rows.sort(key=lambda r: sum((l.y0 + l.y1) / 2 for l in r) / len(r))
    for row in rows:
        row.sort(key=lambda l: l.x0)
        cur = row[0]
        for nxt in row[1:]:
            h = max(cur.y1 - cur.y0, nxt.y1 - nxt.y0)
            if nxt.x0 - cur.x1 < 1.2 * h:        # a normal word space or two: same line
                gap = max(0.0, nxt.x0 - cur.x1)
                spaces = max(1, round(gap / (0.3 * h)))
                cur = Line(cur.text + " " * min(spaces, 8) + nxt.text, cur.x0, min(cur.y0, nxt.y0),
                           nxt.x1, max(cur.y1, nxt.y1), min(cur.conf, nxt.conf))
            else:                                # a wide gap (signature, table column): keep apart
                out.append(cur)
                cur = nxt
        out.append(cur)
    return out


@dataclass
class PageResult:
    """A scanned page ready to be put into a PDF: the cleaned picture and its text lines in PDF points."""
    jpeg: bytes
    width: float
    height: float
    lines: list[dict]
    notes: list[str]


A4 = (595.276, 841.89)


def page_to_image(page, max_dpi: int = 300) -> tuple[np.ndarray, float]:
    """Render a PDF page for reading; returns the BGR picture and the dpi it was drawn at."""
    dpi = float(max_dpi)
    try:   # no need to draw finer than the scan itself
        infos = page.get_image_info()
        big = max(infos, key=lambda i: i["width"] * i["height"]) if infos else None
        if big and big["bbox"][2] - big["bbox"][0] > 1:
            native = big["width"] / ((big["bbox"][2] - big["bbox"][0]) / 72.0)
            dpi = max(100.0, min(float(max_dpi), native))
    except Exception:
        pass
    dpi = float(int(round(dpi)))
    pix = page.get_pixmap(dpi=int(dpi), alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    else:
        img = img[:, :, 2::-1].copy()
    return img, dpi


def process_image(img: np.ndarray, dpi: float, **opts) -> PageResult:
    """Everything for one page: prepare, read, style; then the lines in points of the new page."""
    prep = prepare(img, **{k: v for k, v in opts.items() if k in ("deskew", "crop", "clean")})
    lines = recognize(prep.image)
    style_lines(lines, prep.image)
    unify_sizes(lines)
    h, w = prep.image.shape[:2]
    pw, ph = w * 72.0 / dpi, h * 72.0 / dpi
    for a in (A4, A4[::-1]):                  # a page that is A4 within a few percent becomes exactly A4
        if abs(pw / a[0] - 1) < 0.04 and abs(ph / a[1] - 1) < 0.04:
            pw, ph = a
            break
    kx, ky = pw / w, ph / h
    ok, jpg = cv2.imencode(".jpg", prep.image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    out = [dict(text=l.text, x=l.x0 * kx, y=l.baseline * ky, size=l.size_px * ky, font=l.font, bold=l.bold,
                italic=l.italic, color=l.color, conf=l.conf,
                box=[l.x0 * kx, l.y0 * ky, l.x1 * kx, l.y1 * ky]) for l in lines]
    return PageResult(jpg.tobytes(), pw, ph, out, prep.notes)


def build_pdf(src: str | Path, dst: str | Path, **opts) -> list[PageResult]:
    """Scanned PDF in, searchable PDF out (cleaned picture with an invisible text layer). Used by tests and tools."""
    import pymupdf
    doc = pymupdf.open(src)
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    files = {"Arial": ("arial.ttf", "arialbd.ttf"), "Times New Roman": ("times.ttf", "timesbd.ttf")}
    out, results = pymupdf.open(), []
    for page in doc:
        img, dpi = page_to_image(page)
        res = process_image(img, dpi, **opts)
        results.append(res)
        p = out.new_page(width=res.width, height=res.height)
        p.insert_image(p.rect, stream=res.jpeg)
        for ln in res.lines:
            f = fonts / files.get(ln["font"], files["Arial"])[bool(ln["bold"])]
            font, adv = pymupdf.Font(fontfile=str(f)), 0.0
            for m in re.finditer(r"\S+|\s+", ln["text"]):     # word by word: no no-break spaces in the text layer
                if m.group().strip():
                    p.insert_text((ln["x"] + adv, ln["y"]), m.group(), fontsize=ln["size"], fontfile=str(f),
                                  fontname="F" + f.stem, render_mode=3)
                adv += font.text_length(m.group(), fontsize=ln["size"])
    out.save(dst, garbage=3, deflate=True)
    return results


# ---------------------------------------------------------------------------------------------------------
# 3. Look of the lines
# ---------------------------------------------------------------------------------------------------------
def _text_len(font_name: str, bold: bool, text: str, size: float = 1.0) -> float:
    import pymupdf
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    files = {"Arial": ("arial.ttf", "arialbd.ttf"), "Times New Roman": ("times.ttf", "timesbd.ttf")}[font_name]
    path = str(fonts / files[bool(bold)])
    if not os.path.exists(path):
        return len(text) * 0.5 * size
    return _FONT_CACHE.setdefault(path, pymupdf.Font(fontfile=path)).text_length(text, fontsize=size)


_FONT_CACHE: dict = {}
# Text height (ink of a normal line: ascender to baseline) as a share of the font size
_ASC = {"Arial": 0.72, "Times New Roman": 0.68}


def style_lines(lines: list[Line], img: np.ndarray) -> None:
    """Fill baseline, size, font, weight and colour of every line, in pixels of ``img``."""
    if not lines:
        return
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bw = (gray < 140).astype(np.uint8)
    dens = []
    for ln in lines:
        sub = bw[int(ln.y0):int(ln.y1), int(ln.x0):int(ln.x1)]
        dens.append(float(sub.mean()) if sub.size else 0.0)
    fits = []
    for ln, d in zip(lines, dens):
        flat = re.sub(r"\s+", " ", ln.text)
        has_desc = any(ch in DESC for ch in flat)
        has_asc = any(ch.isupper() or ch.isdigit() or ch in "бвдйЙфыьъ()/" or ch in "bdfhklt" for ch in flat)
        # ink height = ascender (if any) .. baseline (+ descender if any)
        asc_f = 0.72 if has_asc else 0.52
        desc_f = 0.2 if has_desc else 0.0
        size = (ln.y1 - ln.y0) / (asc_f + desc_f)
        ln.size_px = size
        ln.baseline = ln.y1 - desc_f * size
        sub = bw[int(ln.y0):int(ln.y1), int(ln.x0):int(ln.x1)]
        dt = cv2.distanceTransform(sub, cv2.DIST_L2, 3) if sub.size else sub
        ln.dens = float(dt[sub > 0].mean() / size) if sub.size and sub.any() else 0.0   # stroke thickness / size
        w = ln.x1 - ln.x0
        fits.append((ln, flat, w, size))
    t_med = float(np.median([l.dens for l in lines])) or 1e-6
    s_med = float(np.median([f[3] for f in fits]))
    for ln, flat, _w, size in fits:
        # bolder strokes, or the look of a heading: short, no full stop at the end, numbered or in capitals
        letters = [c for c in flat if c.isalpha()]
        caps = bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.8 and len(letters) > 5
        numbered = bool(re.match(r"^\d+(\.\d+)*\.?\s+\D", flat)) and len(flat.split()) <= 8
        heading = len(flat) < 70 and not flat.endswith((".", ",", ";", ":")) and (caps or numbered)
        ln.bold = ln.dens > 1.3 * t_med or (heading and size > 1.0 * s_med)
    # serif or sans for the whole page: the width of the printed text tells it (Times is narrower)
    err = {"Arial": 0.0, "Times New Roman": 0.0}
    for ln, flat, w, size in fits:
        if len(flat) < 12 or ln.bold:
            continue
        for f in err:
            err[f] += abs(np.log(w / max(1e-6, _text_len(f, False, flat, size))))
    page_font = min(err, key=err.get) if any(err.values()) else "Times New Roman"
    for ln, flat, w, size in fits:
        ln.font = page_font
        # fit the width exactly so the line occupies the same place as on the scan
        base = _text_len(page_font, ln.bold, ln.text, 1.0)
        if base > 0 and len(flat) >= 4:
            fit = w / base
            ln.size_px = float(np.clip(fit, 0.9 * size, 1.1 * size))
        # colour: the median of the darkest pixels of the line (black text stays black, stamps are blue)
        sub = img[int(ln.y0):int(ln.y1), int(ln.x0):int(ln.x1)].reshape(-1, 3)
        if len(sub):
            gs = sub.mean(1)
            dark = sub[gs <= np.percentile(gs, 8)]
            b, g, r = [float(v) for v in np.median(dark, axis=0)]
            mx, mn = max(r, g, b), min(r, g, b)
            ln.color = "#%02x%02x%02x" % (int(r), int(g), int(b)) if (mx - mn) > 60 and mn < 170 else "#000000"


def unify_sizes(lines: list[Line]) -> None:
    """One body size per page: lines within 15% of the typical size take exactly it (table rules and specks make
    single lines look taller); headings, which are clearly larger, keep theirs."""
    body = [l.size_px for l in lines if len(l.text) >= 4]
    if body:
        med = float(np.median(body))
        for ln in lines:
            # a short text (a number, a mark) has too few letters to measure: it takes the body size
            if len(ln.text) < 4 or abs(ln.size_px - med) / med < 0.2:
                ln.size_px = med
