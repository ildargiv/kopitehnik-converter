"""Precise crop on a big screen: the photo fills the window, zoom and pan, frame by mouse, arrows or numbers."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from .widgets import PreviewCanvas


class CropDialog(QDialog):
    """Edits one frame of one photo. ``crop`` (normalised x0, y0, x1, y1) holds the result after OK."""

    def __init__(self, parent, t, palette: dict, image: QImage, crop, lock: float | None):
        super().__init__(parent)
        self.t = t
        self.setWindowTitle(t("crop_big_title"))
        self.crop = tuple(crop) if crop else (0.0, 0.0, 1.0, 1.0)
        self._had_crop = bool(crop)
        self.iw, self.ih = image.width(), image.height()
        self._lock = lock
        self._busy = False

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        self.hint = QLabel(t("crop_big_hint"))
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        self.canvas = PreviewCanvas(palette)
        self.canvas.zoom_enabled = True
        self.canvas.set_image(image, tuple(crop) if crop else None, (0.0, 0.0))
        self.canvas.set_edit(True, lock)
        self.canvas.cropEdited.connect(self._edited)
        v.addWidget(self.canvas, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.spins = {}
        for key, label in (("x", "X"), ("y", "Y"), ("w", t("crop_w")), ("h", t("crop_h"))):
            bar.addWidget(QLabel(label))
            sp = QSpinBox()
            sp.setRange(0, 1_000_000)
            sp.setSuffix(" px")
            sp.setMinimumWidth(96)
            sp.valueChanged.connect(self._typed)
            bar.addWidget(sp)
            self.spins[key] = sp
        if lock is not None:
            self.spins["h"].setEnabled(False)       # the format keeps the shape: height follows the width
        self.zoom_label = QLabel()
        bar.addSpacing(12)
        bar.addWidget(self.zoom_label)
        bar.addStretch(1)
        fit = QPushButton(t("crop_fit"))
        fit.clicked.connect(self._fit)
        bar.addWidget(fit)
        cancel = QPushButton(t("cancel"))
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        ok = QPushButton(t("crop_ok"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        bar.addWidget(ok)
        v.addLayout(bar)
        self._show_numbers()
        self.canvas.zoomChanged.connect(self._zoom_changed)
        self._zoom_changed(1.0)

    def showEvent(self, e):
        super().showEvent(e)
        self.canvas.setFocus()

    # ------------------------------------------------------------------ numbers
    def _px(self):
        x0, y0, x1, y1 = self.canvas.crop or (0.0, 0.0, 1.0, 1.0)
        return (round(x0 * self.iw), round(y0 * self.ih), round((x1 - x0) * self.iw), round((y1 - y0) * self.ih))

    def _show_numbers(self):
        self._busy = True
        try:
            for k, val in zip("xywh", self._px()):
                self.spins[k].setValue(val)
            self.spins["x"].setMaximum(self.iw)
            self.spins["y"].setMaximum(self.ih)
            self.spins["w"].setRange(1, self.iw)
            self.spins["h"].setRange(1, self.ih)
        finally:
            self._busy = False

    def _edited(self, *_):
        self._show_numbers()

    def _typed(self, _):
        if self._busy:
            return
        x, y = self.spins["x"].value(), self.spins["y"].value()
        w, h = self.spins["w"].value(), self.spins["h"].value()
        if self._lock is not None:
            h = max(1, round(w / self._lock))
        w, h = min(w, self.iw), min(h, self.ih)
        x, y = min(x, self.iw - w), min(y, self.ih - h)
        self.canvas.crop = (x / self.iw, y / self.ih, (x + w) / self.iw, (y + h) / self.ih)
        self.canvas.update()
        self._show_numbers()

    # ------------------------------------------------------------------ view
    def _fit(self):
        self.canvas.reset_view()

    def _zoom_changed(self, z: float):
        self.zoom_label.setText(f"{round(z * 100)}%")

    def accept(self):
        self.crop = tuple(self.canvas.crop or (0.0, 0.0, 1.0, 1.0))
        super().accept()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(e)
