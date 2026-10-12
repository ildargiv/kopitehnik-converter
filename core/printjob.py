"""Printing without a window: paper sizes, printer margins, placing a page on paper, and the print job itself.

Shared by the print dialog (ui/printing.py) and the MCP server (core/mcp_tools.py)."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

PDF_PRINTER = "::pdf::"

# key, size in mm, standard page size when the driver knows it
PAPERS = [
    ("a4", (210.0, 297.0), QPageSize.PageSizeId.A4),
    ("a3", (297.0, 420.0), QPageSize.PageSizeId.A3),
    ("a5", (148.0, 210.0), QPageSize.PageSizeId.A5),
    ("a6", (105.0, 148.0), QPageSize.PageSizeId.A6),
    ("10x15", (100.0, 150.0), None),
    ("13x18", (130.0, 180.0), None),
    ("15x21", (150.0, 210.0), None),
    ("20x30", (200.0, 300.0), None),
    ("letter", (215.9, 279.4), QPageSize.PageSizeId.Letter),
]
PAPER_BY_KEY = {k: (mm, pid) for k, mm, pid in PAPERS}


def page_size(key: str) -> QPageSize:
    (w, h), pid = PAPER_BY_KEY[key]
    if pid is not None:
        return QPageSize(pid)
    return QPageSize(QSizeF(w, h), QPageSize.Unit.Millimeter, key)


def make_printer(name: str | None) -> QPrinter:
    if name and name != PDF_PRINTER:
        info = QPrinterInfo.printerInfo(name)
        if not info.isNull():
            return QPrinter(info, QPrinter.PrinterMode.HighResolution)
    return QPrinter(QPrinter.PrinterMode.HighResolution)


_MARGIN_CACHE: dict[tuple, tuple[float, float, float, float]] = {}


def hardware_margins(name: str, key: str, landscape: bool) -> tuple[float, float, float, float]:
    """Left, top, right, bottom margins in mm that the printer cannot print on."""
    cache_key = (name, key, landscape)
    if cache_key in _MARGIN_CACHE:
        return _MARGIN_CACHE[cache_key]
    margins = (0.0, 0.0, 0.0, 0.0)
    if name != PDF_PRINTER:
        try:
            pr = make_printer(name)
            pr.setPageSize(page_size(key))
            pr.setPageOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait)
            pr.setFullPage(False)
            paper = pr.paperRect(QPrinter.Unit.Millimeter)
            page = pr.pageRect(QPrinter.Unit.Millimeter)
            raw = (page.left() - paper.left(), page.top() - paper.top(),
                   paper.right() - page.right(), paper.bottom() - page.bottom())
            margins = tuple(min(30.0, max(0.0, m)) for m in raw)
        except Exception:
            margins = (4.0, 4.0, 4.0, 4.0)
    _MARGIN_CACHE[cache_key] = margins
    return margins


def place(img_size: tuple[int, int], dpi: int, paper: QRectF, page: QRectF, mode: str, res: int):
    """Target rectangle on the page and the source rectangle of the image to draw there."""
    w, h = img_size
    src = QRectF(0, 0, w, h)
    if mode == "actual":
        tw, th = w / dpi * res, h / dpi * res
        target = QRectF(paper.center().x() - tw / 2, paper.center().y() - th / 2, tw, th)
        return target, src   # what does not fit is clipped by the paper
    area = paper if mode == "fill" else page
    k = (max if mode == "fill" else min)(area.width() / w, area.height() / h)
    tw, th = w * k, h * k
    target = QRectF(area.center().x() - tw / 2, area.center().y() - th / 2, tw, th)
    if mode == "fill":   # crop the overflow so nothing is drawn outside the paper
        target = target.intersected(area)
        src = QRectF((target.left() - (area.center().x() - tw / 2)) / k,
                     (target.top() - (area.center().y() - th / 2)) / k,
                     target.width() / k, target.height() / k)
    return target, src


def parse_range(text: str, total: int) -> list[int] | None:
    """'1-3, 5, 8-' -> sheet numbers (1-based) in order; None when the text is not a valid range."""
    text = text.replace(" ", "")
    if not text:
        return None
    chosen: list[int] = []
    for part in text.split(","):
        m = re.fullmatch(r"(\d+)-(\d*)|-(\d+)|(\d+)", part)
        if not m:
            return None
        if m.group(4):
            a = b = int(m.group(4))
        elif m.group(3):
            a, b = 1, int(m.group(3))
        else:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else total
        if a < 1 or a > b:
            return None
        chosen.extend(n for n in range(a, min(b, total) + 1) if n not in chosen)
    return chosen or None


def printers() -> tuple[list[str], str]:
    """Names of installed printers and the default one."""
    return [i.printerName() for i in QPrinterInfo.availablePrinters()], QPrinterInfo.defaultPrinterName()


def pil_to_qimage(img) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    return QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888).copy()


def print_pages(pages, printer: QPrinter, printer_name: str, paper_key: str, landscape: bool, dpi: int,
                mode: str = "fit", margin_mm: float = 0.0, gray: bool = False, rotate: bool = True,
                copies: int = 1, wanted: set[int] | None = None) -> int:
    """Send finished pages (PIL images) to ``printer``. Returns the number of pages printed.

    ``mode`` is fit (whole page inside the margins), fill (paper filled, overflow cropped) or actual (real size by dpi).
    ``wanted`` is a set of 1-based page numbers, None for all of them."""
    printer.setPageSize(page_size(paper_key))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait)
    printer.setFullPage(True)   # the program places the page itself, so margins are exact
    printer.setColorMode(QPrinter.ColorMode.GrayScale if gray else QPrinter.ColorMode.Color)
    repeat = 1
    if copies > 1:
        if printer.supportsMultipleCopies():
            printer.setCopyCount(copies)
        else:
            repeat = copies
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("принтер не принял задание")
    try:
        res = printer.resolution()
        pf = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
        paper = QRectF(printer.paperRect(QPrinter.Unit.DevicePixel))
        paper.translate(-pf.left(), -pf.top())
        l, t_, r, b = (max(margin_mm, m) * res / 25.4 for m in hardware_margins(printer_name, paper_key, landscape))
        page = paper.adjusted(l, t_, -r, -b)
        printed = 0
        for number, img in enumerate(pages, 1):
            if wanted is not None and number not in wanted:
                continue
            if gray:
                img = img.convert("L").convert("RGB")
            if rotate and img.width != img.height and (img.width > img.height) != (paper.width() > paper.height()):
                img = img.rotate(90, expand=True)
            target, src = place(img.size, dpi, paper, page, mode, res)
            qimg = pil_to_qimage(img)
            for _ in range(repeat):
                if printed:
                    printer.newPage()
                painter.save()
                painter.setClipRect(paper)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawImage(target, qimg, src)
                painter.restore()
                printed += 1
        return printed
    finally:
        painter.end()
