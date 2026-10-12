"""The main application window."""
from __future__ import annotations

import copy
import json
import os
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThread, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from core.batch import Batch, BatchResult, SourceFile, scan_folder
from PIL import Image

from core.imaging import (
    SIZE_PRESETS, ColorSettings, FrameSettings, JobSettings, OutputSettings, apply_color, apply_frame, crop_box, fit_pad,
    orient, ratio_pair, white_balance_from_pixel,
)
from dataclasses import replace
from PIL import ImageDraw
from core.sheet import PAPERS, PRESETS, SheetSettings, apply_preset, compose, fit_photo, geometry, photo_area
from core.loaders import ARCHIVE_EXTS, SUPPORTED_EXTS, is_photo, load_pages
from core import office

from .i18n import LANGUAGES, system_language, tr
from .about import AboutDialog
from .programs import ProgramsDialog, summary
from .theme import ICONS, PALETTES, stylesheet
from .widgets import (
    AnimatedButton, BrandTitle, Card, FitCombo, KeepLayoutFresh, LogoMark, PreviewCanvas, Segmented, SliderRow,
    icon_button,
)

from core.version import VERSION as APP_VERSION
PREVIEW_SIZE = 1600

COLOR_SLIDERS = [
    ("auto", None), ("brightness", None), ("contrast", None), ("saturation", None), ("gamma", None),
]
CHANNEL_SLIDERS = [
    ("red", "#ef4444"), ("green", "#22c55e"), ("blue", "#3b82f6"),
    ("cyan", "#06b6d4"), ("magenta", "#d946ef"), ("yellow", "#eab308"),
]
RATIO_KEYS = ["original", "3:2", "4:3", "5:4", "7:5", "1:1", "16:9", "a4", "custom"]


def pil_to_qimage(img) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    q = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    return q.copy()


# --------------------------------------------------------------------------- background jobs

class _PreviewSignals(QObject):
    done = Signal(str, object, str)  # path, PIL image or None, error


class PreviewJob(QRunnable):
    def __init__(self, path: Path, read_from: Path | None = None):
        super().__init__()
        self.path = path
        self.read_from = read_from or path   # an edited PDF replaces the original
        self.signals = _PreviewSignals()

    def run(self):
        try:
            pages = load_pages(self.read_from, max_pages=1, preview_size=PREVIEW_SIZE)
            self.signals.done.emit(str(self.path), pages[0], "")
        except Exception as exc:
            self.signals.done.emit(str(self.path), None, str(exc))


class ConvertThread(QThread):
    progress = Signal(int, int, str)
    log = Signal(str, str)
    file_done = Signal(str, bool, str)
    result = Signal(object)

    def __init__(self, batch: Batch):
        super().__init__()
        self.batch = batch
        batch.on_progress = lambda d, t, n: self.progress.emit(d, t, n)
        batch.on_log = lambda lvl, m: self.log.emit(lvl, m)
        batch.on_file = lambda label, ok, info: self.file_done.emit(label, ok, info)

    def run(self):
        try:
            res = self.batch.run()
        except Exception as exc:
            self.log.emit("error", str(exc))
            res = BatchResult()
        self.result.emit(res)


# --------------------------------------------------------------------------- window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = QSettings()
        self.lang = self.store.value("lang", system_language())
        if self.lang not in LANGUAGES:
            self.lang = "ru"
        self.theme = self.store.value("theme", "dark")
        if self.theme not in PALETTES:
            self.theme = "dark"
        self.settings = self._load_job_settings()
        office.set_preference(self.store.value("office_engine", office.ENGINE_AUTO))
        try:
            office.set_custom_libreoffice(self.store.value("lo_custom", "") or None)
        except office.OfficeError:
            pass  # the chosen copy was moved or deleted

        self.sources: list[SourceFile] = []
        self.extra_files: list[Path] = []
        self._folder_text = ""       # folder text at the last scan
        self.current = -1
        self.preview_cache: OrderedDict[str, object] = OrderedDict()
        self.preview_errors: dict[str, str] = {}
        self.pending_previews: set[str] = set()
        self.pool = QThreadPool.globalInstance()
        self.thread: ConvertThread | None = None
        self.items: dict[str, QListWidgetItem] = {}
        self._texts: list[tuple[object, str, str]] = []   # (widget, key, method)

        self.setWindowTitle(tr(self.lang, "app_title"))
        self.setMinimumSize(1240, 720)
        self.setAcceptDrops(True)

        self._preview_timer = QTimer(self, singleShot=True, interval=35)
        self._preview_timer.timeout.connect(self._render_preview)

        self._build()
        self._apply_theme()
        self._restore_state()
        self._retranslate()
        self.rescan()
        QTimer.singleShot(400, self._startup_check)

    # ------------------------------------------------------------------ i18n helpers
    def t(self, key: str, **kw) -> str:
        return tr(self.lang, key, **kw)

    def _bind(self, widget, key: str, method: str = "setText"):
        self._texts.append((widget, key, method))
        getattr(widget, method)(self.t(key))
        return widget

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._build_header())

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setHandleWidth(10)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_workspace())
        body.addWidget(self._build_color_column())
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        body.setSizes([400, 700, 380])
        self.body_splitter = body
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(16, 4, 16, 14)
        wl.addWidget(body)
        v.addWidget(wrap, 1)
        v.addWidget(self._build_footer())

        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=self.prev_file)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=self.next_file)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.start)

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("header")
        h = QHBoxLayout(w)
        h.setContentsMargins(18, 14, 18, 10)
        h.setSpacing(12)
        h.addWidget(LogoMark("К"))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_label = self._bind(BrandTitle(), "app_title")
        self.subtitle_label = self._bind(QLabel(), "app_subtitle")
        self.subtitle_label.setObjectName("appSubtitle")
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        h.addLayout(titles)
        h.addStretch(1)

        self.programs_btn = self._bind(AnimatedButton(), "programs")
        self._bind(self.programs_btn, "programs_tip", "setToolTip")
        self.programs_btn.clicked.connect(lambda: self.show_programs())
        h.addWidget(self.programs_btn)

        self.about_btn = self._bind(AnimatedButton(), "about")
        self._bind(self.about_btn, "about_tip", "setToolTip")
        self.about_btn.clicked.connect(self.show_about)
        h.addWidget(self.about_btn)

        self.lang_combo = FitCombo()
        for code, name in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentIndex(list(LANGUAGES).index(self.lang))
        self.lang_combo.currentIndexChanged.connect(self._lang_changed)
        h.addWidget(self.lang_combo)

        self.theme_btn = icon_button("sun")
        self.theme_btn.setFixedSize(36, 36)
        self.theme_btn.clicked.connect(self._toggle_theme)
        self._bind(self.theme_btn, "theme_toggle", "setToolTip")
        h.addWidget(self.theme_btn)
        return w

    def _build_sidebar(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("sidebar")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(390)
        scroll.setMaximumWidth(470)
        KeepLayoutFresh(scroll)
        inner = QWidget()
        inner.setObjectName("sidebarInner")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(12)
        self.cards = {}
        for key, builder in (
            ("source", self._card_source),
            ("output", self._card_output),
            ("frame", self._card_frame),
        ):
            card = builder()
            self.cards[key] = card
            col.addWidget(card)
        col.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _path_row(self, key: str, browse) -> tuple[QHBoxLayout, QLineEdit]:
        row = QHBoxLayout()
        row.setSpacing(6)
        edit = QLineEdit()
        self._bind(edit, key, "setPlaceholderText")
        row.addWidget(edit, 1)
        b = icon_button("folder", ghost=False)
        b.setFixedSize(34, 34)
        self._bind(b, "browse", "setToolTip")
        b.clicked.connect(browse)
        row.addWidget(b)
        return row, edit

    def _card_source(self) -> Card:
        c = Card()
        self._bind(c.title, "card_source")
        row, self.input_edit = self._path_row("input_placeholder", self._browse_input)
        self.input_edit.editingFinished.connect(self._folder_edited)
        c.add(row)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.add_files_btn = self._bind(AnimatedButton(), "add_files")
        self.add_files_btn.clicked.connect(self._add_files_dialog)
        btns.addWidget(self.add_files_btn)
        self.clear_files_btn = self._bind(AnimatedButton(), "clear_files")
        self.clear_files_btn.clicked.connect(self._clear_extra)
        btns.addWidget(self.clear_files_btn)
        btns.addStretch(1)
        refresh = icon_button("refresh")
        self._bind(refresh, "rescan", "setToolTip")
        refresh.clicked.connect(self.rescan)
        btns.addWidget(refresh)
        c.add(btns)
        self.found_label = QLabel()
        self.found_label.setObjectName("hint")
        c.add(self.found_label)
        return c

    def _card_output(self) -> Card:
        c = Card()
        self._bind(c.title, "card_output")
        open_btn = icon_button("open")
        self._bind(open_btn, "open_output", "setToolTip")
        open_btn.clicked.connect(self._open_output)
        c.header_tools.addWidget(open_btn)
        row, self.output_edit = self._path_row("output_placeholder", self._browse_output)
        c.add(row)

        self.format_seg = Segmented([("JPEG", "JPG"), ("PNG", "PNG"), ("TIFF", "TIFF"), ("PDF", "PDF")])
        self.format_seg.changed.connect(self._format_changed)
        c.add(self.format_seg)

        self.quality_row = SliderRow("quality", "", 60, 100, 95)
        self._bind(self.quality_row.label, "quality")
        self.quality_row.value_label.setProperty("changed", False)
        self.quality_row.slider.valueChanged.connect(lambda v: self.quality_row.value_label.setText(str(v)))
        self.quality_row.value_label.setText("95")
        c.add(self.quality_row)

        dpi_row = QHBoxLayout()
        dpi_label = self._bind(QLabel(), "doc_dpi")
        dpi_row.addWidget(dpi_label)
        dpi_row.addStretch(1)
        self.dpi_combo = FitCombo()
        self.dpi_combo.currentIndexChanged.connect(lambda *_: hasattr(self, "px_label") and self._update_custom_ui())
        for d in (150, 200, 300, 400, 600):
            self.dpi_combo.addItem(f"{d} dpi", d)
        dpi_row.addWidget(self.dpi_combo)
        c.add(dpi_row)

        self.keep_structure = self._bind(QCheckBox(), "keep_structure")
        c.add(self.keep_structure)
        self.merge_pdf = self._bind(QCheckBox(), "merge_pdf")
        c.add(self.merge_pdf)
        self.pdf_hint = self._bind(QLabel(), "pdf_hint")
        self.pdf_hint.setObjectName("hint")
        self.pdf_hint.setWordWrap(True)
        c.add(self.pdf_hint)

        self.sheet_check = self._bind(QCheckBox(), "sheet_enable")
        self.sheet_check.toggled.connect(self._sheet_changed)
        c.add(self.sheet_check)
        self.sheet_box = QWidget()
        sb = QVBoxLayout(self.sheet_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(8)
        self.sheet_preset = FitCombo()
        self.sheet_preset.addItem("", "custom")
        for k in PRESETS:
            self.sheet_preset.addItem("", k)
        self.sheet_preset.currentIndexChanged.connect(self._sheet_preset_chosen)
        sb.addWidget(self._bind(QLabel(), "sheet_preset"))
        sb.addWidget(self.sheet_preset)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        self.sheet_paper = FitCombo()
        for k in PAPERS:
            self.sheet_paper.addItem(k.upper() if k.startswith("a") else k, k)
        self.sheet_paper.setCurrentIndex(self.sheet_paper.findData("a4"))
        self.sheet_paper.currentIndexChanged.connect(self._sheet_edited)
        grid.addWidget(self._bind(QLabel(), "sheet_paper"), 0, 0)
        grid.addWidget(self.sheet_paper, 0, 1, 1, 3)
        self.sheet_cols = QSpinBox()
        self.sheet_rows = QSpinBox()
        for sp in (self.sheet_cols, self.sheet_rows):
            sp.setRange(1, 10)
            sp.setFixedWidth(56)
            sp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sp.valueChanged.connect(self._sheet_edited)
        self.sheet_cols.setValue(2)
        self.sheet_rows.setValue(2)
        self.sheet_grid_label = self._bind(QLabel(), "sheet_grid")
        grid.addWidget(self.sheet_grid_label, 1, 0)
        grid.addWidget(self.sheet_cols, 1, 1)
        grid.addWidget(QLabel("×"), 1, 2)
        grid.addWidget(self.sheet_rows, 1, 3)
        self.sheet_fixed = self._bind(QCheckBox(), "sheet_fixed")
        self.sheet_fixed.toggled.connect(self._sheet_edited)
        grid.addWidget(self.sheet_fixed, 2, 0)
        self.sheet_pw = QDoubleSpinBox()
        self.sheet_ph = QDoubleSpinBox()
        for sp, v in ((self.sheet_pw, 9.0), (self.sheet_ph, 12.0)):
            sp.setRange(1, 60)
            sp.setDecimals(1)
            sp.setSingleStep(0.5)
            sp.setValue(v)
            sp.setFixedWidth(64)
            sp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sp.valueChanged.connect(self._sheet_edited)
        grid.addWidget(self.sheet_pw, 2, 1)
        grid.addWidget(QLabel("×"), 2, 2)
        grid.addWidget(self.sheet_ph, 2, 3)
        self.sheet_copies = QSpinBox()
        self.sheet_copies.setRange(0, 99)
        self.sheet_copies.setValue(1)
        self.sheet_copies.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sheet_copies.valueChanged.connect(self._sheet_edited)
        grid.addWidget(self._bind(QLabel(), "sheet_copies"), 3, 0)
        grid.addWidget(self.sheet_copies, 3, 1, 1, 3)
        self.sheet_margin = QDoubleSpinBox()
        self.sheet_gap = QDoubleSpinBox()
        for sp, v in ((self.sheet_margin, 10.0), (self.sheet_gap, 5.0)):
            sp.setRange(0, 50)
            sp.setDecimals(1)
            sp.setValue(v)
            sp.valueChanged.connect(self._sheet_edited)
        grid.addWidget(self._bind(QLabel(), "sheet_margin"), 4, 0)
        grid.addWidget(self.sheet_margin, 4, 1, 1, 3)
        grid.addWidget(self._bind(QLabel(), "sheet_gap"), 5, 0)
        grid.addWidget(self.sheet_gap, 5, 1, 1, 3)
        sb.addLayout(grid)
        self.sheet_landscape = self._bind(QCheckBox(), "sheet_landscape")
        self.sheet_landscape.toggled.connect(self._sheet_edited)
        sb.addWidget(self.sheet_landscape)
        self.sheet_fill = self._bind(QCheckBox(), "sheet_fill")
        self.sheet_fill.toggled.connect(self._sheet_edited)
        sb.addWidget(self.sheet_fill)
        self.sheet_rotate = self._bind(QCheckBox(), "sheet_rotate")
        self.sheet_rotate.setChecked(True)
        self.sheet_rotate.toggled.connect(self._sheet_edited)
        sb.addWidget(self.sheet_rotate)
        self.sheet_marks = self._bind(QCheckBox(), "sheet_marks")
        self.sheet_marks.toggled.connect(self._sheet_edited)
        sb.addWidget(self.sheet_marks)
        self.sheet_captions = self._bind(QCheckBox(), "sheet_captions")
        self.sheet_captions.toggled.connect(self._sheet_edited)
        sb.addWidget(self.sheet_captions)
        self.sheet_hint = QLabel()
        self.sheet_hint.setObjectName("hint")
        self.sheet_hint.setWordWrap(True)
        sb.addWidget(self.sheet_hint)
        c.add(self.sheet_box)
        self.sheet_box.setVisible(False)
        return c

    def _card_frame(self) -> Card:
        c = Card()
        self._bind(c.title, "card_frame")
        r1 = QHBoxLayout()
        r1.addWidget(self._bind(QLabel(), "ratio"))
        r1.addStretch(1)
        self.ratio_combo = FitCombo()
        self.ratio_combo.setMinimumWidth(170)
        for k in RATIO_KEYS:
            self.ratio_combo.addItem(k, k)
        self.ratio_combo.currentIndexChanged.connect(self._ratio_changed)
        r1.addWidget(self.ratio_combo)
        c.add(r1)

        self.custom_box = QWidget()
        cb = QVBoxLayout(self.custom_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(8)
        preset_row = QHBoxLayout()
        preset_row.addWidget(self._bind(QLabel(), "size_preset"))
        preset_row.addStretch(1)
        self.preset_combo = FitCombo()
        self.preset_combo.addItem("—", None)
        for w_, h_, u_ in SIZE_PRESETS:
            self.preset_combo.addItem(f"{w_:g}×{h_:g} {u_}", (w_, h_, u_))
        self.preset_combo.currentIndexChanged.connect(self._preset_chosen)
        preset_row.addWidget(self.preset_combo)
        cb.addLayout(preset_row)
        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self.size_w = QDoubleSpinBox()
        self.size_h = QDoubleSpinBox()
        for sp in (self.size_w, self.size_h):
            sp.setRange(0.5, 500)
            sp.setDecimals(1)
            sp.setSingleStep(0.5)
            sp.valueChanged.connect(self._size_edited)
        self.unit_combo = FitCombo()
        for u in ("cm", "mm", "in"):
            self.unit_combo.addItem(u, u)
        self.unit_combo.currentIndexChanged.connect(self._size_edited)
        size_row.addWidget(self.size_w, 1)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.size_h, 1)
        size_row.addWidget(self.unit_combo)
        cb.addLayout(size_row)
        self.fit_seg = Segmented([("crop", ""), ("fit", "")])
        self.fit_seg.changed.connect(self._size_edited)
        cb.addWidget(self.fit_seg)
        fill_row = QHBoxLayout()
        self.fill_label = self._bind(QLabel(), "fill_color")
        fill_row.addWidget(self.fill_label)
        fill_row.addStretch(1)
        self.fill_combo = FitCombo()
        self.fill_combo.addItem("", "#ffffff")
        self.fill_combo.addItem("", "#000000")
        self.fill_combo.currentIndexChanged.connect(self._size_edited)
        fill_row.addWidget(self.fill_combo)
        self.fill_row_widget = QWidget()
        self.fill_row_widget.setLayout(fill_row)
        cb.addWidget(self.fill_row_widget)
        self.px_label = QLabel()
        self.px_label.setObjectName("hint")
        cb.addWidget(self.px_label)
        c.add(self.custom_box)

        self.orient_seg = Segmented([("auto", ""), ("landscape", ""), ("portrait", "")])
        self.orient_seg.changed.connect(lambda _: self._frame_changed())
        c.add(self.orient_seg)

        r2 = QHBoxLayout()
        r2.setSpacing(6)
        r2.addWidget(self._bind(QLabel(), "rotate"))
        self.rotate_value = QLabel("0°")
        self.rotate_value.setObjectName("sliderValue")
        r2.addWidget(self.rotate_value)
        r2.addStretch(1)
        self.rot_left = icon_button("rot_left", ghost=False)
        self.rot_left.clicked.connect(lambda: self._rotate(-90))
        self.rot_right = icon_button("rot_right", ghost=False)
        self.rot_right.clicked.connect(lambda: self._rotate(90))
        self.mirror_h_btn = icon_button("mirror", ghost=False, checkable=True)
        self._bind(self.mirror_h_btn, "mirror_h", "setToolTip")
        self.mirror_v_btn = AnimatedButton("⇅")
        self.mirror_v_btn.setCheckable(True)
        self.mirror_v_btn.setStyleSheet('font-family: "Segoe UI Symbol"; font-size: 12pt; padding: 3px;')
        self._bind(self.mirror_v_btn, "mirror_v", "setToolTip")
        self._bind(self.rot_left, "rotate_left", "setToolTip")
        self._bind(self.rot_right, "rotate_right", "setToolTip")
        for b in (self.rot_left, self.rot_right, self.mirror_h_btn, self.mirror_v_btn):
            b.setFixedSize(38, 34)
        for b in (self.mirror_h_btn, self.mirror_v_btn):
            b.toggled.connect(lambda _: self._frame_changed())
        for b in (self.rot_left, self.rot_right, self.mirror_h_btn, self.mirror_v_btn):
            r2.addWidget(b)
        c.add(r2)
        self.frame_hint = self._bind(QLabel(), "frame_hint")
        self.frame_hint.setObjectName("hint")
        self.frame_hint.setWordWrap(True)
        c.add(self.frame_hint)
        return c

    def _build_color_column(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("sidebar")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(370)
        scroll.setMaximumWidth(450)
        KeepLayoutFresh(scroll)
        inner = QWidget()
        inner.setObjectName("sidebarInner")
        col = QVBoxLayout(inner)
        col.setContentsMargins(8, 0, 0, 0)
        self.cards["color"] = self._card_color()
        col.addWidget(self.cards["color"])
        col.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _card_color(self) -> Card:
        c = Card()
        self._bind(c.title, "card_color")
        reset = AnimatedButton()
        reset.setObjectName("ghost")
        self._bind(reset, "reset")
        reset.clicked.connect(self._reset_color)
        c.header_tools.addWidget(reset)
        self.scope_seg = Segmented([("all", ""), ("one", "")])
        self.scope_seg.set_value("all")
        self.scope_seg.changed.connect(self._scope_changed)
        c.add(self.scope_seg)
        self.scope_hint = QLabel()
        self.scope_hint.setObjectName("hint")
        self.scope_hint.setWordWrap(True)
        c.add(self.scope_hint)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.apply_all_btn = self._bind(AnimatedButton(), "apply_to_all")
        self.apply_all_btn.clicked.connect(self._apply_to_all)
        actions.addWidget(self.apply_all_btn, 1)
        self.reset_one_btn = AnimatedButton()
        self.reset_one_btn.clicked.connect(self._reset_this)
        actions.addWidget(self.reset_one_btn, 1)
        c.add(actions)
        wb_row = QHBoxLayout()
        wb_row.setSpacing(6)
        self.pipette_btn = AnimatedButton()
        self.pipette_btn.setCheckable(True)
        self._bind(self.pipette_btn, "pipette")
        self._bind(self.pipette_btn, "pipette_tip", "setToolTip")
        self.pipette_btn.toggled.connect(self._pipette_toggled)
        wb_row.addWidget(self.pipette_btn, 1)
        self.wb_reset_btn = self._bind(AnimatedButton(), "wb_reset")
        self.wb_reset_btn.clicked.connect(self._wb_reset)
        wb_row.addWidget(self.wb_reset_btn, 1)
        c.add(wb_row)
        self.wb_label = QLabel()
        self.wb_label.setObjectName("hint")
        c.add(self.wb_label)
        self.sliders: dict[str, SliderRow] = {}
        for key, color in COLOR_SLIDERS:
            s = SliderRow(key, "", minimum=0 if key == "auto" else -100, color=color)
            self._bind(s.label, key)
            s.valueChanged.connect(self._color_changed)
            self.sliders[key] = s
            c.add(s)
        line = QFrame()
        line.setFixedHeight(1)
        line.setObjectName("cardHeader")
        c.add(line)
        for key, color in CHANNEL_SLIDERS:
            s = SliderRow(key, "", color=color)
            self._bind(s.label, key)
            s.valueChanged.connect(self._color_changed)
            self.sliders[key] = s
            c.add(s)
        hint = self._bind(QLabel(), "color_hint")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        c.add(hint)
        return c

    def _build_workspace(self) -> QWidget:
        split = QSplitter(Qt.Orientation.Vertical)
        split.setHandleWidth(10)
        split.setChildrenCollapsible(False)

        frame = QFrame()
        frame.setObjectName("previewFrame")
        v = QVBoxLayout(frame)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.prev_btn = icon_button("prev")
        self.prev_btn.clicked.connect(self.prev_file)
        self.next_btn = icon_button("next")
        self.next_btn.clicked.connect(self.next_file)
        self.file_label = QLabel()
        self.file_label.setObjectName("fileName")
        self.counter_label = QLabel()
        self.counter_label.setObjectName("muted")
        bar.addWidget(self.prev_btn)
        bar.addWidget(self.next_btn)
        bar.addSpacing(6)
        bar.addWidget(self.file_label)
        bar.addWidget(self.counter_label)
        bar.addStretch(1)
        self.edit_pdf_btn = self._bind(AnimatedButton(), "edit_pdf")
        self.edit_pdf_btn.clicked.connect(self.edit_pdf)
        self.edit_pdf_btn.hide()
        bar.addWidget(self.edit_pdf_btn)
        self.undo_edit_btn = self._bind(AnimatedButton(), "undo_edit")
        self.undo_edit_btn.setObjectName("ghost")
        self.undo_edit_btn.clicked.connect(self.drop_pdf_edits)
        self.undo_edit_btn.hide()
        bar.addWidget(self.undo_edit_btn)
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        bar.addWidget(self.size_label)
        self.compare_btn = AnimatedButton()
        self.compare_btn.setCheckable(True)
        self._bind(self.compare_btn, "show_original")
        self._bind(self.compare_btn, "show_original_tip", "setToolTip")
        self.compare_btn.toggled.connect(lambda _: self._schedule_preview())
        bar.addWidget(self.compare_btn)
        self.sheet_view_btn = AnimatedButton()
        self.sheet_view_btn.setCheckable(True)
        self.sheet_view_btn.setChecked(True)
        self._bind(self.sheet_view_btn, "sheet_view")
        self._bind(self.sheet_view_btn, "sheet_view_tip", "setToolTip")
        self.sheet_view_btn.toggled.connect(lambda _: self._schedule_preview())
        self.sheet_view_btn.hide()
        bar.addWidget(self.sheet_view_btn)
        v.addLayout(bar)
        self.canvas = PreviewCanvas(PALETTES[self.theme])
        self.canvas.offsetChanged.connect(self._offset_changed)
        self.canvas.picked.connect(self._pick_white)
        self.canvas.filesDropped.connect(self._dropped)
        v.addWidget(self.canvas, 1)
        split.addWidget(frame)

        bottom = QFrame()
        bottom.setObjectName("previewFrame")
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(8, 2, 8, 8)
        self.tabs = QTabWidget()
        self.file_list = QListWidget()
        self.file_list.currentRowChanged.connect(self._list_selected)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.tabs.addTab(self.file_list, "")
        self.tabs.addTab(self.log_view, "")
        bl.addWidget(self.tabs)
        split.addWidget(bottom)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([560, 200])
        self.work_splitter = split
        return split

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setObjectName("footer")
        h = QHBoxLayout(w)
        h.setContentsMargins(18, 12, 18, 12)
        h.setSpacing(14)
        info = QVBoxLayout()
        info.setSpacing(6)
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        info.addWidget(self.status_label)
        info.addWidget(self.progress)
        h.addLayout(info, 1)
        self.open_result_btn = self._bind(AnimatedButton(), "open_result")
        self.open_result_btn.clicked.connect(self._open_output)
        self.open_result_btn.hide()
        h.addWidget(self.open_result_btn)
        self.stop_btn = self._bind(AnimatedButton(), "stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.hide()
        h.addWidget(self.stop_btn)
        self.print_btn = self._bind(AnimatedButton(), "print")
        self._bind(self.print_btn, "print_tip", "setToolTip")
        self.print_btn.clicked.connect(self.print_files)
        h.addWidget(self.print_btn)
        self.start_btn = self._bind(AnimatedButton(), "convert")
        self.start_btn.setObjectName("primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.start)
        h.addWidget(self.start_btn)
        return w

    # ------------------------------------------------------------------ theme / language
    def _apply_theme(self):
        p = PALETTES[self.theme]
        self.setStyleSheet(stylesheet(p))
        self.title_label.set_colors(p["text"], p["muted"], p["accent_hover"], "#22d3ee")
        self.canvas.set_palette(p)
        self.theme_btn.setText(ICONS["sun"] if self.theme == "dark" else ICONS["moon"])
        for item in self.items.values():
            self._paint_item(item)

    def _toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self._apply_theme()

    def _lang_changed(self):
        self.lang = self.lang_combo.currentData()
        self._retranslate()

    def _retranslate(self):
        for widget, key, method in self._texts:
            getattr(widget, method)(self.t(key))
        self.setWindowTitle(self.t("app_title"))
        for i, k in enumerate(RATIO_KEYS):
            self.ratio_combo.setItemText(i, self.t(f"ratio_{k.replace(':', '_')}"))
        for k in ("auto", "landscape", "portrait"):
            self.orient_seg.set_text(k, self.t(f"orient_{k}"))
        self._update_scope_ui()
        self.fit_seg.set_text("crop", self.t("fit_crop"))
        self.fit_seg.set_text("fit", self.t("fit_fit"))
        self.fill_combo.setItemText(0, self.t("fill_white"))
        self.fill_combo.setItemText(1, self.t("fill_black"))
        self._update_custom_ui()
        for i in range(self.sheet_preset.count()):
            self.sheet_preset.setItemText(i, self.t(f"sheet_preset_{self.sheet_preset.itemData(i)}"))
        self._sheet_changed()
        self.tabs.setTabText(0, self.t("tab_files"))
        self.tabs.setTabText(1, self.t("tab_log"))
        self.canvas.placeholder = self.t("drop_hint")
        self.canvas.update()
        self._update_found_label()
        self._update_nav()
        if not self.thread:
            self.status_label.setText(self.t("ready"))

    # ------------------------------------------------------------------ PDF editor
    _edits_dir: Path | None = None

    def edit_pdf(self):
        key = self._current_key()
        if not key:
            return
        path = Path(key)
        edited = self.settings.replacements.get(key)
        if edited and Path(edited).exists():
            pdf = Path(edited)
        elif path.suffix.lower() == ".pdf":
            pdf = path
        else:
            # Word, PowerPoint, Excel: edit the PDF the office program makes from it.
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                pdf = office.cached_pdf(path)
            except Exception as exc:
                self.status_label.setText(self.t("preview_error", err=str(exc)))
                return
            finally:
                QApplication.restoreOverrideCursor()
        if MainWindow._edits_dir is None:
            import atexit
            import shutil
            import tempfile

            MainWindow._edits_dir = Path(tempfile.mkdtemp(prefix="kt_edits_"))
            atexit.register(shutil.rmtree, MainWindow._edits_dir, True)
        save_to = MainWindow._edits_dir / f"{path.stem}_{len(os.listdir(MainWindow._edits_dir)) + 1}.pdf"
        from .pdf_editor import PdfEditor

        dlg = PdfEditor(self, self.t, pdf, save_to, path.name)
        dlg.setStyleSheet(self.styleSheet())
        dlg.exec()
        if dlg.result:
            self.settings.replacements[key] = str(dlg.result)
            self.log("info", self.t("pdf_edited", name=path.name))
            self._refresh_after_edit(key)

    def drop_pdf_edits(self):
        key = self._current_key()
        if key and self.settings.replacements.pop(key, None):
            self.log("info", self.t("pdf_edits_dropped", name=Path(key).name))
            self._refresh_after_edit(key)

    def _refresh_after_edit(self, key: str):
        self.preview_cache.pop(key, None)
        self.preview_errors.pop(key, None)
        for item in self.items.values():
            if item.data(Qt.ItemDataRole.UserRole + 2) == key:
                self._paint_item(item)
        self._update_nav()
        self._schedule_preview()

    # ------------------------------------------------------------------ helper programs
    def _startup_check(self):
        """First start: show what was found. Later starts: just note it in the log."""
        self.log("info", summary(office.detect(), self.t))
        if self.store.value("programs_checked", "false") != "true":
            self.store.setValue("programs_checked", "true")
            self.show_programs(first_run=True)

    def show_about(self):
        dlg = AboutDialog(self, self.t)
        dlg.setStyleSheet(stylesheet(PALETTES[self.theme]))
        dlg.exec()

    def show_programs(self, first_run: bool = False):
        dlg = ProgramsDialog(self, self.t, first_run)
        dlg.setStyleSheet(stylesheet(PALETTES[self.theme]))
        dlg.exec()
        after = office.detect()
        self.store.setValue("office_engine", office.get_preference())
        self.store.setValue("lo_custom", after.lo_custom or "")
        # Documents that failed (or were opened by another engine) get a fresh preview.
        for key in [k for k in list(self.preview_errors) + list(self.preview_cache)
                    if Path(k).suffix.lower() in office.OFFICE_EXTS]:
            self.preview_errors.pop(key, None)
            self.preview_cache.pop(key, None)
        self._schedule_preview()

    # ------------------------------------------------------------------ settings
    def _load_job_settings(self) -> JobSettings:
        s = JobSettings()
        raw = self.store.value("job")
        if raw:
            try:
                data = json.loads(raw)
                s.color = ColorSettings.from_dict(data.get("color"))
                s.frame = FrameSettings(**{k: v for k, v in data.get("frame", {}).items()
                                           if k in FrameSettings.__dataclass_fields__})
                s.output = OutputSettings(**{k: v for k, v in data.get("output", {}).items()
                                             if k in OutputSettings.__dataclass_fields__})
                s.sheet = SheetSettings(**{k: v for k, v in data.get("sheet", {}).items()
                                           if k in SheetSettings.__dataclass_fields__})
            except Exception:
                pass
        return s

    def _restore_state(self):
        s = self.settings
        self.input_edit.setText(self.store.value("input_dir", r"C:\iccin"))
        self.output_edit.setText(self.store.value("output_dir", r"C:\iccout"))
        self.format_seg.set_value(s.output.fmt)
        self.quality_row.set_value(s.output.quality, silent=True)
        self.quality_row.value_label.setText(str(s.output.quality))
        idx = self.dpi_combo.findData(s.output.dpi)
        self.dpi_combo.setCurrentIndex(idx if idx >= 0 else 2)
        self.keep_structure.setChecked(s.output.keep_structure)
        self.merge_pdf.setChecked(s.output.merge_pdf)
        sh = s.sheet
        widgets = (self.sheet_check, self.sheet_paper, self.sheet_landscape, self.sheet_cols, self.sheet_rows,
                   self.sheet_margin, self.sheet_gap, self.sheet_fill, self.sheet_captions,
                   self.sheet_preset, self.sheet_fixed, self.sheet_pw, self.sheet_ph, self.sheet_copies,
                   self.sheet_rotate, self.sheet_marks)
        for w_ in widgets:
            w_.blockSignals(True)
        self.sheet_check.setChecked(sh.enabled)
        self.sheet_paper.setCurrentIndex(max(0, self.sheet_paper.findData(sh.paper)))
        self.sheet_landscape.setChecked(sh.landscape)
        self.sheet_cols.setValue(sh.cols)
        self.sheet_rows.setValue(sh.rows)
        self.sheet_margin.setValue(sh.margin_mm)
        self.sheet_gap.setValue(sh.gap_mm)
        self.sheet_fill.setChecked(sh.fill)
        self.sheet_captions.setChecked(sh.captions)
        self.sheet_fixed.setChecked(sh.fixed_size)
        if sh.fixed_size:
            self.sheet_pw.setValue(sh.photo_w_cm)
            self.sheet_ph.setValue(sh.photo_h_cm)
        self.sheet_copies.setValue(sh.copies)
        self.sheet_rotate.setChecked(sh.auto_rotate)
        self.sheet_marks.setChecked(sh.cut_marks)
        self.sheet_preset.setCurrentIndex(max(0, self.sheet_preset.findData(sh.preset)))
        for w_ in widgets:
            w_.blockSignals(False)
        self._sheet_changed()
        self.ratio_combo.blockSignals(True)
        self.ratio_combo.setCurrentIndex(max(0, RATIO_KEYS.index(s.frame.ratio) if s.frame.ratio in RATIO_KEYS else 0))
        self.ratio_combo.blockSignals(False)
        for w_ in (self.size_w, self.size_h, self.unit_combo, self.fit_seg, self.fill_combo):
            w_.blockSignals(True)
        self.size_w.setValue(s.frame.size_w)
        self.size_h.setValue(s.frame.size_h)
        self.unit_combo.setCurrentIndex(max(0, self.unit_combo.findData(s.frame.unit)))
        self.fit_seg.set_value("fit" if s.frame.fit else "crop")
        self.fill_combo.setCurrentIndex(max(0, self.fill_combo.findData(s.frame.fill)))
        for w_ in (self.size_w, self.size_h, self.unit_combo, self.fit_seg, self.fill_combo):
            w_.blockSignals(False)
        self.orient_seg.set_value("auto" if s.frame.auto_orient else ("portrait" if s.frame.portrait else "landscape"))
        self.mirror_h_btn.blockSignals(True)
        self.mirror_v_btn.blockSignals(True)
        self.mirror_h_btn.setChecked(s.frame.mirror_h)
        self.mirror_v_btn.setChecked(s.frame.mirror_v)
        self.mirror_h_btn.blockSignals(False)
        self.mirror_v_btn.blockSignals(False)
        for k, row in self.sliders.items():
            row.set_value(getattr(s.color, k), silent=True)
        self._format_changed(s.output.fmt, save=False)
        self._update_rotate_label()
        geo = self.store.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1360, 860)
        for key, card in self.cards.items():
            card.set_collapsed(self.store.value(f"collapsed_{key}", "false") == "true")

    def _collect_settings(self):
        s = self.settings
        s.output.fmt = self.format_seg.value()
        s.output.quality = self.quality_row.value()
        s.output.dpi = int(self.dpi_combo.currentData())
        s.output.keep_structure = self.keep_structure.isChecked()
        s.output.merge_pdf = self.merge_pdf.isChecked()
        s.frame.ratio = self.ratio_combo.currentData()
        o = self.orient_seg.value()
        s.frame.auto_orient = o == "auto"
        s.frame.portrait = o == "portrait"
        s.frame.mirror_h = self.mirror_h_btn.isChecked()
        s.frame.mirror_v = self.mirror_v_btn.isChecked()
        s.frame.size_w = self.size_w.value()
        s.frame.size_h = self.size_h.value()
        s.frame.unit = self.unit_combo.currentData()
        s.frame.fit = self.fit_seg.value() == "fit"
        s.frame.fill = self.fill_combo.currentData()
        sh = s.sheet
        sh.enabled = self.sheet_check.isChecked()
        sh.paper = self.sheet_paper.currentData()
        sh.landscape = self.sheet_landscape.isChecked()
        sh.cols, sh.rows = self.sheet_cols.value(), self.sheet_rows.value()
        sh.margin_mm, sh.gap_mm = self.sheet_margin.value(), self.sheet_gap.value()
        sh.fill = self.sheet_fill.isChecked()
        sh.captions = self.sheet_captions.isChecked()
        fixed = self.sheet_fixed.isChecked()
        sh.photo_w_cm = self.sheet_pw.value() if fixed else 0.0
        sh.photo_h_cm = self.sheet_ph.value() if fixed else 0.0
        sh.copies = self.sheet_copies.value()
        sh.auto_rotate = self.sheet_rotate.isChecked()
        sh.cut_marks = self.sheet_marks.isChecked()
        sh.preset = self.sheet_preset.currentData() or "custom"

    def _save_state(self):
        self._collect_settings()
        s = self.settings
        self.store.setValue("job", json.dumps({
            "color": s.color.to_dict(), "frame": asdict(s.frame), "output": asdict(s.output),
            "sheet": asdict(s.sheet),
        }))
        self.store.setValue("input_dir", self.input_edit.text())
        self.store.setValue("output_dir", self.output_edit.text())
        self.store.setValue("lang", self.lang)
        self.store.setValue("theme", self.theme)
        self.store.setValue("geometry", self.saveGeometry())
        for key, card in self.cards.items():
            self.store.setValue(f"collapsed_{key}", "true" if card.is_collapsed() else "false")

    def closeEvent(self, e):
        if self.thread and self.thread.isRunning():
            self.thread.batch.stop()
            self.thread.wait(5000)
        self._save_state()
        super().closeEvent(e)

    # ------------------------------------------------------------------ sources
    def _folder_edited(self):
        """A folder typed in by hand replaces any files picked earlier; an untouched field changes nothing."""
        if self.input_edit.text().strip() != self._folder_text:
            self.extra_files.clear()
            self.rescan()

    def _browse_input(self):
        d = QFileDialog.getExistingDirectory(self, self.t("card_source"), self.input_edit.text())
        if d:
            self.extra_files.clear()   # the newly chosen folder is now the only source
            self.input_edit.setText(os.path.normpath(d))
            self.rescan()

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, self.t("card_output"), self.output_edit.text())
        if d:
            self.output_edit.setText(os.path.normpath(d))

    def _add_files_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS | ARCHIVE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, self.t("add_files"), "", f"{self.t('supported')} ({exts})")
        if files:
            self._add_paths(files)

    def _add_paths(self, paths):
        for p in map(Path, paths):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS | ARCHIVE_EXTS and p not in self.extra_files:
                self.extra_files.append(p)
        self.rescan()

    def _dropped(self, paths):
        folders = [p for p in paths if Path(p).is_dir()]
        if folders:
            self.extra_files.clear()
            self.input_edit.setText(os.path.normpath(folders[0]))
        self._add_paths([p for p in paths if Path(p).is_file()])
        if folders and not [p for p in paths if Path(p).is_file()]:
            self.rescan()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._dropped([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def _clear_extra(self):
        self.extra_files.clear()
        self.rescan()

    def rescan(self):
        keep = self.sources[self.current].path if 0 <= self.current < len(self.sources) else None
        self._folder_text = self.input_edit.text().strip()
        folder = Path(self._folder_text) if self._folder_text else None
        # Files picked by hand replace the folder: its documents are not processed.
        sources = [] if self.extra_files else (scan_folder(folder) if folder else [])
        known = {s.path for s in sources}
        sources += [SourceFile(p) for p in self.extra_files if p not in known]
        self.sources = sources
        self.file_list.blockSignals(True)
        self.file_list.clear()
        self.items.clear()
        for src in sources:
            item = QListWidgetItem(src.label)
            item.setData(Qt.ItemDataRole.UserRole, "pending")
            item.setData(Qt.ItemDataRole.UserRole + 2, str(src.path))
            self.items[src.label] = item
            self._paint_item(item)
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)
        idx = next((i for i, s in enumerate(sources) if s.path == keep), 0 if sources else -1)
        self._update_found_label()
        self.show_file(idx)

    def _update_found_label(self):
        n = len(self.sources)
        arch = sum(1 for s in self.sources if s.path.suffix.lower() in ARCHIVE_EXTS)
        text = self.t("found", n=n)
        if arch:
            text += " · " + self.t("archives", n=arch)
        if self.extra_files:
            text = self.t("only_chosen", n=n)
        self.found_label.setText(text)

    def _paint_item(self, item: QListWidgetItem):
        p = PALETTES[self.theme]
        state = item.data(Qt.ItemDataRole.UserRole)
        color = {"ok": p["success"], "error": p["error"]}.get(state, p["text"])
        item.setForeground(QColor(color))
        prefix = {"ok": "✓  ", "error": "✕  "}.get(state, "")
        base = item.data(Qt.ItemDataRole.UserRole + 1) or item.text()
        item.setData(Qt.ItemDataRole.UserRole + 1, base)
        edited = item.data(Qt.ItemDataRole.UserRole + 2) in self.settings.replacements
        item.setText(prefix + base + ("  ✎" if edited else ""))

    # ------------------------------------------------------------------ navigation & preview
    def _list_selected(self, row: int):
        if row != self.current:
            self.show_file(row)

    def prev_file(self):
        if self.current > 0:
            self.show_file(self.current - 1)

    def next_file(self):
        if self.current < len(self.sources) - 1:
            self.show_file(self.current + 1)

    def show_file(self, idx: int):
        self.current = idx
        self._update_nav()
        if hasattr(self, "scope_seg"):
            self._load_sliders()
        if idx < 0:
            self.canvas.set_image(None)
            return
        self.file_list.blockSignals(True)
        self.file_list.setCurrentRow(idx)
        self.file_list.blockSignals(False)
        self._schedule_preview()

    def _update_nav(self):
        n = len(self.sources)
        has = 0 <= self.current < n
        ext = self.sources[self.current].path.suffix.lower() if has else ""
        editable = ext == ".pdf" or ext in office.OFFICE_EXTS
        can = office.detect().pymupdf
        self.edit_pdf_btn.setVisible(editable)
        self.edit_pdf_btn.setEnabled(can)
        self.edit_pdf_btn.setToolTip(self.t("edit_pdf_tip") if can else self.t("edit_pdf_missing"))
        self.undo_edit_btn.setVisible(has and str(self.sources[self.current].path) in self.settings.replacements)
        self.prev_btn.setEnabled(has and self.current > 0)
        self.next_btn.setEnabled(has and self.current < n - 1)
        self.file_label.setText(self.sources[self.current].label if has else self.t("no_files"))
        self.counter_label.setText(f"{self.current + 1} / {n}" if has else "")
        if not has:
            self.size_label.setText("")

    def _schedule_preview(self):
        self._preview_timer.start()

    def _render_preview(self):
        if not (0 <= self.current < len(self.sources)):
            self.canvas.set_image(None)
            return
        if self._render_sheet_preview():
            return
        src = self.sources[self.current]
        key = str(src.path)
        if src.path.suffix.lower() in ARCHIVE_EXTS:
            self.canvas.set_image(None)
            self.canvas.set_message(self.t("archive_preview"))
            self.size_label.setText("")
            return
        if key in self.preview_errors:
            self.canvas.set_image(None)
            self.canvas.set_message(self.t("preview_error", err=self.preview_errors[key]))
            return
        base = self.preview_cache.get(key)
        if base is None:
            if key not in self.pending_previews:
                self.pending_previews.add(key)
                edited = self.settings.replacements.get(key)
                job = PreviewJob(src.path, Path(edited) if edited else None)
                job.signals.done.connect(self._preview_loaded)
                self.pool.start(job)
            if not self.canvas.image:
                self.canvas.set_message(self.t("loading"))
            return
        self.preview_cache.move_to_end(key)
        self._collect_settings()
        s = self.settings
        photo = is_photo(src.path)
        frame = s.frame if photo else FrameSettings(rotate=s.frame.rotate, mirror_h=s.frame.mirror_h, mirror_v=s.frame.mirror_v)
        img = orient(base, frame)
        if not self.compare_btn.isChecked():
            img = apply_color(img, s.color_for(key))
        crop = None
        self._content_box = (0.0, 0.0, 1.0, 1.0)
        offset = s.offsets.get(key, (0.0, 0.0))
        if photo and frame.ratio == "custom" and frame.fit and ratio_pair(frame):
            img, self._content_box = fit_pad(img, frame)
        box = crop_box(img.size, frame, offset)
        if box and box != (0, 0, *img.size):
            w, h = img.size
            crop = (box[0] / w, box[1] / h, box[2] / w, box[3] / h)
        self.canvas.set_image(pil_to_qimage(img), crop, offset)
        self.size_label.setText(f"{base.width}×{base.height}" if photo else "")

    def _preview_loaded(self, key: str, img, err: str):
        self.pending_previews.discard(key)
        if img is None:
            self.preview_errors[key] = err
        else:
            self.preview_cache[key] = img
            while len(self.preview_cache) > 30:
                self.preview_cache.popitem(last=False)
        if 0 <= self.current < len(self.sources) and (
                str(self.sources[self.current].path) == key or self.sheet_check.isChecked()):
            self._render_preview()

    # ------------------------------------------------------------------ setting changes
    # ---- colour: global settings plus optional per-photo overrides
    def _current_key(self) -> str | None:
        return str(self.sources[self.current].path) if 0 <= self.current < len(self.sources) else None

    _wb = (1.0, 1.0, 1.0)  # white balance of whatever the sliders currently edit

    def _slider_values(self) -> ColorSettings:
        c = ColorSettings(**{k: row.value() for k, row in self.sliders.items()})
        c.wb = self._wb
        return c

    def _load_sliders(self):
        """Show the colour that applies to the current photo (or the global one)."""
        key = self._current_key()
        if self.scope_seg.value() == "one" and key:
            c = self.settings.color_for(key)
        else:
            c = self.settings.color
        for k, row in self.sliders.items():
            row.set_value(getattr(c, k), silent=True)
        self._wb = tuple(c.wb)
        self._update_scope_ui()

    def _update_scope_ui(self):
        one = self.scope_seg.value() == "one"
        n = len(self.settings.color_overrides)
        key = self._current_key()
        has = bool(key and key in self.settings.color_overrides)
        self.scope_hint.setText(self.t("scope_hint_one" if one else "scope_hint_all", n=n))
        self.apply_all_btn.setVisible(one)
        self.reset_one_btn.setVisible(one or n > 0)
        self.reset_one_btn.setText(self.t("reset_this") if one else self.t("reset_individual", n=n))
        self.reset_one_btn.setEnabled(has if one else n > 0)
        neutral = tuple(self._wb) == (1.0, 1.0, 1.0)
        self.wb_label.setText(self.t("wb_none") if neutral else self.t("wb_set"))
        self.wb_reset_btn.setEnabled(not neutral)
        self.scope_seg.set_text("all", self.t("scope_all"))
        self.scope_seg.set_text("one", self.t("scope_one"))

    def _scope_changed(self, _=None):
        self._load_sliders()
        self._schedule_preview()

    def _color_changed(self, *_):
        c = self._slider_values()
        key = self._current_key()
        if self.scope_seg.value() == "one" and key:
            if c == self.settings.color:
                self.settings.color_overrides.pop(key, None)
            else:
                self.settings.color_overrides[key] = c
        else:
            self.settings.color = c
        self._update_scope_ui()
        self._schedule_preview()

    # ---- white balance pipette
    def _pipette_toggled(self, on: bool):
        self.canvas.set_pick_mode(on)

    def _pick_white(self, nx: float, ny: float):
        key = self._current_key()
        base = self.preview_cache.get(key) if key else None
        if base is None:
            return
        self._collect_settings()
        img = orient(base, self.settings.frame)
        w, h = img.size
        bx0, by0, bx1, by1 = getattr(self, "_content_box", (0.0, 0.0, 1.0, 1.0))
        nx, ny = (nx - bx0) / (bx1 - bx0), (ny - by0) / (by1 - by0)  # skip the padding
        if not (0 <= nx <= 1 and 0 <= ny <= 1):
            return
        x, y = min(w - 1, max(0, int(nx * w))), min(h - 1, max(0, int(ny * h)))
        r = max(2, min(w, h) // 200)
        box = img.crop((max(0, x - r), max(0, y - r), min(w, x + r + 1), min(h, y + r + 1))).resize((1, 1), Image.Resampling.BOX)
        self._wb = white_balance_from_pixel(box.getpixel((0, 0)))
        self.pipette_btn.setChecked(False)
        self._color_changed()

    def _wb_reset(self):
        self._wb = (1.0, 1.0, 1.0)
        self._color_changed()

    def _apply_to_all(self):
        """Make the current photo's colour the setting for every photo."""
        self.settings.color = self._slider_values()
        self.settings.color_overrides.clear()
        self._update_scope_ui()
        self._schedule_preview()

    def _reset_this(self):
        if self.scope_seg.value() == "one":
            key = self._current_key()
            if key:
                self.settings.color_overrides.pop(key, None)
        else:
            self.settings.color_overrides.clear()
        self._load_sliders()
        self._schedule_preview()

    def _reset_color(self):
        self._wb = (1.0, 1.0, 1.0)
        zero = ColorSettings()
        key = self._current_key()
        if self.scope_seg.value() == "one" and key:
            if zero == self.settings.color:
                self.settings.color_overrides.pop(key, None)
            else:
                self.settings.color_overrides[key] = zero
        else:
            self.settings.color = zero
        self._load_sliders()
        self._schedule_preview()

    def _sheet_preset_chosen(self, *_):
        key = self.sheet_preset.currentData()
        if key and key != "custom":
            tmp = SheetSettings()
            apply_preset(tmp, key)
            widgets = (self.sheet_paper, self.sheet_landscape, self.sheet_cols, self.sheet_rows, self.sheet_margin,
                       self.sheet_gap, self.sheet_fill, self.sheet_captions, self.sheet_fixed, self.sheet_pw,
                       self.sheet_ph, self.sheet_copies, self.sheet_marks)
            for w_ in widgets:
                w_.blockSignals(True)
            self.sheet_paper.setCurrentIndex(max(0, self.sheet_paper.findData(tmp.paper)))
            self.sheet_landscape.setChecked(tmp.landscape)
            self.sheet_cols.setValue(tmp.cols if not tmp.fixed_size else self.sheet_cols.value())
            self.sheet_rows.setValue(tmp.rows if not tmp.fixed_size else self.sheet_rows.value())
            self.sheet_margin.setValue(tmp.margin_mm)
            self.sheet_gap.setValue(tmp.gap_mm)
            self.sheet_fill.setChecked(tmp.fill)
            self.sheet_captions.setChecked(tmp.captions)
            self.sheet_fixed.setChecked(tmp.fixed_size)
            if tmp.fixed_size:
                self.sheet_pw.setValue(tmp.photo_w_cm)
                self.sheet_ph.setValue(tmp.photo_h_cm)
            self.sheet_copies.setValue(tmp.copies)
            self.sheet_marks.setChecked(tmp.cut_marks)
            for w_ in widgets:
                w_.blockSignals(False)
        self._sheet_changed()

    def _sheet_edited(self, *_):
        """A manual change: the layout is no longer exactly a ready preset."""
        if hasattr(self, "sheet_preset") and self.sheet_preset.currentData() != "custom":
            self.sheet_preset.blockSignals(True)
            self.sheet_preset.setCurrentIndex(0)
            self.sheet_preset.blockSignals(False)
        self._sheet_changed()

    def _photo_sources(self) -> list[SourceFile]:
        return [x for x in self.sources if is_photo(x.path) and x.path.suffix.lower() not in ARCHIVE_EXTS]

    def _sheet_changed(self, *_):
        if not hasattr(self, "sheet_hint"):
            return  # widgets are still being created
        on = self.sheet_check.isChecked()
        self.sheet_box.setVisible(on)
        self.sheet_view_btn.setVisible(on)
        self.keep_structure.setEnabled(not on)
        fixed = self.sheet_fixed.isChecked()
        for w_ in (self.sheet_cols, self.sheet_rows, self.sheet_grid_label):
            w_.setEnabled(not fixed)
        for w_ in (self.sheet_pw, self.sheet_ph):
            w_.setEnabled(fixed)
        self._collect_settings()
        sh = self.settings.sheet
        n = sh.per_sheet
        photos = len(self._photo_sources())
        total = photos * (sh.copies or n)
        sheets = -(-total // n) if photos else 0
        self.sheet_hint.setText(self.t("sheet_hint", n=n, sheets=sheets))
        self.sheet_copies.setSpecialValueText(self.t("sheet_copies_fill"))
        self._schedule_preview()

    # ---- preview of the finished sheet
    def _render_sheet_preview(self) -> bool:
        """Show the sheet that holds the current photo. False: not applicable, show the plain preview."""
        if not (self.sheet_check.isChecked() and self.sheet_view_btn.isChecked()):
            return False
        photos = self._photo_sources()
        cur = self.sources[self.current] if 0 <= self.current < len(self.sources) else None
        if not photos or cur is None:
            return False
        if cur not in photos:
            cur = photos[0]
        self._collect_settings()
        s = self.settings
        sh = s.sheet
        dpi = 100
        _, cell, cells = geometry(sh, dpi)
        per = len(cells)
        n = sh.copies or per
        order = [x for x in photos for _ in range(n)]
        total = -(-len(order) // per)
        start = (order.index(cur) // per) * per
        chunk = order[start:start + per]
        missing = False
        for src in {x.path: x for x in chunk}.values():
            key = str(src.path)
            if key in self.preview_cache or key in self.preview_errors:
                continue
            missing = True
            if key not in self.pending_previews:
                self.pending_previews.add(key)
                edited = s.replacements.get(key)
                job = PreviewJob(src.path, Path(edited) if edited else None)
                job.signals.done.connect(self._preview_loaded)
                self.pool.start(job)
        if missing:
            if not self.canvas.image:
                self.canvas.set_message(self.t("loading"))
            return True
        area = photo_area(sh, cell, dpi)
        made: dict[str, tuple[str, object]] = {}
        items = []
        for src in chunk:
            key = str(src.path)
            if key not in made:
                base = self.preview_cache.get(key)
                if base is None:
                    made[key] = (src.path.stem, Image.new("RGB", (1, 1), "#dddddd"))
                else:
                    img = apply_frame(base, s.frame, s.offsets.get(key, (0.0, 0.0)))
                    if not self.compare_btn.isChecked():
                        img = apply_color(img, s.color_for(key))
                    made[key] = (src.path.stem, fit_photo(img, area, sh))
            items.append(made[key])
        page = compose(items, replace(sh, copies=1), dpi)[0]
        draw = ImageDraw.Draw(page)
        cw, ch = cell
        for x, y in cells[len(items):]:
            draw.rectangle([x, y, x + cw - 1, y + ch - 1], outline="#cfcfcf")
        self._content_box = (0.0, 0.0, 1.0, 1.0)
        self.canvas.set_image(pil_to_qimage(page))
        self.size_label.setText(self.t("sheet_view_info", i=start // per + 1, n=total, k=len(items), per=per))
        return True

    def _ratio_changed(self, *_):
        self._update_custom_ui()
        self._schedule_preview()

    def _preset_chosen(self, *_):
        data = self.preset_combo.currentData()
        if not data:
            return
        w_, h_, u_ = data
        for sp in (self.size_w, self.size_h, self.unit_combo):
            sp.blockSignals(True)
        self.size_w.setValue(w_)
        self.size_h.setValue(h_)
        self.unit_combo.setCurrentIndex(self.unit_combo.findData(u_))
        for sp in (self.size_w, self.size_h, self.unit_combo):
            sp.blockSignals(False)
        self._update_custom_ui()
        self._schedule_preview()

    def _size_edited(self, *_):
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)
        self._update_custom_ui()
        self._schedule_preview()

    def _update_custom_ui(self):
        custom = self.ratio_combo.currentData() == "custom"
        self.custom_box.setVisible(custom)
        self.fill_row_widget.setVisible(custom and self.fit_seg.value() == "fit")
        if custom:
            from core.imaging import UNIT_TO_INCH

            dpi = int(self.dpi_combo.currentData())
            k = UNIT_TO_INCH.get(self.unit_combo.currentData(), 1 / 2.54) * dpi
            a, b = sorted((round(self.size_w.value() * k), round(self.size_h.value() * k)), reverse=True)
            self.px_label.setText(self.t("size_px", w=a, h=b, dpi=dpi))

    def _frame_changed(self, *_):
        self._schedule_preview()

    def _rotate(self, delta: int):
        self.settings.frame.rotate = (self.settings.frame.rotate + delta) % 360
        self._update_rotate_label()
        self._schedule_preview()

    def _update_rotate_label(self):
        self.rotate_value.setText(f"{self.settings.frame.rotate}°")

    def _offset_changed(self, x: float, y: float):
        if 0 <= self.current < len(self.sources):
            key = str(self.sources[self.current].path)
            if abs(x) < 1e-3 and abs(y) < 1e-3:
                self.settings.offsets.pop(key, None)
            else:
                self.settings.offsets[key] = (x, y)

    def _format_changed(self, fmt: str, save: bool = True):
        self.quality_row.setVisible(fmt == "JPEG")
        self.merge_pdf.setVisible(fmt == "PDF")
        self.pdf_hint.setVisible(fmt == "PDF")

    def _open_output(self):
        out = Path(self.output_edit.text().strip())
        if out.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    # ------------------------------------------------------------------ conversion
    def log(self, level: str, msg: str):
        mark = {"ok": "✓", "error": "✕", "info": "•"}.get(level, "•")
        self.log_view.appendPlainText(f"{mark} {msg}")

    def _file_done(self, label: str, ok: bool, info: str):
        # Files from an archive report as "archive › inner"; they mark the archive row.
        item = self.items.get(label) or self.items.get(label.split(" › ")[0])
        if item is None:
            return
        if ok and item.data(Qt.ItemDataRole.UserRole) == "error":
            return
        item.setData(Qt.ItemDataRole.UserRole, "ok" if ok else "error")
        item.setToolTip(info if not ok else "")
        self._paint_item(item)

    def start(self):
        if self.thread:
            return
        if not self.sources:
            self.status_label.setText(self.t("nothing_to_do"))
            return
        out = self.output_edit.text().strip()
        if not out:
            self.status_label.setText(self.t("need_output"))
            self.output_edit.setFocus()
            return
        out_path = Path(out)
        try:
            out_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.status_label.setText(self.t("output_error", err=str(exc)))
            return
        self._save_state()
        for item in self.items.values():
            item.setData(Qt.ItemDataRole.UserRole, "pending")
            self._paint_item(item)
        batch = Batch(list(self.sources), out_path, copy.deepcopy(self.settings))
        self.thread = ConvertThread(batch)
        self.thread.progress.connect(self._progress)
        self.thread.log.connect(self.log)
        self.thread.file_done.connect(self._file_done)
        self.thread.result.connect(self._finished)
        self.log_view.appendPlainText("")
        self.log("info", self.t("log_start", n=len(self.sources), out=str(out_path)))
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.stop_btn.show()
        self.open_result_btn.hide()
        self.status_label.setText(self.t("working"))
        self.thread.start()

    def print_files(self):
        if not self.sources:
            self.status_label.setText(self.t("nothing_to_do"))
            return
        from .printing import run_print

        self._collect_settings()
        cur = self.sources[self.current].path if 0 <= self.current < len(self.sources) else None
        has_current = bool(cur and cur.suffix.lower() not in ARCHIVE_EXTS)
        run_print(self, [s.path for s in self.sources], copy.deepcopy(self.settings),
                  dict(self.settings.replacements), has_current, cur)

    def stop(self):
        if self.thread:
            self.thread.batch.stop()
            self.stop_btn.setEnabled(False)
            self.status_label.setText(self.t("stopping"))

    def _progress(self, done: int, total: int, name: str):
        self.progress.setValue(int(done * 100 / total) if total else 0)
        if name:
            self.status_label.setText(self.t("progress", done=done, total=total, name=name))

    def _finished(self, res: BatchResult):
        self.thread.wait()
        self.thread = None
        self.start_btn.setEnabled(True)
        self.stop_btn.hide()
        self.stop_btn.setEnabled(True)
        self.progress.setValue(100 if not res.cancelled else self.progress.value())
        key = "done_cancelled" if res.cancelled else ("done_errors" if res.failed else "done_ok")
        text = self.t(key, ok=res.converted, pages=res.pages, err=len(res.failed))
        self.status_label.setText(text)
        self.log("info", text)
        if res.failed:
            self.tabs.setCurrentIndex(1)
        if res.pages:
            self.open_result_btn.show()
        QApplication.alert(self)

