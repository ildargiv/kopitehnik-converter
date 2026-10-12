"""Placing several photos on one sheet (contact sheet, photo prints, ID photos)."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

# Paper sizes in cm (short side, long side)
PAPERS: dict[str, tuple[float, float]] = {
    "a3": (29.7, 42.0),
    "a4": (21.0, 29.7),
    "a5": (14.8, 21.0),
    "10x15": (10.0, 15.0),
    "13x18": (13.0, 18.0),
    "15x21": (15.0, 21.0),
    "20x30": (20.0, 30.0),
}

CAPTION_MM = 6.0


@dataclass
class SheetSettings:
    enabled: bool = False
    paper: str = "a4"
    landscape: bool = False
    cols: int = 2
    rows: int = 2
    margin_mm: float = 10.0
    gap_mm: float = 5.0
    fill: bool = False        # False: whole photo inside the cell, True: cell filled, photo cropped
    captions: bool = False    # file name under every photo
    copies: int = 1           # copies of every photo; 0 = fill whole sheet(s) with each photo
    photo_w_cm: float = 0.0   # fixed photo size; 0 = grid mode (columns x rows)
    photo_h_cm: float = 0.0
    auto_rotate: bool = True  # turn a photo by 90 degrees when that fits the cell better
    cut_marks: bool = False   # little cut marks in the margins
    preset: str = "custom"

    @property
    def fixed_size(self) -> bool:
        return self.photo_w_cm > 0 and self.photo_h_cm > 0

    @property
    def per_sheet(self) -> int:
        return len(geometry(self, 150)[2])


# Ready layouts for typical photo-lab jobs. Keys of the dict are SheetSettings fields.
PRESETS: dict[str, dict] = {
    "a4_grid": dict(paper="a4", landscape=False, cols=2, rows=2, photo_w_cm=0.0, photo_h_cm=0.0,
                    margin_mm=10.0, gap_mm=5.0, fill=False, captions=False, copies=1, cut_marks=False),
    "contact": dict(paper="a4", landscape=False, cols=4, rows=5, photo_w_cm=0.0, photo_h_cm=0.0,
                    margin_mm=10.0, gap_mm=3.0, fill=False, captions=True, copies=1, cut_marks=False),
    "p10x15_a4": dict(paper="a4", landscape=False, photo_w_cm=10.0, photo_h_cm=15.0,
                      margin_mm=3.0, gap_mm=2.0, fill=True, captions=False, copies=1, cut_marks=True),
    "p9x12_a4": dict(paper="a4", landscape=False, photo_w_cm=9.0, photo_h_cm=12.0,
                     margin_mm=5.0, gap_mm=2.0, fill=True, captions=False, copies=1, cut_marks=True),
    "id3x4": dict(paper="10x15", landscape=True, photo_w_cm=3.0, photo_h_cm=4.0,
                  margin_mm=3.0, gap_mm=2.0, fill=True, captions=False, copies=0, cut_marks=True),
    "id35x45": dict(paper="10x15", landscape=True, photo_w_cm=3.5, photo_h_cm=4.5,
                    margin_mm=3.0, gap_mm=2.0, fill=True, captions=False, copies=0, cut_marks=True),
    "id4x6": dict(paper="10x15", landscape=True, photo_w_cm=4.0, photo_h_cm=6.0,
                  margin_mm=3.0, gap_mm=2.0, fill=True, captions=False, copies=0, cut_marks=True),
    "id3x4_a4": dict(paper="a4", landscape=False, photo_w_cm=3.0, photo_h_cm=4.0,
                     margin_mm=5.0, gap_mm=2.0, fill=True, captions=False, copies=0, cut_marks=True),
}


def apply_preset(s: SheetSettings, key: str) -> None:
    for k, v in PRESETS.get(key, {}).items():
        setattr(s, k, v)
    s.preset = key


def _mm(value_mm: float, dpi: int) -> int:
    return round(value_mm / 25.4 * dpi)


def _caption_px(s: SheetSettings, dpi: int) -> int:
    return _mm(CAPTION_MM, dpi) if s.captions else 0


def _count(avail: int, size: int, gap: int) -> int:
    return max(0, (avail + gap) // (size + gap)) if size > 0 else 0


def geometry(s: SheetSettings, dpi: int):
    """Page size, cell size and cell positions in pixels."""
    short, long = PAPERS.get(s.paper, PAPERS["a4"])
    w_cm, h_cm = (long, short) if s.landscape else (short, long)
    page_w, page_h = round(w_cm / 2.54 * dpi), round(h_cm / 2.54 * dpi)
    margin, gap = _mm(s.margin_mm, dpi), _mm(s.gap_mm, dpi)
    avail_w, avail_h = page_w - 2 * margin, page_h - 2 * margin
    if s.fixed_size:
        cap = _caption_px(s, dpi)
        pw, ph = round(s.photo_w_cm / 2.54 * dpi), round(s.photo_h_cm / 2.54 * dpi)
        best = None
        for cw, ch in ((pw, ph), (ph, pw)):
            ch += cap
            cols, rows = _count(avail_w, cw, gap), _count(avail_h, ch, gap)
            if best is None or cols * rows > best[0]:
                best = (cols * rows, cols, rows, cw, ch)
        _, cols, rows, cell_w, cell_h = best
        if cols * rows == 0:  # photo larger than the paper: one cell, shrunk to the page
            cols = rows = 1
            cell_w, cell_h = max(1, avail_w), max(1, avail_h)
        block_w, block_h = cols * cell_w + (cols - 1) * gap, rows * cell_h + (rows - 1) * gap
        x0, y0 = (page_w - block_w) // 2, (page_h - block_h) // 2
    else:
        cols, rows = max(1, s.cols), max(1, s.rows)
        cell_w = max(1, (avail_w - gap * (cols - 1)) // cols)
        cell_h = max(1, (avail_h - gap * (rows - 1)) // rows)
        x0 = y0 = margin
    cells = [(x0 + c * (cell_w + gap), y0 + r * (cell_h + gap)) for r in range(rows) for c in range(cols)]
    return (page_w, page_h), (cell_w, cell_h), cells


def photo_area(s: SheetSettings, cell: tuple[int, int], dpi: int) -> tuple[int, int]:
    """Cell size left for the photo itself (caption takes the bottom strip)."""
    cw, ch = cell
    if s.captions:
        ch = max(1, ch - _mm(CAPTION_MM, dpi))
    return cw, ch


def fit_to_area(img: Image.Image, area: tuple[int, int], fill: bool) -> Image.Image:
    aw, ah = area
    w, h = img.size
    k = max(aw / w, ah / h) if fill else min(aw / w, ah / h)
    resized = img.resize((max(1, round(w * k)), max(1, round(h * k))), Image.Resampling.LANCZOS)
    if fill:
        left, top = (resized.width - aw) // 2, (resized.height - ah) // 2
        resized = resized.crop((left, top, left + aw, top + ah))
    return resized


def fit_photo(img: Image.Image, area: tuple[int, int], s: SheetSettings) -> Image.Image:
    """Resize a photo for its cell, turning it first when that wastes less paper."""
    if s.auto_rotate and img.width != img.height and area[0] != area[1] \
            and (img.width > img.height) != (area[0] > area[1]):
        img = img.transpose(Image.Transpose.ROTATE_90)
    return fit_to_area(img, area, s.fill)


def _draw_cut_marks(draw: ImageDraw.ImageDraw, page, cell, cells, dpi: int) -> None:
    cw, ch = cell
    xs = sorted({x for x, _ in cells} | {x + cw for x, _ in cells})
    ys = sorted({y for _, y in cells} | {y + ch for _, y in cells})
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]
    length = max(4, _mm(3.0, dpi))
    off = max(1, _mm(0.5, dpi))
    width = max(1, round(dpi / 150))
    for x in xs:
        if y0 - off - 2 > 0:
            draw.line([(x, max(0, y0 - off - length)), (x, y0 - off)], fill="black", width=width)
        if y1 + off + 2 < page[1]:
            draw.line([(x, y1 + off), (x, min(page[1] - 1, y1 + off + length))], fill="black", width=width)
    for y in ys:
        if x0 - off - 2 > 0:
            draw.line([(max(0, x0 - off - length), y), (x0 - off, y)], fill="black", width=width)
        if x1 + off + 2 < page[0]:
            draw.line([(x1 + off, y), (min(page[0] - 1, x1 + off + length), y)], fill="black", width=width)


def _caption_font(size_px: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size_px)
        except OSError:
            continue
    return ImageFont.load_default()


def expand_copies(items: list, s: SheetSettings, per: int) -> list:
    """Repeat every photo: ``copies`` times, or enough to fill whole sheets when copies is 0."""
    n = s.copies if s.copies > 0 else per
    return [it for it in items for _ in range(n)]


def compose(items: list[tuple[str, Image.Image]], s: SheetSettings, dpi: int) -> list[Image.Image]:
    """Build sheets from (caption, image) pairs; the images are already sized for a cell."""
    page, cell, cells = geometry(s, dpi)
    area = photo_area(s, cell, dpi)
    font = _caption_font(max(10, _mm(CAPTION_MM * 0.6, dpi)))
    sheets: list[Image.Image] = []
    per = len(cells)
    items = expand_copies(items, s, per)
    for start in range(0, len(items), per):
        sheet = Image.new("RGB", page, "white")
        draw = ImageDraw.Draw(sheet)
        for (label, placed), (x, y) in zip(items[start:start + per], cells):
            sheet.paste(placed, (x + (area[0] - placed.width) // 2, y + (area[1] - placed.height) // 2))
            if s.captions:
                text = label if len(label) <= 40 else label[:37] + "…"
                draw.text((x + cell[0] // 2, y + area[1] + _mm(CAPTION_MM, dpi) // 2), text,
                          fill="#444444", font=font, anchor="mm")
        if s.cut_marks:
            _draw_cut_marks(draw, page, cell, cells, dpi)
        sheets.append(sheet)
    return sheets
