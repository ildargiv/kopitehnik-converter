"""Printing: one window with a live preview of the sheet on paper, printer and paper choice,
copies, page range, colour and size on paper, and the code that places pages on the paper."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressDialog, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from core.batch import process_file
from core.loaders import ARCHIVE_EXTS
from core.sheet import compose, fit_photo, geometry, photo_area
from core.printjob import (
    PAPER_BY_KEY, PAPERS, PDF_PRINTER, hardware_margins, make_printer, page_size, parse_range, place,
)

from .theme import PALETTES
from .widgets import AnimatedButton, Card, FitCombo, Segmented

PREVIEW_DPI = 100      # resolution the preview pages are rendered at (paper is laid out in these pixels)
PREVIEW_SIDE = 1100    # pages kept for the preview are shrunk to this many pixels on the long side


def paper_label(key: str, t) -> str:
    (w, h), _ = PAPER_BY_KEY[key]
    names = {"a4": "A4", "a3": "A3", "a5": "A5", "a6": "A6", "letter": "Letter"}
    if key in names:
        return f"{names[key]} · {w:g} × {h:g} {t('print_unit_mm')}"
    return f"{w / 10:g} × {h / 10:g} {t('print_unit_cm')}"


def to_qimage(img) -> QImage:
    from .main_window import pil_to_qimage
    return pil_to_qimage(img)


def render_pages(files, settings, edited: dict[str, str], dpi: int, progress, errors: list[str]):
    """Yield every finished page; with several photos per sheet, yield whole sheets."""
    sheet = settings.sheet
    items = []
    total = max(1, len(files))
    for n, path in enumerate(files):
        if progress is not None:
            if progress.wasCanceled():
                return
            progress.setValue(n)
            progress.setLabelText(path.name)
            QApplication.processEvents()
        try:
            read_from = edited.get(str(path))
            pages = process_file(path, settings, dpi, Path(read_from) if read_from else None)
        except Exception as exc:  # one bad file must not stop the print
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
    if progress is not None:
        progress.setValue(total)


class PreviewPage:
    """A finished page shrunk for the preview, remembering its real size in pixels."""

    def __init__(self, img):
        self.size = img.size
        thumb = img.copy()
        thumb.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
        self.image = to_qimage(thumb)
        self._variants: dict[tuple, QImage] = {}

    def variant(self, rotated: bool, gray: bool) -> QImage:
        key = (rotated, gray)
        if key not in self._variants:
            q = self.image
            if rotated:
                q = q.transformed(QTransform().rotate(90))
            if gray:
                q = q.convertToFormat(QImage.Format.Format_Grayscale8)
            self._variants[key] = q
        return self._variants[key]


class PagePreview(QWidget):
    """The sheet of paper with the page placed on it, drawn the way it will print."""

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.p = palette
        self.pages: list[PreviewPage] = []
        self.index = 0
        self.paper_mm = (210.0, 297.0)
        self.margins_mm = (0.0, 0.0, 0.0, 0.0)
        self.mode = "fit"
        self.rotate = True
        self.gray = False
        self.message = ""
        self.setMinimumSize(360, 360)

    def landscape(self) -> bool:
        return self.paper_mm[0] > self.paper_mm[1]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(self.rect()), 14, 14)
        p.setClipPath(frame)
        p.fillPath(frame, QColor(self.p["canvas"]))
        px = PREVIEW_DPI / 25.4
        pw, ph = self.paper_mm[0] * px, self.paper_mm[1] * px
        avail = QRectF(self.rect()).adjusted(28, 28, -28, -28)
        k = min(avail.width() / pw, avail.height() / ph)
        if k <= 0:
            return
        ox, oy = avail.center().x() - pw * k / 2, avail.center().y() - ph * k / 2
        for i in range(6, 0, -1):   # soft shadow under the sheet
            p.fillRect(QRectF(ox - i + 1, oy - i + 5, pw * k + 2 * i - 2, ph * k + 2 * i - 2), QColor(0, 0, 0, 9))
        p.save()
        p.translate(ox, oy)
        p.scale(k, k)
        paper = QRectF(0, 0, pw, ph)
        p.fillRect(paper, QColor("#ffffff"))
        l, t, r, b = (m * px for m in self.margins_mm)
        page = paper.adjusted(l, t, -r, -b)
        if self.pages and 0 <= self.index < len(self.pages):
            pg = self.pages[self.index]
            w, h = pg.size
            rotated = self.rotate and w != h and (w > h) != self.landscape()
            if rotated:
                w, h = h, w
            target, src = place((w, h), PREVIEW_DPI, paper, page, self.mode, PREVIEW_DPI)
            q = pg.variant(rotated, self.gray)
            sx, sy = q.width() / w, q.height() / h
            p.save()
            p.setClipRect(paper)
            p.drawImage(target, q, QRectF(src.x() * sx, src.y() * sy, src.width() * sx, src.height() * sy))
            p.restore()
        if self.mode == "fit":   # the printable area
            pen = QPen(QColor(self.p["accent"]), 1.2 / k, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(page)
        p.restore()
        p.setPen(QColor(self.p["muted"]))
        if not self.pages:
            p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.message)

    def wheelEvent(self, e):
        if e.angleDelta().y() and self.pages:
            self.parent_dialog.step(-1 if e.angleDelta().y() > 0 else 1)

    parent_dialog = None


class PrintDialog(QDialog):
    def __init__(self, window, files: list[Path], settings, edited: dict[str, str], current: Path | None):
        super().__init__(window)
        self.window_ = window
        self.t = window.t
        t = self.t
        self.settings = settings
        self.edited = edited
        self.all_files = [f for f in files if f.suffix.lower() not in ARCHIVE_EXTS]
        self.current = current if current and current.suffix.lower() not in ARCHIVE_EXTS else None
        self.store = window.store
        self.errors: list[str] = []
        self.cache: dict[str, list[PreviewPage]] = {}
        self.printer: QPrinter | None = None   # created once the driver's own dialog was opened
        sheet = settings.sheet.enabled

        self.setWindowTitle(t("print_title"))
        self.setStyleSheet(window.styleSheet())
        self.resize(1120, 780)
        self.setMinimumSize(960, 640)
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # ---- left: preview
        left = QVBoxLayout()
        left.setSpacing(8)
        self.preview = PagePreview(PALETTES[window.theme])
        self.preview.parent_dialog = self
        left.addWidget(self.preview, 1)
        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.prev_btn = AnimatedButton("‹")
        self.next_btn = AnimatedButton("›")
        for b in (self.prev_btn, self.next_btn):
            b.setFixedWidth(40)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        self.page_label = QLabel()
        self.info_label = QLabel()
        self.info_label.setObjectName("hint")
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.page_label)
        nav.addWidget(self.next_btn)
        nav.addSpacing(12)
        nav.addWidget(self.info_label, 1)
        left.addLayout(nav)
        root.addLayout(left, 1)

        # ---- right: settings
        side = QVBoxLayout()
        side.setSpacing(10)
        area = QScrollArea()
        area.setObjectName("sidebar")
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setFixedWidth(392)
        inner = QWidget()
        inner.setObjectName("sidebarInner")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(10)

        card = Card(collapsible=False)
        card.title.setText(t("print_what"))
        self.what = Segmented([("one", t("print_current")), ("all", t("print_all", n=len(self.all_files)))])
        self.what.buttons["one"].setEnabled(bool(self.current) and not sheet)
        self.what.set_value("one" if self.current and not sheet and len(self.all_files) > 1 else "all")
        self.what.changed.connect(lambda *_: self._load_preview())
        card.add(self.what)
        if sheet:
            note = QLabel(t("print_sheet_note"))
            note.setObjectName("hint")
            note.setWordWrap(True)
            card.add(note)
        col.addWidget(card)

        card = Card(collapsible=False)
        card.title.setText(t("print_printer"))
        self.printer_combo = FitCombo()
        names = [i.printerName() for i in QPrinterInfo.availablePrinters()]
        default = QPrinterInfo.defaultPrinterName()
        for n in names:
            self.printer_combo.addItem(n, n)
        self.printer_combo.addItem(t("print_pdf_printer"), PDF_PRINTER)
        wanted = self.store.value("print_printer", default) or default
        idx = self.printer_combo.findData(wanted)
        if idx < 0:
            idx = self.printer_combo.findData(default)
        self.printer_combo.setCurrentIndex(idx if idx >= 0 else self.printer_combo.count() - 1)
        self.printer_combo.currentIndexChanged.connect(self._printer_changed)
        card.add(self.printer_combo)
        self.props_btn = AnimatedButton(t("print_props"))
        self.props_btn.setToolTip(t("print_props_tip"))
        self.props_btn.clicked.connect(self._driver_dialog)
        card.add(self.props_btn)
        if not names:
            note = QLabel(t("print_no_printers"))
            note.setObjectName("hint")
            note.setWordWrap(True)
            card.add(note)
        col.addWidget(card)

        card = Card(collapsible=False)
        card.title.setText(t("print_paper_card"))
        self.paper_combo = FitCombo()
        for key, _mm, _pid in PAPERS:
            self.paper_combo.addItem(paper_label(key, t), key)
        sheet_paper = settings.sheet.paper if sheet and settings.sheet.paper in PAPER_BY_KEY else None
        want_paper = sheet_paper or self.store.value("print_paper", "a4")
        self.paper_combo.setCurrentIndex(max(0, self.paper_combo.findData(want_paper)))
        self.paper_combo.currentIndexChanged.connect(self._layout_changed)
        card.add(self.paper_combo)
        self.orient = Segmented([("auto", t("print_orient_auto")), ("portrait", t("print_orient_portrait")),
                                 ("landscape", t("print_orient_landscape"))])
        if sheet:
            self.orient.set_value("landscape" if settings.sheet.landscape else "portrait")
        else:
            self.orient.set_value(self.store.value("print_orient", "auto"))
        self.orient.changed.connect(self._layout_changed)
        card.add(self.orient)
        margin_row = QHBoxLayout()
        margin_row.addWidget(QLabel(t("print_margins")))
        margin_row.addStretch(1)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 50)
        self.margin_spin.setSuffix(f" {t('print_unit_mm')}")
        self.margin_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.margin_spin.setFixedWidth(84)
        self.margin_spin.setValue(int(self.store.value("print_margin", 0) or 0))
        self.margin_spin.valueChanged.connect(self._layout_changed)
        margin_row.addWidget(self.margin_spin)
        self.margin_row = QWidget()
        self.margin_row.setLayout(margin_row)
        margin_row.setContentsMargins(0, 0, 0, 0)
        card.add(self.margin_row)
        self.margin_hint = QLabel(t("print_margins_hint"))
        self.margin_hint.setObjectName("hint")
        self.margin_hint.setWordWrap(True)
        card.add(self.margin_hint)
        col.addWidget(card)

        card = Card(collapsible=False)
        card.title.setText(t("print_scale"))
        self.scale = Segmented([("fit", t("print_fit")), ("fill", t("print_fill")), ("actual", t("print_actual"))])
        self.scale.set_value("actual" if sheet else self.store.value("print_scale", "fit"))
        self.scale.changed.connect(self._scale_changed)
        card.add(self.scale)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        card.add(self.hint)
        self.rotate = QCheckBox(t("print_rotate"))
        self.rotate.setChecked(True)
        self.rotate.toggled.connect(self._layout_changed)
        card.add(self.rotate)
        col.addWidget(card)

        card = Card(collapsible=False)
        card.title.setText(t("print_job"))
        row = QHBoxLayout()
        row.addWidget(QLabel(t("print_copies")))
        row.addStretch(1)
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        self.copies.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.copies.setFixedWidth(84)
        row.addWidget(self.copies)
        card.add(row)
        card.add(self._caption(t("print_pages")))
        self.pages_mode = Segmented([("all", t("print_pages_all")), ("range", t("print_pages_range"))])
        self.pages_mode.changed.connect(self._pages_mode_changed)
        card.add(self.pages_mode)
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText(t("print_pages_ph"))
        self.range_edit.textChanged.connect(self._range_changed)
        self.range_edit.hide()
        card.add(self.range_edit)
        card.add(self._caption(t("print_color")))
        self.color = Segmented([("color", t("print_color_color")), ("gray", t("print_color_gray"))])
        self.color.set_value(self.store.value("print_color", "color"))
        self.color.changed.connect(self._layout_changed)
        card.add(self.color)
        card.add(self._caption(t("print_quality")))
        self.quality = Segmented([("150", t("print_q_draft")), ("300", t("print_q_normal"))])
        self.quality.set_value(self.store.value("print_quality", "150" if settings.output.dpi <= 150 else "300"))
        card.add(self.quality)
        col.addWidget(card)
        col.addStretch(1)
        area.setWidget(inner)
        side.addWidget(area, 1)

        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        side.addWidget(self.summary)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        cancel = AnimatedButton(t("cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        self.print_btn = AnimatedButton()
        self.print_btn.setObjectName("primary")
        self.print_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.print_btn.clicked.connect(self._print)
        buttons.addWidget(self.print_btn)
        side.addLayout(buttons)
        root.addLayout(side)

        self.copies.valueChanged.connect(self._refresh_summary)

        self._scale_changed()
        self.preview.message = t("print_preview_loading")
        QTimer.singleShot(60, self._load_preview)

    def keyPressEvent(self, e):
        keys = {Qt.Key.Key_Left: -1, Qt.Key.Key_PageUp: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_PageDown: 1}
        if e.key() in keys:   # fields that need these keys handle them first
            self.step(keys[e.key()])
            return
        super().keyPressEvent(e)

    @staticmethod
    def _caption(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("muted")
        return lab

    # ------------------------------------------------------------------ state
    def scope_files(self) -> list[Path]:
        if self.what.value() == "one" and self.current:
            return [self.current]
        return self.all_files

    def printer_name(self) -> str:
        return self.printer_combo.currentData() or PDF_PRINTER

    def is_pdf(self) -> bool:
        return self.printer_name() == PDF_PRINTER

    def total(self) -> int:
        return len(self.cache.get(self._scope_key(), []))

    def _scope_key(self) -> str:
        return "one" if self.what.value() == "one" and self.current else "all"

    def selected_sheets(self) -> list[int] | None:
        """Sheet numbers to print (1-based), or None when the range text is wrong."""
        total = self.total()
        if self.pages_mode.value() == "all":
            return list(range(1, total + 1))
        return parse_range(self.range_edit.text(), total)

    def _landscape(self) -> bool:
        o = self.orient.value()
        if o == "auto":
            pages = self.cache.get(self._scope_key())
            if pages:
                w, h = pages[0].size
                return w > h
            return False
        return o == "landscape"

    # ------------------------------------------------------------------ reactions
    def _scale_changed(self, *_):
        self.hint.setText(self.t(f"print_{self.scale.value()}_hint"))
        fit = self.scale.value() == "fit"
        self.margin_row.setVisible(fit)
        self.margin_hint.setVisible(fit)
        self._layout_changed()

    def _printer_changed(self, *_):
        self.printer = None
        self.props_btn.setEnabled(not self.is_pdf())
        self._layout_changed()

    def _pages_mode_changed(self, *_):
        self.range_edit.setVisible(self.pages_mode.value() == "range")
        self._range_changed()

    def _range_changed(self, *_):
        bad = self.pages_mode.value() == "range" and self.selected_sheets() is None
        self.range_edit.setStyleSheet(f"border-color: {PALETTES[self.window_.theme]['error']};" if bad else "")
        self._refresh_summary()

    def _layout_changed(self, *_):
        pv = self.preview
        key = self.paper_combo.currentData()
        (w, h), _ = PAPER_BY_KEY[key]
        landscape = self._landscape()
        pv.paper_mm = (h, w) if landscape else (w, h)
        pv.mode = self.scale.value()
        pv.rotate = self.rotate.isChecked()
        pv.gray = self.color.value() == "gray"
        hw = hardware_margins(self.printer_name(), key, landscape)
        user = float(self.margin_spin.value())
        pv.margins_mm = tuple(max(user, m) for m in hw)
        self._hw = hw
        pv.update()
        self._refresh_summary()

    def step(self, d: int):
        n = self.total()
        if not n:
            return
        self.preview.index = max(0, min(n - 1, self.preview.index + d))
        self.preview.update()
        self._refresh_summary()

    def _refresh_summary(self):
        t = self.t
        n = self.total()
        pv = self.preview
        self.prev_btn.setEnabled(pv.index > 0)
        self.next_btn.setEnabled(pv.index < n - 1)
        self.page_label.setText(t("print_page_of", i=pv.index + 1, n=n) if n else "")
        landscape = pv.landscape()
        self.info_label.setText(f"{paper_label(self.paper_combo.currentData(), t)}, "
                                f"{t('print_orient_landscape' if landscape else 'print_orient_portrait').lower()}")
        sheets = self.selected_sheets() if n else []
        count = len(sheets) if sheets else 0
        copies = 1 if self.is_pdf() else self.copies.value()
        self.summary.setText(t("print_summary", n=count, c=copies, total=count * copies) if n else "")
        pdf = self.is_pdf()
        self.print_btn.setText(t("print_save_pdf") if pdf else t("print_btn"))
        self.print_btn.setEnabled(bool(n) and bool(sheets))
        self.copies.setEnabled(not pdf)

    # ------------------------------------------------------------------ preview pages
    def _load_preview(self):
        t = self.t
        key = self._scope_key()
        if key not in self.cache:
            files = self.scope_files()
            progress = QProgressDialog(t("print_rendering"), t("cancel"), 0, max(1, len(files)), self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(300)
            progress.setStyleSheet(self.styleSheet())
            pages: list[PreviewPage] = []
            self.errors.clear()
            for img in render_pages(files, self.settings, self.edited, PREVIEW_DPI, progress, self.errors):
                pages.append(PreviewPage(img))
            progress.close()
            self.cache[key] = pages
            if self.errors:
                for e in self.errors:
                    self.window_.log("error", e)
        pages = self.cache[key]
        self.preview.pages = pages
        self.preview.index = 0
        self.preview.message = "" if pages else t("print_nothing_to_show")
        self._layout_changed()

    # ------------------------------------------------------------------ the driver's own dialog
    def _prepare(self, printer: QPrinter):
        key = self.paper_combo.currentData()
        printer.setPageSize(page_size(key))
        printer.setPageOrientation(QPageLayout.Orientation.Landscape if self._landscape()
                                   else QPageLayout.Orientation.Portrait)
        printer.setFullPage(True)   # the program places the page itself, so margins are exact
        printer.setColorMode(QPrinter.ColorMode.GrayScale if self.color.value() == "gray"
                             else QPrinter.ColorMode.Color)

    def _driver_dialog(self):
        """Paper type, print quality and the rest live in the printer's own dialog."""
        if self.is_pdf():
            return
        if self.printer is None:
            self.printer = make_printer(self.printer_name())
        self._prepare(self.printer)
        self.printer.setCopyCount(self.copies.value())
        dlg = QPrintDialog(self.printer, self)
        dlg.setWindowTitle(self.t("print_props"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pr = self.printer
        self.copies.setValue(max(1, pr.copyCount()))
        landscape = pr.pageLayout().orientation() == QPageLayout.Orientation.Landscape
        self.orient.set_value("landscape" if landscape else "portrait")
        self.color.set_value("gray" if pr.colorMode() == QPrinter.ColorMode.GrayScale else "color")
        size = pr.pageLayout().pageSize().size(QPageSize.Unit.Millimeter)
        for key, (mm, _pid) in PAPER_BY_KEY.items():
            if sorted((round(size.width()), round(size.height()))) == sorted((round(mm[0]), round(mm[1]))):
                self.paper_combo.setCurrentIndex(self.paper_combo.findData(key))
                break
        self._layout_changed()

    # ------------------------------------------------------------------ printing
    def _print(self):
        t = self.t
        sheets = self.selected_sheets()
        if not sheets:
            return
        name = self.printer_name()
        if self.is_pdf():
            base = self.store.value("output_dir", "") or str(Path.home())
            stem = self.scope_files()[0].stem if len(self.scope_files()) == 1 else "KopiTehnik"
            path, _ = QFileDialog.getSaveFileName(self, t("print_pdf_file"), str(Path(base) / f"{stem}.pdf"),
                                                  "PDF (*.pdf)")
            if not path:
                return
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
            target = Path(path).name
        else:
            printer = self.printer or make_printer(name)
            target = name
        self._prepare(printer)
        landscape = self._landscape()
        manual_copies = 1
        copies = 1 if self.is_pdf() else self.copies.value()
        if copies > 1:
            if printer.supportsMultipleCopies():
                printer.setCopyCount(copies)
            else:
                manual_copies = copies
        stem = self.scope_files()[0].stem if len(self.scope_files()) == 1 else "KopiTehnik"
        printer.setDocName(stem)
        self._remember()
        done = self._paint(printer, set(sheets), landscape, manual_copies)
        if done is None:
            self.window_.status_label.setText(t("print_failed"))
            return
        if self.is_pdf():
            self.window_.status_label.setText(t("print_saved", name=target))
        else:
            self.window_.status_label.setText(t("print_done", n=done, name=target))
        if self.errors:
            for e in self.errors:
                self.window_.log("error", e)
            self.window_.status_label.setText(t("print_errors", n=len(self.errors)))
        self.accept()

    def _remember(self):
        s = self.store
        s.setValue("print_printer", self.printer_name())
        if not self.settings.sheet.enabled:
            s.setValue("print_paper", self.paper_combo.currentData())
            s.setValue("print_orient", self.orient.value())
            s.setValue("print_scale", self.scale.value())
        s.setValue("print_margin", self.margin_spin.value())
        s.setValue("print_color", self.color.value())
        s.setValue("print_quality", self.quality.value())

    def _paint(self, printer: QPrinter, wanted: set[int], landscape: bool, repeat: int) -> int | None:
        """Render at print quality and send the chosen sheets. Returns pages printed, None on failure."""
        files = self.scope_files()
        dpi = int(self.quality.value())
        gray = self.color.value() == "gray"
        mode = self.scale.value()
        rotate = self.rotate.isChecked()
        progress = QProgressDialog(self.t("print_rendering"), self.t("cancel"), 0, max(1, len(files)), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        progress.setStyleSheet(self.styleSheet())
        painter = QPainter()
        if not painter.begin(printer):
            progress.close()
            return None
        res = printer.resolution()
        pf = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
        paper = QRectF(printer.paperRect(QPrinter.Unit.DevicePixel))
        paper.translate(-pf.left(), -pf.top())
        key = self.paper_combo.currentData()
        user = float(self.margin_spin.value())
        l, t_, r, b = (max(user, m) * res / 25.4 for m in hardware_margins(self.printer_name(), key, landscape))
        page = paper.adjusted(l, t_, -r, -b)
        printed = 0
        self.errors.clear()
        for number, img in enumerate(render_pages(files, self.settings, self.edited, dpi, progress, self.errors), 1):
            if number not in wanted:
                continue
            if gray:
                img = img.convert("L").convert("RGB")
            if rotate and img.width != img.height and (img.width > img.height) != (paper.width() > paper.height()):
                img = img.rotate(90, expand=True)
            target, src = place(img.size, dpi, paper, page, mode, res)
            qimg = to_qimage(img)
            for _ in range(repeat):
                if printed:
                    printer.newPage()
                painter.save()
                painter.setClipRect(paper)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawImage(target, qimg, src)
                painter.restore()
                printed += 1
        painter.end()
        progress.close()
        return printed


def run_print(window, files: list[Path], settings, edited: dict[str, str], has_current: bool, current: Path | None):
    t = window.t
    if not [f for f in files if f.suffix.lower() not in ARCHIVE_EXTS]:
        window.status_label.setText(t("print_nothing"))
        return
    dlg = PrintDialog(window, files, settings, edited, current if has_current else None)
    dlg.exec()
