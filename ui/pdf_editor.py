"""PDF editor: text you add or pick up from the page stays a movable, editable object until saved (PyMuPDF)."""
from __future__ import annotations

import base64
import copy
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QThread, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QKeySequence, QPainter, QPen, QShortcut, QTransform,
)
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from .widgets import Segmented, icon_button

FONTS_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
# Font name -> files for regular, bold, italic, bold italic.
FONTS = {
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "Courier New": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
}
UNDO_LIMIT = 30
ROT_DIST = 26.0     # distance of the rotate handle above the frame, in view pixels
HANDLE = 5.0       # half-size of a resize handle, in view pixels
MIN_IMAGE = 8.0    # smallest picture side, in points
LEADING = 1.2      # line spacing of added text, in font sizes
PAD = 2.0          # white background margin around a text object, in points
SIDECAR = ".edits.json"


def font_file(name: str, bold: bool, italic: bool) -> str | None:
    files = FONTS.get(name, FONTS["Arial"])
    for f in (files[bold + 2 * italic], files[0]):
        if (FONTS_DIR / f).exists():
            return str(FONTS_DIR / f)
    return None


_families: dict[str, str] = {}


def qt_family(path: str | None, fallback: str) -> str:
    """Load the font file into Qt, so the preview uses exactly the font written into the PDF."""
    if not path:
        return fallback
    if path not in _families:
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _families[path] = fams[0] if fams else fallback
    return _families[path]


def guess_font(pdf_font: str) -> str:
    """Closest font we have for a font name found in the PDF."""
    low = pdf_font.lower()
    for key, name in (("times", "Times New Roman"), ("cour", "Courier New"), ("calibri", "Calibri"),
                      ("segoe", "Segoe UI"), ("verdana", "Verdana"), ("serif", "Times New Roman")):
        if key in low and "sans" not in low:
            return name
    return "Arial"


@dataclass
class TextItem:
    """Text not yet written into the PDF. x and baseline are in points of the page as shown."""
    page: int
    x: float
    y: float               # baseline of the first line
    text: str = ""
    font: str = "Arial"
    size: float = 12.0
    color: str = "#000000"
    bold: bool = False
    italic: bool = False
    white: bool = False    # white background under the text
    leading: float = LEADING
    angle: float = 0.0     # free rotation in degrees, clockwise, about the centre of the box
    ocr: bool = False      # read from a scan and untouched: only an invisible, searchable layer over the picture
    cover: list | None = None   # page area (x0, y0, x1, y1) painted white once the text is changed or moved
    flag: bool = False     # doubtful, shown with a yellow mark
    note: str = ""         # why it is doubtful

    def qfont(self, zoom: float) -> QFont:
        f = QFont(qt_family(font_file(self.font, self.bold, self.italic), self.font))
        f.setPixelSize(max(1, round(self.size * zoom)))
        f.setBold(self.bold)
        f.setItalic(self.italic)
        f.setKerning(False)  # PDF text is written without kerning
        return f

    def lines(self) -> list[str]:
        return self.text.split("\n")

    def rect(self, zoom: float) -> QRectF:
        """Bounding box in view pixels."""
        fm = QFontMetricsF(self.qfont(zoom))
        lines = self.lines()
        w = max((fm.horizontalAdvance(s) for s in lines), default=0) or fm.horizontalAdvance(" ")
        top = self.y * zoom - fm.ascent()
        h = fm.ascent() + fm.descent() + (len(lines) - 1) * self.size * self.leading * zoom
        return QRectF(self.x * zoom, top, w, h)


@dataclass
class ImageItem:
    """A picture (added, or taken out of the page) that can be moved and resized until saved."""
    page: int
    x: float               # top-left corner, points of the page as shown
    y: float
    w: float
    h: float
    data: bytes = b""      # an image file (PNG), or a one-page PDF when ``vector``
    angle: float = 0.0
    vector: bool = False   # text taken from the page: real vector text with its own font
    text_src: str = ""     # for such text: the editable text object it turns into on double-click

    def rect(self, zoom: float) -> QRectF:
        return QRectF(self.x * zoom, self.y * zoom, self.w * zoom, self.h * zoom)


_qimages: dict[int, tuple[bytes, QImage]] = {}


def qimage_of(item: ImageItem) -> QImage:
    key = id(item.data)
    if key not in _qimages:
        if item.vector:
            import pymupdf
            pix = pymupdf.open("pdf", item.data)[0].get_pixmap(matrix=pymupdf.Matrix(4, 4), alpha=True)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGBA8888).copy()
        else:
            img = QImage.fromData(item.data)
        _qimages[key] = (item.data, img)
    return _qimages[key][1]


def rot_point(p: QPointF, c: QPointF, deg: float) -> QPointF:
    """Rotate ``p`` clockwise (as seen on screen) by ``deg`` about ``c``."""
    if not deg:
        return p
    a = math.radians(deg)
    dx, dy = p.x() - c.x(), p.y() - c.y()
    return QPointF(c.x() + dx * math.cos(a) - dy * math.sin(a), c.y() + dx * math.sin(a) + dy * math.cos(a))


def corners(r: QRectF) -> list[QPointF]:
    """Top-left, top-right, bottom-left, bottom-right."""
    return [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]


class PageView(QWidget):
    """One rendered page with the text objects drawn over it. Mouse and keys go to the editor."""

    def __init__(self, editor: "PdfEditor"):
        super().__init__()
        self.ed = editor
        self.image: QImage | None = None
        self.band: QRectF | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_image(self, img: QImage):
        self.image = img
        self.setFixedSize(img.size())
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self.image:
            p.drawImage(0, 0, self.image)
        z = self.ed.zoom
        for img in self.ed.page_images():
            r = img.rect(z)
            p.save()
            self._turn(p, r, img.angle)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(r, qimage_of(img))
            if img is self.ed.selected:
                self._outline(p, r)
            p.restore()
        for item in self.ed.page_items():
            if item is self.ed.editing:
                continue
            r = item.rect(z)
            if item.cover and not item.ocr:
                cx0, cy0, cx1, cy1 = item.cover
                p.fillRect(QRectF(cx0 * z, cy0 * z, (cx1 - cx0) * z, (cy1 - cy0) * z), Qt.GlobalColor.white)
            p.save()
            self._turn(p, r, item.angle)
            if item.flag:
                p.fillRect(r.adjusted(-2, -1, 2, 1), QColor(255, 214, 10, 110))
            if item.ocr:
                # read from the scan: the picture shows the text itself; the layer is drawn only on request
                if self.ed.show_ocr:
                    p.setFont(item.qfont(z))
                    p.setPen(QColor(37, 99, 235, 170))
                    p.drawText(QPointF(item.x * z, item.y * z), item.text)
                if item is self.ed.selected:
                    self._outline(p, r)
                p.restore()
                continue
            if item.white:
                p.fillRect(r.adjusted(-PAD * z, -PAD * z, PAD * z, PAD * z), Qt.GlobalColor.white)
            p.setFont(item.qfont(z))
            p.setPen(QColor(item.color))
            for i, line in enumerate(item.lines()):
                p.drawText(QPointF(item.x * z, (item.y + i * item.size * item.leading) * z), line)
            if item is self.ed.selected:
                self._outline(p, r)
            p.restore()
        if self.band:
            color = QColor("#f43f5e") if self.ed.mode == "remove" else QColor("#7c5cff")
            p.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
            fill = QColor(color)
            fill.setAlpha(40)
            p.fillRect(self.band, fill)
            p.drawRect(self.band)

    @staticmethod
    def _turn(p: QPainter, r: QRectF, angle: float):
        if angle:
            c = r.center()
            p.translate(c)
            p.rotate(angle)
            p.translate(-c)

    def _outline(self, p: QPainter, r: QRectF):
        """Dashed frame with four resize handles around the selected object."""
        r = r.adjusted(-3, -3, 3, 3)
        p.setPen(QPen(QColor("#7c5cff"), 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        p.setPen(QPen(QColor("#7c5cff"), 1.5))
        p.setBrush(Qt.GlobalColor.white)
        for c in corners(r):
            p.drawRect(QRectF(c.x() - HANDLE, c.y() - HANDLE, 2 * HANDLE, 2 * HANDLE))
        top = QPointF(r.center().x(), r.top())
        knob = QPointF(top.x(), top.y() - ROT_DIST)
        p.drawLine(top, knob)
        p.drawEllipse(knob, HANDLE + 1, HANDLE + 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan = (e.globalPosition(), self.ed.scroll.horizontalScrollBar().value(),
                         self.ed.scroll.verticalScrollBar().value())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.ed.press(e.position(), e.modifiers())

    def mouseMoveEvent(self, e):
        if getattr(self, "_pan", None):
            start, hx, vy = self._pan
            d = e.globalPosition() - start
            self.ed.scroll.horizontalScrollBar().setValue(int(hx - d.x()))
            self.ed.scroll.verticalScrollBar().setValue(int(vy - d.y()))
            return
        self.ed.move(e.position(), bool(e.buttons() & Qt.MouseButton.LeftButton))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton and getattr(self, "_pan", None):
            self._pan = None
            self.ed._mode_changed(self.ed.mode)       # puts the mode's cursor back
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.ed.release(e.position())

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.ed._zoom_at(1.25 if e.angleDelta().y() > 0 else 0.8, e.position())
            e.accept()
        else:
            super().wheelEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.ed.double_click(e.position())

    def focusNextPrevChild(self, nxt: bool) -> bool:
        return False        # Tab and Shift+Tab go to the editor (next doubtful line), not to the next control

    def keyPressEvent(self, e):
        if not self.ed.key(e):
            super().keyPressEvent(e)


class InlineEdit(QPlainTextEdit):
    """Typing right on the page. Ctrl+Enter or a click elsewhere finishes, Esc cancels."""

    finished = Signal(bool)  # True = keep the text

    def __init__(self, parent):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.document().setDocumentMargin(0)
        self._done = False

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._finish(False)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._finish(True)
        else:
            super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self._finish(True)

    def _finish(self, keep: bool):
        if not self._done:
            self._done = True
            self.finished.emit(keep)


class OcrWorker(QThread):
    """Reads scanned pages in the background (the models take a few seconds per page)."""

    done = Signal(object)    # {page number: PageResult}, or an Exception

    def __init__(self, parent, jobs: list[tuple[int, object, float]]):
        super().__init__(parent)
        self.jobs = jobs

    def run(self):
        try:
            from core import ocr
            self.done.emit({n: ocr.process_image(img, dpi) for n, img, dpi in self.jobs})
        except Exception as exc:  # reported to the user by the editor
            self.done.emit(exc)


class PdfEditor(QDialog):
    """Edits a copy of the PDF. ``result`` is the saved copy's path after Save.

    Removed text is cut out of ``self.doc`` at once. Added or picked-up text lives in ``self.items``
    and is written into the PDF only when saving, so it can be moved and changed until then. The
    unwritten state is kept next to the saved copy, so opening the copy again brings the objects back.
    """

    def __init__(self, parent, t, pdf: Path, save_to: Path, title: str, auto_ocr: bool = False):
        super().__init__(parent)
        import pymupdf

        self.fitz = pymupdf
        self.t = t
        self.save_to = save_to
        self.result: Path | None = None
        self.items: list[TextItem] = []
        self.images: list[ImageItem] = []
        self.doc = self._open(Path(pdf))
        self.undo: list[tuple[bytes, list[TextItem], list[ImageItem]]] = []
        self.page_no = 0
        self.zoom = 1.5
        self.changed = False
        self.show_ocr = False
        self._pdf_fonts: dict = {}
        self._ocr_worker: OcrWorker | None = None
        self.selected: TextItem | ImageItem | None = None
        self.editing: TextItem | None = None
        self.inline: InlineEdit | None = None
        self._drag: dict | None = None
        self._band_start: QPointF | None = None
        self.setWindowTitle(t("pdf_title", name=title))
        self.resize(1180, 880)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.mode_seg = Segmented([("edit", t("pdf_edit")), ("add", t("pdf_add")),
                                   ("replace", t("pdf_replace")), ("remove", t("pdf_remove"))])
        self.mode_seg.set_value("edit")
        self.mode_seg.changed.connect(self._mode_changed)
        self.mode_seg.setMinimumWidth(460)
        tools.addWidget(self.mode_seg)
        tools.addSpacing(10)
        self.font_combo = QComboBox()
        for name, files in FONTS.items():
            if (FONTS_DIR / files[0]).exists():
                self.font_combo.addItem(name)
        self.font_combo.currentTextChanged.connect(lambda v: self._style_changed(font=v))
        tools.addWidget(self.font_combo)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(4, 200)
        self.size_spin.setValue(12)
        self.size_spin.setSuffix(" pt")
        self.size_spin.valueChanged.connect(lambda v: self._style_changed(size=float(v)))
        tools.addWidget(self.size_spin)
        self.bold_btn = self._toggle("B", t("pdf_bold"), lambda v: self._style_changed(bold=v))
        f = self.bold_btn.font()
        f.setBold(True)
        self.bold_btn.setFont(f)
        self.italic_btn = self._toggle("I", t("pdf_italic"), lambda v: self._style_changed(italic=v))
        f = self.italic_btn.font()
        f.setItalic(True)
        self.italic_btn.setFont(f)
        tools.addWidget(self.bold_btn)
        tools.addWidget(self.italic_btn)
        self.color = QColor("#000000")
        self.color_btn = QPushButton()
        self.color_btn.setFixedWidth(40)
        self.color_btn.setToolTip(t("pdf_color"))
        self.color_btn.clicked.connect(self._pick_color)
        self._paint_color_btn()
        tools.addWidget(self.color_btn)
        self.bg_check = QCheckBox(t("pdf_bg"))
        self.bg_check.setToolTip(t("pdf_bg_tip"))
        self.bg_check.toggled.connect(lambda v: self._style_changed(white=v))
        tools.addWidget(self.bg_check)
        self.white_check = QCheckBox(t("pdf_white"))
        self.white_check.setToolTip(t("pdf_white_tip"))
        tools.addWidget(self.white_check)
        tools2 = QHBoxLayout()
        tools2.setSpacing(8)
        self.image_btn = QPushButton(t("pdf_add_image"))
        self.image_btn.setToolTip(t("pdf_add_image_tip"))
        self.image_btn.clicked.connect(self._add_image)
        tools2.addWidget(self.image_btn)
        self.delete_btn = QPushButton(t("pdf_delete_item"))
        self.delete_btn.setToolTip(t("pdf_delete_item_tip"))
        self.delete_btn.clicked.connect(self._delete_selected)
        tools2.addWidget(self.delete_btn)
        self.undo_btn = QPushButton(t("pdf_undo"))
        self.undo_btn.clicked.connect(self._undo)
        tools2.addWidget(self.undo_btn)
        tools2.addSpacing(14)
        self.ocr_btn = QPushButton(t("pdf_ocr"))
        self.ocr_btn.setToolTip(t("pdf_ocr_tip"))
        menu = QMenu(self.ocr_btn)
        menu.addAction(t("pdf_ocr_page"), lambda: self._ocr([self.page_no]))
        menu.addAction(t("pdf_ocr_all"), lambda: self._ocr(list(range(self.doc.page_count))))
        self.ocr_btn.setMenu(menu)
        tools2.addWidget(self.ocr_btn)
        self.ocr_show = QCheckBox(t("pdf_ocr_show"))
        self.ocr_show.setToolTip(t("pdf_ocr_show_tip"))
        self.ocr_show.toggled.connect(self._toggle_ocr_layer)
        tools2.addWidget(self.ocr_show)
        tools2.addSpacing(14)
        self.doubt_btn = QPushButton()
        self.doubt_btn.setToolTip(t("pdf_doubt_tip"))
        self.doubt_btn.clicked.connect(lambda: self._goto_doubt(1))
        tools2.addWidget(self.doubt_btn)
        self.ok_btn = QPushButton(t("pdf_doubt_ok"))
        self.ok_btn.setToolTip(t("pdf_doubt_ok_tip"))
        self.ok_btn.clicked.connect(self._accept_doubt)
        tools2.addWidget(self.ok_btn)
        tools2.addStretch(1)
        v.addLayout(tools)
        v.addLayout(tools2)

        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        self.view = PageView(self)
        holder = QWidget()
        holder.setObjectName("sidebarInner")  # transparent: the page sits on the dialog background
        hl = QHBoxLayout(holder)
        hl.addStretch(1)
        hl.addWidget(self.view)
        hl.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(holder)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        v.addWidget(self.scroll, 1)

        bottom = QHBoxLayout()
        self.prev_btn = icon_button("prev")
        self.prev_btn.clicked.connect(lambda: self._go(self.page_no - 1))
        self.next_btn = icon_button("next")
        self.next_btn.clicked.connect(lambda: self._go(self.page_no + 1))
        self.page_label = QLabel()
        bottom.addWidget(self.prev_btn)
        bottom.addWidget(self.page_label)
        bottom.addWidget(self.next_btn)
        zoom_out = QPushButton("−")
        zoom_out.setFixedWidth(34)
        zoom_out.clicked.connect(lambda: self._set_zoom(self.zoom / 1.25))
        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(34)
        zoom_in.clicked.connect(lambda: self._set_zoom(self.zoom * 1.25))
        bottom.addSpacing(12)
        bottom.addWidget(zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom.addWidget(self.zoom_label)
        bottom.addWidget(zoom_in)
        fitw = QPushButton(self.t("pdf_fitw"))
        fitw.setToolTip(self.t("pdf_zoom_tip"))
        fitw.clicked.connect(self._fit_width)
        bottom.addWidget(fitw)
        self.full_btn = QPushButton(self.t("pdf_full"))
        self.full_btn.setToolTip(self.t("pdf_full_tip"))
        self.full_btn.clicked.connect(self._toggle_full)
        bottom.addWidget(self.full_btn)
        bottom.addStretch(1)
        export = QPushButton(t("pdf_export"))
        export.setToolTip(t("pdf_export_tip"))
        menu_x = QMenu(export)
        menu_x.addAction(t("pdf_export_to_word"), lambda: self._export_text(".docx"))
        menu_x.addAction(t("pdf_export_to_excel"), lambda: self._export_text(".xlsx"))
        menu_x.addAction(t("pdf_export_to_txt"), lambda: self._export_text(".txt"))
        export.setMenu(menu_x)
        bottom.addWidget(export)
        save_as = QPushButton(t("pdf_save_as"))
        save_as.clicked.connect(self._save_as)
        bottom.addWidget(save_as)
        cancel = QPushButton(t("cancel"))
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        save = QPushButton(t("pdf_save"))
        save.setObjectName("primary")
        save.setToolTip(t("pdf_save_tip"))
        save.clicked.connect(self._save)
        bottom.addWidget(save)
        v.addLayout(bottom)

        self._mode_changed("edit")
        self._render()
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self._toggle_full)
        self._update_doubts()
        if auto_ocr:
            self.showMaximized()           # a scan is read and checked on a big screen from the start
            QTimer.singleShot(0, lambda: self._ocr(list(range(self.doc.page_count))))

    def _toggle(self, text: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setFixedWidth(32)
        b.toggled.connect(slot)
        return b

    # ------------------------------------------------------------------ open / state
    def _open(self, pdf: Path):
        """Open ``pdf``; if it is a copy saved by this editor, reopen its base and unwritten text instead."""
        side = pdf.with_name(pdf.name + SIDECAR)
        if side.exists():
            try:
                data = json.loads(side.read_text(encoding="utf-8"))
                base = pdf.with_name(data["base"])
                doc = self.fitz.open(base)
                self.items = [TextItem(**d) for d in data["items"]]
                self.images = [ImageItem(**{**d, "data": base64.b64decode(d["data"])})
                               for d in data.get("images", [])]
                return doc
            except Exception:
                self.items = []
                self.images = []
        return self.fitz.open(pdf)

    @property
    def page(self):
        return self.doc[self.page_no]

    @property
    def mode(self) -> str:
        return self.mode_seg.value()

    def page_items(self) -> list[TextItem]:
        return [i for i in self.items if i.page == self.page_no]

    def page_images(self) -> list[ImageItem]:
        return [i for i in self.images if i.page == self.page_no]

    def _snapshot(self):
        return self.doc.tobytes(), copy.deepcopy(self.items), copy.deepcopy(self.images)

    def _remember(self):
        self.undo.append(self._snapshot())
        del self.undo[:-UNDO_LIMIT]
        self.changed = True
        self.undo_btn.setEnabled(True)

    def _undo(self):
        self._close_inline(False)
        if not self.undo:
            return
        data, items, images = self.undo.pop()
        self.doc.close()
        self.doc = self.fitz.open("pdf", data)
        self.items = items
        self.images = images
        self.selected = None
        self.page_no = min(self.page_no, self.doc.page_count - 1)
        self.changed = bool(self.undo)
        self._render()

    # ------------------------------------------------------------------ view
    def _render(self):
        pix = self.page.get_pixmap(matrix=self.fitz.Matrix(self.zoom, self.zoom), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        self.view.set_image(img)
        n = self.doc.page_count
        self.page_label.setText(self.t("pdf_page", n=self.page_no + 1, total=n))
        self.prev_btn.setEnabled(self.page_no > 0)
        self.next_btn.setEnabled(self.page_no < n - 1)
        self.undo_btn.setEnabled(bool(self.undo))
        self.delete_btn.setEnabled(self.selected is not None)
        self._update_doubts()

    def _go(self, n: int):
        if 0 <= n < self.doc.page_count:
            self._close_inline(True)
            self.page_no = n
            self._select(None)
            self._render()

    def _set_zoom(self, z: float):
        self._close_inline(True)
        self.zoom = max(0.25, min(8.0, z))
        self._render()
        self.zoom_label.setText(f"{round(self.zoom / 1.5 * 100)}%")

    def _zoom_at(self, factor: float, pos: QPointF):
        """Zoom with the point under the pointer staying under it."""
        old = self.zoom
        self._set_zoom(old * factor)
        s = self.zoom / old
        if s == 1.0:
            return
        hb, vb = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        dx, dy = pos.x() * (s - 1), pos.y() * (s - 1)
        QTimer.singleShot(0, lambda: (hb.setValue(int(hb.value() + dx)), vb.setValue(int(vb.value() + dy))))

    def _fit_width(self):
        w = self.scroll.viewport().width() - 40
        pw = self.page.rect.width if not self.page.rotation % 180 else self.page.rect.height
        if w > 50 and pw > 0:
            self._set_zoom(w / pw)

    def _toggle_full(self):
        self._close_inline(True)
        if self.isFullScreen():
            if self._before_full & Qt.WindowState.WindowMaximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.full_btn.setText(self.t("pdf_full"))
        else:
            self._before_full = self.windowState() & ~Qt.WindowState.WindowFullScreen
            self.showFullScreen()
            self.full_btn.setText(self.t("pdf_full_exit"))
        QTimer.singleShot(150, self._fit_width)

    def _mode_changed(self, mode: str):
        self._close_inline(True)
        self.white_check.setVisible(mode in ("remove", "replace", "edit"))
        self.hint.setText(self.t(f"pdf_hint_{mode}"))
        self.hint.setStyleSheet("")
        self.view.setCursor(Qt.CursorShape.IBeamCursor if mode == "add" else
                            Qt.CursorShape.ArrowCursor if mode == "edit" else Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------ style controls
    def _pick_color(self):
        c = QColorDialog.getColor(self.color, self, self.t("pdf_color"))
        if c.isValid():
            self.color = c
            self._paint_color_btn()
            self._style_changed(color=c.name())

    def _paint_color_btn(self):
        self.color_btn.setStyleSheet(f"background: {self.color.name()}; border-radius: 8px;")

    def _style_changed(self, **kw):
        """A toolbar change applies to the selected text object (and to text added next)."""
        item = self.selected
        if not isinstance(item, TextItem) or getattr(self, "_syncing", False):
            return
        if all(getattr(item, k) == v for k, v in kw.items()):
            return
        self._remember()
        self._touch(item)
        for k, v in kw.items():
            setattr(item, k, v)
        if self.inline and self.editing is item:
            self._style_inline()
        self.view.update()

    def _sync_toolbar(self, item: TextItem):
        self._syncing = True
        try:
            i = self.font_combo.findText(item.font)
            if i >= 0:
                self.font_combo.setCurrentIndex(i)
            self.size_spin.setValue(int(round(item.size)))
            self.bold_btn.setChecked(item.bold)
            self.italic_btn.setChecked(item.italic)
            self.bg_check.setChecked(item.white)
            self.color = QColor(item.color)
            self._paint_color_btn()
        finally:
            self._syncing = False

    def _new_item_style(self) -> dict:
        return dict(font=self.font_combo.currentText() or "Arial", size=float(self.size_spin.value()),
                    color=self.color.name(), bold=self.bold_btn.isChecked(),
                    italic=self.italic_btn.isChecked(), white=self.bg_check.isChecked())

    # ------------------------------------------------------------------ coordinates
    def _to_pdf_rect(self, r: QRectF):
        """View pixels -> unrotated PDF coordinates (what PyMuPDF edits in)."""
        rect = self.fitz.Rect(r.left(), r.top(), r.right(), r.bottom()) / self.zoom
        return rect * self.page.derotation_matrix

    def _to_pdf_point(self, p: QPointF):
        return self.fitz.Point(p.x(), p.y()) / self.zoom * self.page.derotation_matrix

    def _to_view_pt(self, pt) -> tuple[float, float]:
        """Unrotated PDF point -> point of the page as shown (in points, not pixels)."""
        q = self.fitz.Point(pt) * self.page.rotation_matrix
        return q.x, q.y

    # ------------------------------------------------------------------ mouse
    def _item_at(self, pos: QPointF) -> TextItem | ImageItem | None:
        for item in list(reversed(self.page_items())) + list(reversed(self.page_images())):
            if item.rect(self.zoom).adjusted(-4, -4, 4, 4).contains(self._unrot(item, pos)):
                return item
        return None

    def _unrot(self, item, pos: QPointF, center: QPointF | None = None) -> QPointF:
        """``pos`` in the frame of the item before its rotation."""
        if not item.angle:
            return pos
        return rot_point(pos, center or item.rect(self.zoom).center(), -item.angle)

    def _handle_at(self, pos: QPointF) -> int | None:
        """Index of the resize handle of the selected object under ``pos``."""
        if self.selected is None or self.mode not in ("edit", "add"):
            return None
        r = self.selected.rect(self.zoom).adjusted(-3, -3, 3, 3)
        pos = self._unrot(self.selected, pos)
        knob = QPointF(r.center().x(), r.top() - ROT_DIST)
        if abs(knob.x() - pos.x()) <= HANDLE + 3 and abs(knob.y() - pos.y()) <= HANDLE + 3:
            return 4
        for i, c in enumerate(corners(r)):
            if abs(c.x() - pos.x()) <= HANDLE + 2 and abs(c.y() - pos.y()) <= HANDLE + 2:
                return i
        return None

    @staticmethod
    def _handle_cursor(i: int):
        if i == 4:
            return Qt.CursorShape.PointingHandCursor
        return Qt.CursorShape.SizeFDiagCursor if i in (0, 3) else Qt.CursorShape.SizeBDiagCursor

    def _select(self, item: TextItem | ImageItem | None):
        self.selected = item
        if isinstance(item, TextItem):
            self._sync_toolbar(item)
            if item.flag and item.note:
                self.hint.setText(self.t("pdf_ocr_doubt", why=item.note))
                self.hint.setStyleSheet("color: #f5c542; font-weight: 600;")
            else:
                self.hint.setStyleSheet("")
            self._update_doubts()
        self.delete_btn.setEnabled(item is not None)
        self.view.update()

    def press(self, pos: QPointF, mods):
        self._close_inline(True)
        mode = self.mode
        h = self._handle_at(pos)
        if h is not None:
            item = self.selected
            cs = corners(item.rect(self.zoom))
            if h == 4:
                self._drag = {"item": item, "start": pos, "moved": False, "snapshot": self._snapshot(),
                              "rotate": True, "center": item.rect(self.zoom).center(), "x": item.x, "y": item.y}
                self.view.setCursor(self._handle_cursor(h))
                return
            self._drag = {"item": item, "start": pos, "moved": False, "snapshot": self._snapshot(),
                          "resize": True, "anchor": cs[3 - h], "corner": cs[h], "center": cs[0] * 0.5 + cs[3] * 0.5,
                          "x": item.x, "y": item.y, "size": getattr(item, "size", 0.0),
                          "w": getattr(item, "w", 0.0), "h": getattr(item, "h", 0.0)}
            self.view.setCursor(self._handle_cursor(h))
            return
        item = self._item_at(pos)
        if item is None and mode == "edit":
            item = self._pick_up(pos, whole_block=bool(mods & Qt.KeyboardModifier.ShiftModifier))
            if item is None:
                item = self._pick_image(pos)
        if item is not None and mode in ("edit", "add"):
            self._select(item)
            self._drag = {"item": item, "start": pos, "x": item.x, "y": item.y, "moved": False,
                          "snapshot": self._snapshot()}
            self.view.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        self._select(None)
        if mode == "add":
            pt = pos / self.zoom
            style = self._new_item_style()
            new = TextItem(self.page_no, pt.x(), pt.y() + style["size"] * 0.8, **style)  # click marks the top
            self._remember()
            self.items.append(new)
            self._select(new)
            self._open_inline(new, new_item=True)
        elif mode in ("remove", "replace"):
            self._band_start = pos

    def move(self, pos: QPointF, pressed: bool):
        if self._drag and pressed:
            d = self._drag
            delta = (pos - d["start"]) / self.zoom
            if not d["moved"] and (abs(delta.x()) + abs(delta.y())) * self.zoom < 3:
                return
            if not d["moved"]:
                d["moved"] = True
                self.undo.append(d["snapshot"])
                del self.undo[:-UNDO_LIMIT]
                self.changed = True
                self._touch(d["item"])
            if d.get("rotate"):
                c = d["center"]
                ang = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x())) + 90.0
                if self._shift:
                    ang = round(ang / 15.0) * 15.0
                ang = (ang + 180.0) % 360.0 - 180.0
                d["item"].angle = round(ang, 1)
            elif d.get("resize"):
                self._resize(d, self._unrot(d["item"], pos, d["center"]), bool(self._shift))
            else:
                d["item"].x = d["x"] + delta.x()
                d["item"].y = d["y"] + delta.y()
            self.view.update()
        elif self._band_start is not None and pressed:
            self.view.band = QRectF(self._band_start, pos).normalized()
            self.view.update()
        elif self.mode in ("edit", "add") and not pressed:
            h = self._handle_at(pos)
            if h is not None:
                self.view.setCursor(self._handle_cursor(h))
            elif self._item_at(pos):
                self.view.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.view.setCursor(Qt.CursorShape.ArrowCursor if self.mode == "edit" else Qt.CursorShape.IBeamCursor)

    @property
    def _shift(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier

    def _resize(self, d: dict, pos: QPointF, free: bool):
        """Scale the dragged object about the opposite corner; Shift stretches a picture freely."""
        z = self.zoom
        item, anchor, corner = d["item"], d["anchor"], d["corner"]
        diag = corner - anchor
        len2 = diag.x() ** 2 + diag.y() ** 2
        if len2 < 1:
            return
        s = max(0.05, ((pos.x() - anchor.x()) * diag.x() + (pos.y() - anchor.y()) * diag.y()) / len2)
        ax, ay = anchor.x() / z, anchor.y() / z
        if isinstance(item, ImageItem):
            if free:
                r = QRectF(anchor, pos).normalized()
                item.x, item.y = r.x() / z, r.y() / z
                item.w, item.h = max(MIN_IMAGE, r.width() / z), max(MIN_IMAGE, r.height() / z)
            else:
                s = max(s, MIN_IMAGE / max(1e-6, min(d["w"], d["h"])))
                item.w, item.h = d["w"] * s, d["h"] * s
                item.x, item.y = ax + (d["x"] - ax) * s, ay + (d["y"] - ay) * s
            self._keep_anchor(d)
            return
        size = max(4.0, min(400.0, d["size"] * s))
        s = size / d["size"]
        item.size = round(size, 1)
        item.x, item.y = ax + (d["x"] - ax) * s, ay + (d["y"] - ay) * s
        self._keep_anchor(d)
        self._syncing = True
        try:
            self.size_spin.setValue(int(round(item.size)))
        finally:
            self._syncing = False

    def _keep_anchor(self, d: dict):
        """After resizing a rotated object, put the fixed corner back where it was on screen."""
        item = d["item"]
        if not item.angle:
            return
        z = self.zoom
        before = rot_point(d["anchor"], d["center"], item.angle)
        after = rot_point(d["anchor"], item.rect(z).center(), item.angle)
        item.x += (before.x() - after.x()) / z
        item.y += (before.y() - after.y()) / z

    def release(self, pos: QPointF):
        if self._drag:
            self._drag = None
            self.view.setCursor(Qt.CursorShape.SizeAllCursor)
            self.undo_btn.setEnabled(bool(self.undo))
            return
        if self._band_start is not None:
            r = QRectF(self._band_start, pos).normalized()
            self._band_start = None
            self.view.band = None
            self.view.update()
            if r.width() > 3 and r.height() > 3:
                self._rect_drawn(r)

    def double_click(self, pos: QPointF):
        item = self._item_at(pos)
        if isinstance(item, ImageItem) and item.text_src and self.mode in ("edit", "add"):
            item = self._to_text(item)
        if isinstance(item, TextItem) and self.mode in ("edit", "add"):
            self._select(item)
            self._open_inline(item)

    def key(self, e) -> bool:
        item = self.selected
        k = e.key()
        if e.matches(QKeySequence.StandardKey.Undo):
            self._undo()
            return True
        if e.matches(QKeySequence.StandardKey.Paste) and self._paste_image():
            return True
        if k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and self._doubts():
            self._goto_doubt(-1 if k == Qt.Key.Key_Backtab or e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
            return True
        if item is None:
            return False
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2):
            if isinstance(item, ImageItem) and item.text_src:
                item = self._to_text(item)
            if isinstance(item, TextItem):
                self._open_inline(item)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 10.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
            dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(k, 0.0)
            dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(k, 0.0)
            self._remember()
            self._touch(item)
            item.x += dx
            item.y += dy
            self.view.update()
        elif k == Qt.Key.Key_Escape:
            self._select(None)
        else:
            return False
        return True

    @staticmethod
    def _touch(item):
        """A text read from a scan turns into ordinary visible text once it is changed or moved."""
        if isinstance(item, TextItem) and item.ocr:
            item.ocr = False
            item.flag = False
            item.note = ""

    def _delete_selected(self):
        sel = self.selected
        for lst in (self.items, self.images):
            if sel is not None and any(sel is i for i in lst):
                self._remember()
                lst[:] = [i for i in lst if i is not sel]
                self._select(None)
                self._render()
                return

    def _to_text(self, img: ImageItem) -> TextItem:
        """Picked-up page text becomes an editable text object (with the closest font we have)."""
        src = json.loads(img.text_src)
        ox, oy, ow = src.pop("ox"), src.pop("oy"), src.pop("ow")
        s = img.w / ow if ow else 1.0
        item = TextItem(**src)
        item.x = img.x + (item.x - ox) * s
        item.y = img.y + (item.y - oy) * s
        item.size = round(max(4.0, item.size * s), 1)
        item.angle = img.angle
        self._remember()
        self.images = [i for i in self.images if i is not img]
        self.items.append(item)
        self._select(item)
        self.view.update()
        return item

    # ------------------------------------------------------------------ scans
    def _doubts(self) -> list:
        return sorted((i for i in self.items if i.flag and i.ocr), key=lambda i: (i.page, i.y, i.x))

    def _update_doubts(self):
        n = len(self._doubts())
        self.doubt_btn.setText(self.t("pdf_doubt", n=n))
        self.doubt_btn.setVisible(n > 0)
        sel = self.selected
        self.ok_btn.setVisible(isinstance(sel, TextItem) and sel.flag and sel.ocr)

    def _goto_doubt(self, step: int):
        """Select the next (or previous) doubtful line, bring it into view."""
        items = self._doubts()
        if not items:
            return
        cur = self.selected if self.selected in items else None
        i = (items.index(cur) + step) % len(items) if cur is not None else (0 if step > 0 else len(items) - 1)
        item = items[i]
        self._close_inline(True)
        if item.page != self.page_no:
            self._go(item.page)
        self._select(item)
        r = item.rect(self.zoom)
        self.scroll.ensureVisible(int(r.center().x()), int(r.center().y()), 60, 140)
        self.view.setFocus()

    def _accept_doubt(self):
        """The line is right as it is: the yellow mark goes and the next doubtful line is shown."""
        item = self.selected
        if not (isinstance(item, TextItem) and item.flag):
            return
        self._remember()
        item.flag, item.note = False, ""
        rest = self._doubts()
        self.hint.setText(self.t("pdf_hint_edit"))
        self.hint.setStyleSheet("")
        if rest:
            self._goto_doubt(1)
        else:
            self._update_doubts()
        self.view.update()

    def _fit_page(self):
        """Whole page in the window, as large as it goes."""
        w = self.scroll.viewport().width() - 40
        h = self.scroll.viewport().height() - 20
        pr = self.page.rect
        pw, ph = (pr.width, pr.height) if not self.page.rotation % 180 else (pr.height, pr.width)
        if w > 50 and h > 50 and pw > 0:
            self._set_zoom(min(w / pw, h / ph))

    def _toggle_ocr_layer(self, on: bool):
        self.show_ocr = on
        self.view.update()

    def _is_scan(self, n: int) -> bool:
        """A page whose content is a picture and that has little or no text of its own."""
        page = self.doc[n]
        return len(page.get_text().strip()) < 30 and bool(page.get_images())

    def _ocr(self, pages: list[int]):
        """Recognise scanned pages: the picture is straightened and cleaned, the lines become text objects."""
        if self._ocr_worker is not None:
            return
        self._close_inline(True)
        try:
            from core import ocr
        except Exception as exc:
            QMessageBox.warning(self, self.t("pdf_ocr"), self.t("pdf_ocr_fail", err=str(exc)))
            return
        jobs, skipped = [], 0
        for n in pages:
            if not self._is_scan(n):
                skipped += 1
                continue
            img, dpi = ocr.page_to_image(self.doc[n])
            jobs.append((n, img, dpi))
        if not jobs:
            QMessageBox.information(self, self.t("pdf_ocr"), self.t("pdf_ocr_notscan"))
            return
        self._ocr_skipped = skipped
        self.ocr_btn.setEnabled(False)
        self.ocr_btn.setText(self.t("pdf_ocr_busy"))
        self._ocr_worker = OcrWorker(self, jobs)
        self._ocr_worker.done.connect(self._ocr_done)
        self._ocr_worker.start()

    def _ocr_done(self, res):
        self._ocr_worker = None
        self.ocr_btn.setEnabled(True)
        self.ocr_btn.setText(self.t("pdf_ocr"))
        if isinstance(res, Exception):
            QMessageBox.warning(self, self.t("pdf_ocr"), self.t("pdf_ocr_fail", err=str(res)))
            return
        self._remember()
        lines = 0
        for n, r in sorted(res.items()):
            lines += self._apply_ocr(n, r)
        self.selected = None
        self.page_no = min(self.page_no, self.doc.page_count - 1)
        self._render()
        msg = self.t("pdf_ocr_done", n=lines, pages=len(res))
        if self._ocr_skipped:
            msg += " " + self.t("pdf_ocr_skipped", n=self._ocr_skipped)
        self.hint.setText(msg)
        QTimer.singleShot(50, self._fit_width)
        self._update_doubts()
        if self._doubts():
            self._goto_doubt(1)

    def _apply_ocr(self, n: int, r) -> int:
        """Put the cleaned picture in the page's place and the recognised lines on it as text objects."""
        new = self.doc.new_page(pno=n, width=r.width, height=r.height)
        new.insert_image(new.rect, stream=r.jpeg)
        self.doc.delete_page(n + 1)
        self.items = [i for i in self.items if not (i.page == n and i.ocr)]
        from core.requisites import check_line
        for ln in r.lines:
            x0, y0, x1, y1 = ln["box"]
            pad = max(1.0, 0.18 * ln["size"])
            why = check_line(ln["text"], ln["conf"])
            self.items.append(TextItem(
                flag=bool(why), note="; ".join(why),
                page=n, x=ln["x"], y=ln["y"], text=ln["text"], font=ln["font"], size=round(ln["size"], 2),
                color=ln["color"], bold=ln["bold"], italic=ln["italic"], ocr=True,
                cover=[x0 - pad, y0 - pad, x1 + pad, y1 + pad]))
        return len(r.lines)

    # ------------------------------------------------------------------ pictures
    def _add_image(self):
        self._close_inline(True)
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("pdf_add_image"), "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, self.t("pdf_add_image"), path)
            return
        self._place_image(img)

    def _paste_image(self) -> bool:
        img = QApplication.clipboard().image()
        if img.isNull():
            return False
        self._place_image(img)
        return True

    def _place_image(self, img: QImage):
        try:
            # Re-encode as PNG so every format works and transparency stays.
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, "PNG")
            data = bytes(buf.data())
        except Exception as exc:
            QMessageBox.warning(self, self.t("pdf_add_image"), str(exc))
            return
        pw, ph = self.view.width() / self.zoom, self.view.height() / self.zoom
        w = min(img.width() * 0.75, pw * 0.5)  # at most half the page width
        h = w * img.height() / img.width()
        if h > ph * 0.5:
            h = ph * 0.5
            w = h * img.width() / img.height()
        item = ImageItem(self.page_no, (pw - w) / 2, (ph - h) / 2, w, h, data)
        self._remember()
        self.images.append(item)
        self.mode_seg.set_value("edit")
        self._select(item)
        self.view.update()

    def _pick_image(self, pos: QPointF) -> ImageItem | None:
        """Turn the picture of the page under the cursor into a movable, resizable object."""
        pt = self._to_pdf_point(pos)
        page = self.page
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            return None
        page_area = max(1.0, page.rect.width * page.rect.height)
        for info in reversed(infos):
            xref = info.get("xref", 0)
            r = self.fitz.Rect(info["bbox"])
            if not xref or not r.contains(pt) or r.width * r.height > 0.85 * page_area:
                continue  # whole-page scans stay part of the page
            try:
                pix = self.fitz.Pixmap(self.doc, xref)
                smask = self.doc.extract_image(xref).get("smask", 0)
                if pix.n - pix.alpha >= 4:
                    pix = self.fitz.Pixmap(self.fitz.csRGB, pix)
                if smask:
                    pix = self.fitz.Pixmap(pix, self.fitz.Pixmap(self.doc, smask))
                data = pix.tobytes("png")
            except Exception:
                continue
            vr = (r * page.rotation_matrix).normalize()
            self._remember()
            try:
                page.delete_image(xref)
            except Exception:
                self.undo.pop()
                return None
            item = ImageItem(self.page_no, vr.x0, vr.y0, vr.width, vr.height, data)
            self.images.append(item)
            self._render()
            return item
        return None

    # ------------------------------------------------------------------ inline typing
    def _open_inline(self, item: TextItem, new_item: bool = False):
        self._close_inline(True)
        self.editing = item
        self._inline_new = new_item
        self._inline_before = item.text
        ed = InlineEdit(self.view)
        self.inline = ed
        ed.setPlainText(item.text)
        self._style_inline()
        ed.textChanged.connect(self._fit_inline)
        ed.finished.connect(self._inline_finished)
        ed.show()
        ed.setFocus()
        ed.moveCursor(ed.textCursor().MoveOperation.End)
        self.view.update()

    def _style_inline(self):
        item, ed = self.editing, self.inline
        f = item.qfont(self.zoom)
        ed.setFont(f)
        solid = item.white or item.ocr or bool(item.cover)   # over a scan the old line must not show through
        ed.setStyleSheet(
            f"QPlainTextEdit {{ background: rgba(255,255,255,{255 if solid else 200}); color: {item.color};"
            f" font-family: \"{f.family()}\"; font-size: {f.pixelSize()}px; font-weight: {700 if item.bold else 400};"
            f" font-style: {'italic' if item.italic else 'normal'};"
            " border: 1.5px solid #7c5cff; border-radius: 0; padding: 0; }")
        self._fit_inline()

    def _fit_inline(self):
        item, ed = self.editing, self.inline
        if not ed:
            return
        fm = QFontMetricsF(ed.font())
        lines = ed.toPlainText().split("\n")
        w = max(fm.horizontalAdvance(s) for s in lines) + fm.horizontalAdvance("MM")
        h = fm.lineSpacing() * len(lines) + 6
        top = item.y * self.zoom - fm.ascent()
        ed.setGeometry(int(item.x * self.zoom) - 2, int(top) - 2, int(max(w, 60)) + 4, int(h) + 4)

    def _inline_finished(self, keep: bool):
        item, ed = self.editing, self.inline
        if not ed:
            return
        text = ed.toPlainText().rstrip("\n")
        self.inline = None
        self.editing = None
        ed.hide()
        ed.deleteLater()
        if keep and text.strip():
            if text != self._inline_before:
                if not self._inline_new:
                    self._remember()
                self._touch(item)
                item.text = text
        elif self._inline_new or keep:
            # new text left empty, or all text erased: the object goes away
            if item in self.items:
                if not self._inline_new:
                    self._remember()
                self.items.remove(item)
                self._select(None)
        if self._inline_new and item not in self.items and self.undo:
            self.undo.pop()  # nothing was added, so the "before adding" step is not needed
            self.changed = bool(self.undo)
        self._render()
        self.view.setFocus()

    def _close_inline(self, keep: bool):
        if self.inline:
            self.inline._finish(keep)

    # ------------------------------------------------------------------ existing PDF text
    def _spans_in(self, rect) -> list[list[dict]]:
        """Lines (as lists of spans) inside ``rect`` in unrotated coordinates."""
        try:
            data = self.page.get_text("dict", clip=rect)
        except Exception:
            return []
        out = []
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s.get("text", "")]
                if any(s["text"].strip() for s in spans):
                    out.append(spans)
        return out

    def _item_from_lines(self, lines: list[list[dict]]) -> TextItem | None:
        """A text object with the look of the first span, placed exactly over the original lines."""
        if not lines:
            return None
        first = next(s for s in lines[0] if s["text"].strip())
        c = first.get("color", 0)
        flags = first.get("flags", 0)
        fname = first.get("font", "")
        x, y = self._to_view_pt(lines[0][0]["origin"])
        leading = LEADING
        if len(lines) > 1:
            _, y2 = self._to_view_pt(lines[-1][0]["origin"])
            leading = max(0.8, (y2 - y) / (len(lines) - 1) / max(first["size"], 1))
        return TextItem(
            page=self.page_no, x=x, y=y,
            text="\n".join("".join(s["text"] for s in spans).rstrip() for spans in lines),
            font=guess_font(fname), size=round(first["size"], 1),
            color="#%06x" % (c & 0xFFFFFF),
            bold=bool(flags & 16) or "bold" in fname.lower(),
            italic=bool(flags & 2) or "italic" in fname.lower() or "oblique" in fname.lower(),
            white=self.white_check.isChecked(), leading=round(leading, 3),
        )

    def _snippet(self, lines, item: TextItem) -> ImageItem | None:
        """The lines as they are on the page (own font, vector), without pictures and lines behind them."""
        try:
            clip = self.fitz.Rect()
            for spans in lines:
                for sp in spans:
                    clip |= self.fitz.Rect(sp["bbox"])
            clip = clip + (-1, -1, 1, 1)
            tmp = self.fitz.open("pdf", self.doc.tobytes())
            tp = tmp[self.page_no]
            tp.add_redact_annot(tp.rect, fill=False)
            tp.apply_redactions(images=self.fitz.PDF_REDACT_IMAGE_REMOVE,
                                graphics=self.fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                text=self.fitz.PDF_REDACT_TEXT_NONE)
            mini = self.fitz.open()
            mp = mini.new_page(width=clip.width, height=clip.height)
            mp.show_pdf_page(mp.rect, tmp, self.page_no, clip=clip)
            data = mini.tobytes()
            vr = (clip * self.page.rotation_matrix).normalize()
        except Exception:
            return None
        src = asdict(item)
        src.update(ox=vr.x0, oy=vr.y0, ow=vr.width)
        return ImageItem(self.page_no, vr.x0, vr.y0, vr.width, vr.height, data, vector=True,
                         text_src=json.dumps(src, ensure_ascii=False))

    def _line_boxes(self, lines) -> list:
        boxes = []
        for spans in lines:
            r = self.fitz.Rect()
            for s in spans:
                r |= self.fitz.Rect(s["bbox"])
            # A little thinner than the line, so letters of the lines above and below are not cut.
            inset = r.height * 0.15
            boxes.append(self.fitz.Rect(r.x0, r.y0 + inset, r.x1, r.y1 - inset))
        return boxes

    def _cut(self, boxes):
        white = self.white_check.isChecked()
        for r in boxes:
            self.page.add_redact_annot(r, fill=(1, 1, 1) if white else False)
        # Only text goes; pictures and lines under it stay (unless painting white was asked for).
        self.page.apply_redactions(images=self.fitz.PDF_REDACT_IMAGE_NONE,
                                   graphics=self.fitz.PDF_REDACT_LINE_ART_NONE)

    def _pick_up(self, pos: QPointF, whole_block: bool) -> TextItem | None:
        """Turn the PDF line (or paragraph with Shift) under the cursor into a movable text object."""
        pt = self._to_pdf_point(pos)
        try:
            data = self.page.get_text("dict")
        except Exception:
            return None
        for block in data.get("blocks", []):
            lines = [[s for s in ln.get("spans", []) if s.get("text", "")] for ln in block.get("lines", [])]
            lines = [ln for ln in lines if any(s["text"].strip() for s in ln)]
            for ln in lines:
                r = self.fitz.Rect()
                for s in ln:
                    r |= self.fitz.Rect(s["bbox"])
                if r.contains(pt):
                    chosen = lines if whole_block else [ln]
                    item = self._item_from_lines(chosen)
                    if item is None:
                        return None
                    snippet = self._snippet(chosen, item)
                    self._remember()
                    self._cut(self._line_boxes(chosen))
                    if snippet is not None:
                        self.images.append(snippet)
                        item = snippet
                    else:
                        self.items.append(item)
                    self._render()
                    return item
        return None

    def _rect_drawn(self, r: QRectF):
        rect = self._to_pdf_rect(r)
        if self.mode == "remove":
            self._remember()
            self._cut([rect])
            self._render()
            return
        # replace: the text inside becomes an object with the same look, opened for typing
        lines = self._spans_in(rect)
        item = self._item_from_lines(lines)
        self._remember()
        self._cut([rect])
        if item is None:
            p = r.topLeft() / self.zoom
            style = self._new_item_style()
            item = TextItem(self.page_no, p.x(), p.y() + style["size"] * 0.8, **style)
        self.items.append(item)
        self._render()
        self._select(item)
        self._open_inline(item)

    # ------------------------------------------------------------------ writing
    @staticmethod
    def _rotated_png(img: ImageItem):
        """The picture turned by its angle on a transparent canvas: PNG bytes and the box it covers."""
        src = qimage_of(img)
        a = math.radians(img.angle)
        bw = abs(img.w * math.cos(a)) + abs(img.h * math.sin(a))
        bh = abs(img.w * math.sin(a)) + abs(img.h * math.cos(a))
        k = min(src.width() / max(img.w, 1e-6), 8.0)
        out = QImage(max(1, round(bw * k)), max(1, round(bh * k)), QImage.Format.Format_ARGB32)
        out.fill(0)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(out.width() / 2, out.height() / 2)
        p.rotate(img.angle)
        p.drawImage(QRectF(-img.w * k / 2, -img.h * k / 2, img.w * k, img.h * k), src)
        p.end()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        out.save(buf, "PNG")
        cx, cy = img.x + img.w / 2, img.y + img.h / 2
        return bytes(buf.data()), cx - bw / 2, cy - bh / 2, bw, bh

    def _write_items(self, doc):
        for img in self.images:
            page = doc[img.page]
            if img.vector and not img.angle:
                box = self.fitz.Rect(img.x, img.y, img.x + img.w, img.y + img.h) * page.derotation_matrix
                page.show_pdf_page(box.normalize(), self.fitz.open("pdf", img.data), 0, rotate=page.rotation,
                                   overlay=True)
                continue
            data, x, y, w, h = img.data, img.x, img.y, img.w, img.h
            if img.angle or img.vector:
                data, x, y, w, h = self._rotated_png(img)
            box = self.fitz.Rect(x, y, x + w, y + h) * page.derotation_matrix
            page.insert_image(box.normalize(), stream=data, rotate=page.rotation,
                              keep_proportion=False, overlay=True)
        for item in self.items:
            page = doc[item.page]
            font = font_file(item.font, item.bold, item.italic)
            rgb = QColor(item.color)
            kwargs = {"fontsize": item.size, "color": (rgb.redF(), rgb.greenF(), rgb.blueF()),
                      "rotate": page.rotation}
            if font:
                kwargs.update(fontfile=font, fontname="F" + Path(font).stem)
            derot = page.derotation_matrix
            morph = None
            if item.ocr:
                kwargs["render_mode"] = 3       # invisible: the scan stays as it looks, the text is for search
            elif item.cover:
                cx0, cy0, cx1, cy1 = item.cover
                page.draw_rect(self.fitz.Rect(cx0, cy0, cx1, cy1) * derot, color=None, fill=(1, 1, 1), overlay=True)
            if item.angle:
                c = item.rect(1.0).center()
                morph = (self.fitz.Point(c.x(), c.y()) * derot, self.fitz.Matrix(-item.angle))
            if item.white and not item.ocr:
                r = item.rect(1.0).adjusted(-PAD, -PAD, PAD, PAD)
                box = self.fitz.Rect(r.left(), r.top(), r.right(), r.bottom()) * derot
                if morph:
                    page.draw_quad(box.quad.morph(*morph), color=None, fill=(1, 1, 1), overlay=True)
                else:
                    page.draw_rect(box, color=None, fill=(1, 1, 1), overlay=True)
            for i, line in enumerate(item.lines()):
                if not line.strip():
                    continue
                y = item.y + i * item.size * item.leading
                if not font:
                    page.insert_text(self.fitz.Point(item.x, y) * derot, line, morph=morph, **kwargs)
                    continue
                # word by word: the font's space glyph would be read back as a no-break space, which breaks search
                f = self._pdf_fonts.setdefault(font, self.fitz.Font(fontfile=font))
                adv = 0.0
                for m in re.finditer(r"\S+|\s+", line):
                    if m.group().strip():
                        page.insert_text(self.fitz.Point(item.x + adv, y) * derot, m.group(), morph=morph, **kwargs)
                    adv += f.text_length(m.group(), fontsize=item.size)

    def _final_doc(self):
        doc = self.fitz.open("pdf", self.doc.tobytes())
        self._write_items(doc)
        return doc

    # ------------------------------------------------------------------ save
    def _save(self):
        self._close_inline(True)
        if not self.changed:
            self.reject()
            return
        self.save_to.parent.mkdir(parents=True, exist_ok=True)
        doc = self._final_doc()
        doc.save(self.save_to, garbage=3, deflate=True)
        doc.close()
        # Keep the page without the added text, so the objects stay editable next time.
        base = self.save_to.with_name(self.save_to.stem + ".base.pdf")
        self.doc.save(base, garbage=3, deflate=True)
        self.save_to.with_name(self.save_to.name + SIDECAR).write_text(
            json.dumps({"base": base.name, "items": [asdict(i) for i in self.items],
                        "images": [{**asdict(i), "data": base64.b64encode(i.data).decode()} for i in self.images]},
                       ensure_ascii=False),
            encoding="utf-8")
        self.result = self.save_to
        self.changed = False
        self.accept()

    def _export_text(self, ext: str = ".docx"):
        """The text of the document (recognised, edited, added) as a Word file, an Excel table or plain text."""
        self._close_inline(True)
        label = {".docx": self.t("pdf_export_word"), ".xlsx": self.t("pdf_export_excel"),
                 ".txt": self.t("pdf_export_txt")}[ext]
        start = str(self.save_to.with_suffix(ext)) if self.save_to else ""
        path, _ = QFileDialog.getSaveFileName(self, label, start, f"{label} (*{ext})")
        if not path:
            return
        if Path(path).suffix.lower() != ext:
            path += ext
        try:
            from core import textexport
            doc = self._final_doc()
            try:
                textexport.save(doc, path)
            finally:
                doc.close()
        except Exception as exc:
            QMessageBox.warning(self, self.t("pdf_export"), self.t("pdf_export_fail", err=str(exc)))
            return
        self.hint.setStyleSheet("")
        self.hint.setText(self.t("pdf_export_done", path=path))

    def _save_as(self):
        self._close_inline(True)
        path, _ = QFileDialog.getSaveFileName(self, self.t("pdf_save_as"), "", "PDF (*.pdf)")
        if path:
            try:
                doc = self._final_doc()
                doc.save(path, garbage=3, deflate=True)
                doc.close()
            except Exception as exc:
                QMessageBox.warning(self, self.t("pdf_save_as"), str(exc))

    def reject(self):
        self._close_inline(False)
        if self.changed and QMessageBox.question(
                self, self.windowTitle(), self.t("pdf_discard")) != QMessageBox.StandardButton.Yes:
            return
        super().reject()

    def done(self, r):
        self.doc.close()
        super().done(r)
