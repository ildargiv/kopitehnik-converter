"""Reusable widgets: cards, segmented control, slider rows and the preview canvas."""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from .theme import ICON_FONT, ICONS

ACCENT = QColor("#7c5cff")
ACCENT2 = QColor("#22d3ee")


class AnimatedButton(QPushButton):
    """A button with a soft glow and a light that follows the cursor, a ripple on click and,
    for the main (primary) button, a slow breathing glow with a shine sweeping across it."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._hover = 0.0
        self._breath = 0.0
        self._sweep = -1.0
        self._mouse = QPointF(-1, -1)
        self._ripples: list[tuple[QPointF, QVariantAnimation]] = []
        self.setMouseTracking(True)
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 0))
        self.setGraphicsEffect(self._glow)

        self._hover_anim = QVariantAnimation(self, duration=200, startValue=0.0, endValue=1.0)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover)
        self._breath_anim = QVariantAnimation(self, duration=2600, startValue=0.0, endValue=1.0, loopCount=-1)
        self._breath_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._breath_anim.valueChanged.connect(self._set_breath)
        self._sweep_anim = QVariantAnimation(self, duration=900, startValue=-0.4, endValue=1.4)
        self._sweep_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._sweep_anim.valueChanged.connect(self._set_sweep)
        self._sweep_anim.finished.connect(lambda: self._set_sweep(-1.0))
        self._sweep_timer = QTimer(self, interval=4800)
        self._sweep_timer.timeout.connect(self._start_sweep)

    # -------------------------------------------------------------- state
    def _primary(self) -> bool:
        return self.objectName() == "primary"

    def _live(self) -> bool:
        return self.isEnabled() and self.isVisible()

    def _refresh_idle(self):
        if self._primary() and self._live():
            if self._breath_anim.state() != QVariantAnimation.State.Running:
                self._breath_anim.start()
            if not self._sweep_timer.isActive():
                self._sweep_timer.start()
                QTimer.singleShot(900, self._start_sweep)
        else:
            self._breath_anim.stop()
            self._sweep_timer.stop()
            self._sweep_anim.stop()
            self._breath = 0.0
            self._sweep = -1.0
        self._update_glow()

    def _start_sweep(self):
        if self._live() and self._primary() and self._sweep_anim.state() != QVariantAnimation.State.Running:
            self._sweep_anim.start()

    def _set_hover(self, v):
        self._hover = float(v)
        self._update_glow()
        self.update()

    def _set_breath(self, v):
        v = float(v)
        self._breath = 1 - abs(2 * v - 1)   # 0 -> 1 -> 0 over one cycle
        self._update_glow()

    def _set_sweep(self, v):
        self._sweep = float(v)
        self.update()

    def _update_glow(self):
        if not self.isEnabled():
            self._glow.setBlurRadius(0)
            return
        base = 0.45 if self._primary() else 0.0
        strength = base * (0.45 + 0.55 * self._breath) + self._hover * (0.55 if self._primary() else 0.4)
        self._glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), int(255 * min(1.0, strength))))
        self._glow.setBlurRadius(strength * 34)

    # -------------------------------------------------------------- events
    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_idle()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._refresh_idle()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.EnabledChange:
            self._refresh_idle()

    def enterEvent(self, e):
        super().enterEvent(e)
        self._hover_anim.setDirection(QVariantAnimation.Direction.Forward)
        self._hover_anim.start()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._hover_anim.setDirection(QVariantAnimation.Direction.Backward)
        self._hover_anim.start()

    def mouseMoveEvent(self, e):
        self._mouse = e.position()
        if self._hover > 0:
            self.update()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._add_ripple(e.position())
        super().mousePressEvent(e)

    def _add_ripple(self, pos: QPointF):
        anim = QVariantAnimation(self, duration=620, startValue=0.0, endValue=1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        entry = (pos, anim)
        anim.valueChanged.connect(lambda _v: self.update())

        def done():
            if entry in self._ripples:
                self._ripples.remove(entry)
            anim.deleteLater()
            self.update()

        anim.finished.connect(done)
        self._ripples.append(entry)
        anim.start()

    # -------------------------------------------------------------- painting
    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.isEnabled():
            return
        w, h = self.width(), self.height()
        r = 10.0 if self._primary() else 8.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.setClipPath(clip)
        if self._hover > 0.001:   # light under the cursor
            c = self._mouse if self._mouse.x() >= 0 else QPointF(w / 2, h / 2)
            g = QRadialGradient(c, max(w, h) * 0.8)
            tone = QColor(255, 255, 255) if self._primary() else QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue())
            top = QColor(tone)
            top.setAlpha(int((70 if self._primary() else 55) * self._hover))
            end = QColor(tone)
            end.setAlpha(0)
            g.setColorAt(0, top)
            g.setColorAt(1, end)
            p.fillRect(self.rect(), g)
        if self._sweep > -0.9:   # shine across the main button
            x = self._sweep * w
            g = QLinearGradient(x - w * 0.18, 0, x + w * 0.18, h * 0.6)
            clear, shine = QColor(255, 255, 255, 0), QColor(255, 255, 255, 80)
            g.setColorAt(0, clear)
            g.setColorAt(0.5, shine)
            g.setColorAt(1, clear)
            p.fillRect(self.rect(), g)
        for pos, anim in self._ripples:
            t = float(anim.currentValue() or 0.0)
            rad = max(w, h) * 1.15 * t
            col = QColor(255, 255, 255) if self._primary() else QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue())
            col.setAlpha(int(110 * (1 - t)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(pos, rad, rad)
        p.end()


class FitCombo(QComboBox):
    """A combo box that never forces its column wider than the window, but lists items in full."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)

    def showPopup(self):
        fm = self.fontMetrics()
        widest = max((fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        self.view().setMinimumWidth(max(self.width(), widest + 48))
        super().showPopup()


class KeepLayoutFresh(QObject):
    """Qt can leave a scroll area's content at a stale size after a card is folded or a block of
    options is shown or hidden, so the column ends up cut off. After any such change inside the
    area, the layouts are recalculated and the content is fitted to the viewport width."""

    def __init__(self, area: QScrollArea):
        super().__init__(area)
        self.area = area
        self._timer = QTimer(self, singleShot=True, interval=0)
        self._timer.timeout.connect(self.refresh)
        self._viewport = area.viewport()
        self._app = QApplication.instance()
        self._app.installEventFilter(self)
        area.destroyed.connect(self._detach)
        QTimer.singleShot(0, self.refresh)

    def _detach(self, *_):
        self._app.removeEventFilter(self)
        self._alive = False

    _alive = True

    def eventFilter(self, obj, ev):
        if not self._alive:
            return False
        t = ev.type()
        if obj is self._viewport:
            if t == QEvent.Type.Resize:
                self._timer.start()
        elif t in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent, QEvent.Type.FontChange,
                   QEvent.Type.LanguageChange, QEvent.Type.StyleChange):
            inner = self.area.widget()
            if inner is not None and isinstance(obj, QWidget) and obj is not inner and inner.isAncestorOf(obj):
                self._timer.start()
        return False

    def refresh(self):
        inner = self.area.widget()
        if inner is None:
            return
        for w in [inner, *inner.findChildren(QWidget)]:
            lay = w.layout()
            if lay is not None:
                lay.invalidate()
        if inner.layout() is not None:
            inner.layout().activate()
        inner.updateGeometry()
        QApplication.sendPostedEvents(inner, QEvent.Type.LayoutRequest)


def icon_button(icon: str, tooltip: str = "", ghost: bool = True, checkable: bool = False) -> QToolButton:
    b = QToolButton()
    b.setObjectName("iconGhost" if ghost else "iconButton")
    b.setText(ICONS.get(icon, icon))
    b.setToolTip(tooltip)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class Card(QFrame):
    """A rounded panel with a title row that can collapse its content."""

    def __init__(self, title: str = "", collapsible: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(10)

        self.header = QWidget()
        self.header.setObjectName("cardHeader")
        h = QHBoxLayout(self.header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        h.addWidget(self.title)
        h.addStretch(1)
        self.header_tools = QHBoxLayout()
        self.header_tools.setSpacing(2)
        h.addLayout(self.header_tools)
        self.chevron = None
        if collapsible:
            self.chevron = icon_button("up")
            self.chevron.setFixedSize(26, 26)
            self.chevron.clicked.connect(self.toggle)
            h.addWidget(self.chevron)
        outer.addWidget(self.header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        outer.addWidget(self.body)

    def add(self, w):
        if isinstance(w, QWidget):
            self.body_layout.addWidget(w)
        else:
            self.body_layout.addLayout(w)
        return w

    def toggle(self):
        self.set_collapsed(self.body.isVisible())

    def set_collapsed(self, collapsed: bool):
        self.body.setVisible(not collapsed)
        if self.chevron:
            self.chevron.setText(ICONS["down"] if collapsed else ICONS["up"])

    def is_collapsed(self) -> bool:
        return not self.body.isVisible()

    def mouseReleaseEvent(self, e):
        if self.chevron and e.position().y() < self.header.geometry().bottom() + 4:
            self.toggle()
        super().mouseReleaseEvent(e)


class Segmented(QFrame):
    """A row of mutually exclusive buttons."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("segment")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in options:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))

    def value(self) -> str:
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return next(iter(self.buttons))

    def set_value(self, key: str):
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    def set_text(self, key: str, text: str):
        self.buttons[key].setText(text)


class SliderRow(QWidget):
    """Label, slider and value. Double-click the slider to reset it."""

    valueChanged = Signal(str, int)

    def __init__(self, key: str, text: str, minimum=-100, maximum=100, default=0, color: str | None = None, parent=None):
        super().__init__(parent)
        self.key = key
        self.default = default
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        if color:
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background:{color}; border-radius:4px;")
            top.addWidget(dot)
        self.label = QLabel(text)
        top.addWidget(self.label)
        top.addStretch(1)
        self.value_label = QLabel()
        self.value_label.setObjectName("sliderValue")
        top.addWidget(self.value_label)
        lay.addLayout(top)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(default)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.valueChanged.connect(self._changed)
        self.slider.mouseDoubleClickEvent = lambda e: self.reset()
        if color:
            self.slider.setStyleSheet(f"QSlider::sub-page:horizontal {{ background: {color}; }}"
                                      f"QSlider::handle:horizontal {{ border-color: {color}; }}")
        lay.addWidget(self.slider)
        self._update_label(default)

    def _update_label(self, v: int):
        self.value_label.setText(f"{v:+d}" if v else "0")
        self.value_label.setProperty("changed", v != self.default)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)

    def _changed(self, v: int):
        self._update_label(v)
        self.valueChanged.emit(self.key, v)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, v: int, silent: bool = False):
        if silent:
            self.slider.blockSignals(True)
        self.slider.setValue(int(v))
        self._update_label(int(v))
        if silent:
            self.slider.blockSignals(False)

    def reset(self):
        self.slider.setValue(self.default)


class PreviewCanvas(QWidget):
    """Shows the processed preview with an optional draggable crop frame."""

    offsetChanged = Signal(float, float)
    filesDropped = Signal(list)
    picked = Signal(float, float)  # normalised position of a white-balance click
    cropEdited = Signal(float, float, float, float)  # the frame was drawn with the mouse (normalised)
    cropReset = Signal()                              # double-click: back to the format's own frame
    cropToggle = Signal()                             # double-click: crop to the frame / back to the frame
    menuRequested = Signal(object)                    # right-click: global position
    zoomChanged = Signal(float)

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.p = palette
        self.image: QImage | None = None
        self.crop: tuple[float, float, float, float] | None = None  # normalised 0..1
        self.offset = (0.0, 0.0)
        self.free = (0.0, 0.0)  # free space around the crop, normalised to image size
        self.placeholder = ""
        self.message = ""
        self._drag_start: QPointF | None = None
        self._drag_offset = (0.0, 0.0)
        self.pick_mode = False
        self.edit_mode = False          # the frame has handles: drag corners, edges or the inside
        self.lock: float | None = None  # width / height in pixels the frame keeps, None: free
        self._grab: str | None = None
        self._new_moved = False
        self.drew_new = False
        self.result_mode = False        # the preview is a finished crop, not a frame to edit
        self.zoom_enabled = False       # wheel zooms, middle or right button pans (the big crop window)
        self.apply_btn = QPushButton(self)   # "Crop" button that floats at the frame's corner
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.clicked.connect(lambda: self.cropToggle.emit())
        self.apply_btn.hide()
        self.zoom = 1.0
        self.pan = QPointF(0.0, 0.0)
        self._pan_start: QPointF | None = None
        self._pan0 = QPointF()
        self._grab_pos = QPointF()
        self._grab_crop = (0.0, 0.0, 1.0, 1.0)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(QSize(320, 240))
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

    def set_palette(self, p: dict):
        self.p = p
        self.update()

    def set_image(self, img: QImage | None, crop=None, offset=(0.0, 0.0)):
        self.image = img
        self.crop = crop
        self.offset = offset
        self.message = ""
        if crop:
            x0, y0, x1, y1 = crop
            self.free = (1 - (x1 - x0), 1 - (y1 - y0))
        if not self.pick_mode:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._can_drag() else Qt.CursorShape.ArrowCursor)
        self.update()

    def set_message(self, text: str):
        self.message = text
        self.update()

    def set_edit(self, on: bool, lock: float | None = None):
        self.edit_mode = on
        self.lock = lock
        if not self.pick_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor if on or not self._can_drag() else Qt.CursorShape.OpenHandCursor)
        self.update()

    def _can_drag(self) -> bool:
        return not self.edit_mode and bool(self.crop) and (self.free[0] > 0.001 or self.free[1] > 0.001)

    def _image_rect(self) -> QRectF:
        if not self.image:
            return QRectF()
        m = 18
        avail = QRectF(self.rect()).adjusted(m, m, -m, -m)
        iw, ih = self.image.width(), self.image.height()
        k = min(avail.width() / iw, avail.height() / ih)
        w, h = iw * k * self.zoom, ih * k * self.zoom
        c = avail.center() + self.pan
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def _place_apply_button(self):
        show = bool(self.edit_mode and self.crop and self.image and not self.zoom_enabled and not self._grab)
        if show:
            cr = self._frame_rect()
            b = self.apply_btn
            b.adjustSize()
            x = min(max(4, cr.right() - b.width() - 8), self.width() - b.width() - 4)
            y = min(max(4, cr.bottom() - b.height() - 8), self.height() - b.height() - 4)
            b.move(int(x), int(y))
        self.apply_btn.setVisible(show)

    def paintEvent(self, _):
        self._place_apply_button()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(self.p["canvas"]))

        if not self.image:
            p.setPen(QColor(self.p["muted"]))
            f = QFont(ICON_FONT.split(",")[0])
            f.setPointSize(34)
            p.setFont(f)
            r = QRectF(self.rect())
            p.drawText(r.adjusted(0, -60, 0, -60), Qt.AlignmentFlag.AlignCenter, ICONS["photo"])
            f2 = QFont()
            f2.setPointSize(10)
            p.setFont(f2)
            p.drawText(r.adjusted(40, 40, -40, 40), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.message or self.placeholder)
            return

        r = self._image_rect()
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.setClipPath(path)
        p.drawImage(r, self.image)
        p.setClipping(False)

        if self.crop:
            x0, y0, x1, y1 = self.crop
            cr = QRectF(r.left() + x0 * r.width(), r.top() + y0 * r.height(),
                        (x1 - x0) * r.width(), (y1 - y0) * r.height())
            shade = QColor(0, 0, 0, 150)
            outside = QPainterPath()
            outside.addRoundedRect(r, 6, 6)
            inner = QPainterPath()
            inner.addRect(cr)
            p.fillPath(outside.subtracted(inner), shade)
            pen = QPen(QColor(255, 255, 255, 90), 1)
            p.setPen(pen)
            for i in (1, 2):
                x = cr.left() + cr.width() * i / 3
                y = cr.top() + cr.height() * i / 3
                p.drawLine(QPointF(x, cr.top()), QPointF(x, cr.bottom()))
                p.drawLine(QPointF(cr.left(), y), QPointF(cr.right(), y))
            p.setPen(QPen(QColor(self.p["accent_hover"]), 2))
            p.drawRect(cr)
            if self.edit_mode:
                p.setBrush(QColor("#ffffff"))
                for pt in self._handles(cr).values():
                    p.drawRect(QRectF(pt.x() - 5, pt.y() - 5, 10, 10))

        if self.message:
            p.setPen(QColor(self.p["text"]))
            p.drawText(QRectF(self.rect()).adjusted(0, 0, 0, -8),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.message)

    # -------------------------------------------------------------- dragging the crop
    def set_pick_mode(self, on: bool):
        self.pick_mode = on
        self.setCursor(Qt.CursorShape.CrossCursor if on else
                       (Qt.CursorShape.OpenHandCursor if self._can_drag() else Qt.CursorShape.ArrowCursor))

    # -------------------------------------------------------------- frame with handles
    def _frame_rect(self) -> QRectF:
        r = self._image_rect()
        x0, y0, x1, y1 = self.crop
        return QRectF(r.left() + x0 * r.width(), r.top() + y0 * r.height(), (x1 - x0) * r.width(), (y1 - y0) * r.height())

    def _handles(self, cr: QRectF) -> dict[str, QPointF]:
        cx, cy = cr.center().x(), cr.center().y()
        pts = {"nw": cr.topLeft(), "ne": cr.topRight(), "sw": cr.bottomLeft(), "se": cr.bottomRight()}
        if self.lock is None:
            pts.update(n=QPointF(cx, cr.top()), s=QPointF(cx, cr.bottom()),
                       w=QPointF(cr.left(), cy), e=QPointF(cr.right(), cy))
        return pts

    def _start_new(self, pos: QPointF) -> bool:
        """Press on the picture outside the frame: a new frame is drawn from this corner."""
        r = self._image_rect()
        if not (self.image and r.contains(pos)):
            return False
        self._grab, self._grab_pos, self._grab_crop = "new", pos, self.crop
        self._new_moved = False
        return True

    def _hit(self, pos: QPointF) -> str | None:
        if not (self.edit_mode and self.crop and self.image):
            return None
        cr = self._frame_rect()
        for name, pt in self._handles(cr).items():
            if abs(pt.x() - pos.x()) <= 9 and abs(pt.y() - pos.y()) <= 9:
                return name
        return "move" if cr.contains(pos) else None

    @staticmethod
    def _cursor_for(h: str | None):
        return {"nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
                "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
                "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
                "w": Qt.CursorShape.SizeHorCursor, "e": Qt.CursorShape.SizeHorCursor,
                "move": Qt.CursorShape.SizeAllCursor}.get(h, Qt.CursorShape.ArrowCursor)

    def _drag_frame(self, pos: QPointF):
        r = self._image_rect()
        if r.isEmpty():
            return
        dx = (pos.x() - self._grab_pos.x()) / r.width()
        dy = (pos.y() - self._grab_pos.y()) / r.height()
        x0, y0, x1, y1 = self._grab_crop or (0.0, 0.0, 1.0, 1.0)
        h, mn = self._grab, 0.03
        if h == "new":
            if not self._new_moved and abs(dx * r.width()) + abs(dy * r.height()) < 4:
                return
            self._new_moved = True
            ax = min(max(0.0, (self._grab_pos.x() - r.left()) / r.width()), 1.0)
            ay = min(max(0.0, (self._grab_pos.y() - r.top()) / r.height()), 1.0)
            px = min(max(0.0, (pos.x() - r.left()) / r.width()), 1.0)
            py = min(max(0.0, (pos.y() - r.top()) / r.height()), 1.0)
            if self.lock is not None:
                k = r.width() / r.height() / self.lock
                sx, sy = (1 if px >= ax else -1), (1 if py >= ay else -1)
                max_w = min((1 - ax) if sx > 0 else ax, ((1 - ay) if sy > 0 else ay) / k)
                w = min(abs(px - ax), abs(py - ay) / k, max_w)
                px, py = ax + sx * w, ay + sy * w * k
            x0, x1 = sorted((ax, px))
            y0, y1 = sorted((ay, py))
            self.crop = (x0, y0, max(x1, x0 + 0.01), max(y1, y0 + 0.01))
        elif h == "move":
            w, hh = x1 - x0, y1 - y0
            nx, ny = min(max(0.0, x0 + dx), 1 - w), min(max(0.0, y0 + dy), 1 - hh)
            self.crop = (nx, ny, nx + w, ny + hh)
        elif self.lock is not None:
            # corner with the shape kept: the opposite corner stays, size follows the pointer
            ax, ay = (x1 if "w" in h else x0), (y1 if "n" in h else y0)
            sx, sy = (-1 if "w" in h else 1), (-1 if "n" in h else 1)
            k = r.width() / r.height() / self.lock          # normalised height per normalised width
            max_w = min((ax if sx < 0 else 1 - ax), (ay if sy < 0 else 1 - ay) / k)
            px = (x0 if "w" in h else x1) + dx
            w = min(max(mn, (px - ax) * sx), max_w)
            hh = w * k
            nx0, nx1 = sorted((ax, ax + sx * w))
            ny0, ny1 = sorted((ay, ay + sy * hh))
            self.crop = (nx0, ny0, nx1, ny1)
        else:
            if "w" in h:
                x0 = min(max(0.0, x0 + dx), x1 - mn)
            if "e" in h:
                x1 = max(min(1.0, x1 + dx), x0 + mn)
            if "n" in h:
                y0 = min(max(0.0, y0 + dy), y1 - mn)
            if "s" in h:
                y1 = max(min(1.0, y1 + dy), y0 + mn)
            self.crop = (x0, y0, x1, y1)
        self.update()

    def keyPressEvent(self, e):
        """Arrows nudge the frame by one picture pixel (Shift: ten); with Ctrl they resize it instead."""
        k = e.key()
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if not (self.edit_mode and self.crop and self.image and k in arrows):
            super().keyPressEvent(e)
            return
        step = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        dx, dy = arrows[k][0] * step / self.image.width(), arrows[k][1] * step / self.image.height()
        x0, y0, x1, y1 = self.crop
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.lock is not None:           # shape kept: width leads, height follows
                d = dx if dx else dy * self.lock * self.image.height() / self.image.width()
                kx = self.image.width() / self.image.height() / self.lock
                w = min(max(0.01, x1 - x0 + d), 1 - x0, (1 - y0) / kx)
                x1, y1 = x0 + w, y0 + w * kx
            else:
                x1 = min(max(x0 + 0.01, x1 + dx), 1.0)
                y1 = min(max(y0 + 0.01, y1 + dy), 1.0)
        else:
            w, h = x1 - x0, y1 - y0
            x0 = min(max(0.0, x0 + dx), 1 - w)
            y0 = min(max(0.0, y0 + dy), 1 - h)
            x1, y1 = x0 + w, y0 + h
        self.crop = (x0, y0, x1, y1)
        self.update()
        self.cropEdited.emit(*self.crop)

    def mousePressEvent(self, e):
        self.setFocus()
        if self.zoom_enabled and e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_start, self._pan0 = e.position(), QPointF(self.pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self.edit_mode and e.button() == Qt.MouseButton.LeftButton and not self.pick_mode:
            h = self._hit(e.position())
            if h:
                self._grab, self._grab_pos, self._grab_crop = h, e.position(), self.crop
            else:
                self._start_new(e.position())
            return
        if self.pick_mode and e.button() == Qt.MouseButton.LeftButton and self.image:
            r = self._image_rect()
            if r.contains(e.position()):
                self.picked.emit((e.position().x() - r.left()) / r.width(),
                                 (e.position().y() - r.top()) / r.height())
            return
        if e.button() == Qt.MouseButton.LeftButton and self._can_drag():
            self._drag_start = e.position()
            self._drag_offset = self.offset
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._pan_start is not None:
            self.pan = self._pan0 + (e.position() - self._pan_start)
            self.update()
            return
        if self.edit_mode and not self.pick_mode:
            if self._grab:
                self._drag_frame(e.position())
            else:
                h = self._hit(e.position())
                self.setCursor(self._cursor_for(h) if h else
                               Qt.CursorShape.CrossCursor if self._image_rect().contains(e.position())
                               else Qt.CursorShape.ArrowCursor)
            return
        if self._drag_start is None:
            return
        r = self._image_rect()
        if r.isEmpty():
            return
        d = e.position() - self._drag_start
        ox, oy = self._drag_offset
        fx, fy = self.free
        # Offset -1..1 spans the free space: one unit is half of it.
        if fx > 0.001:
            ox += d.x() / (r.width() * fx / 2)
        if fy > 0.001:
            oy += d.y() / (r.height() * fy / 2)
        ox, oy = max(-1.0, min(1.0, ox)), max(-1.0, min(1.0, oy))
        self._move_crop(ox, oy)

    def mouseReleaseEvent(self, e):
        if self._pan_start is not None and e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self._grab:
            moved = self._grab != "new" or self._new_moved
            self.drew_new = self._grab == "new"
            self._grab = None
            if moved and self.crop:
                self.cropEdited.emit(*self.crop)
            return
        if self._drag_start is not None:
            self._drag_start = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.offsetChanged.emit(*self.offset)

    def reset_view(self):
        self.zoom, self.pan = 1.0, QPointF(0.0, 0.0)
        self.zoomChanged.emit(1.0)
        self.update()

    def wheelEvent(self, e):
        if not (self.zoom_enabled and self.image):
            e.ignore()
            return
        s = 1.25 if e.angleDelta().y() > 0 else 0.8
        z = min(max(self.zoom * s, 1.0), 24.0)
        s = z / self.zoom
        if s == 1.0:
            return
        m = 18
        c0 = QRectF(self.rect()).adjusted(m, m, -m, -m).center()
        v = e.position() - (c0 + self.pan)
        self.pan = self.pan + v * (1 - s)          # the point under the pointer stays under it
        self.zoom = z
        if z == 1.0:
            self.pan = QPointF(0.0, 0.0)
        self.zoomChanged.emit(z)
        self.update()

    def contextMenuEvent(self, e):
        if self.zoom_enabled:
            return
        if self.image:
            self.menuRequested.emit(e.globalPos())

    def mouseDoubleClickEvent(self, e):
        if self.result_mode and e.button() == Qt.MouseButton.LeftButton:
            self.cropToggle.emit()
            return
        if self.edit_mode:
            if self.crop and self._frame_rect().contains(e.position()):
                self.cropToggle.emit()          # double-click inside the frame: crop
            else:
                self.cropReset.emit()           # double-click outside it: remove the frame
            return
        if self._can_drag():
            self._move_crop(0.0, 0.0)
            self.offsetChanged.emit(0.0, 0.0)

    def _move_crop(self, ox: float, oy: float):
        if not self.crop:
            return
        x0, y0, x1, y1 = self.crop
        cw, ch = x1 - x0, y1 - y0
        fx, fy = self.free
        nx0 = fx / 2 * (1 + ox)
        ny0 = fy / 2 * (1 + oy)
        self.crop = (nx0, ny0, nx0 + cw, ny0 + ch)
        self.offset = (ox, oy)
        self.update()

    # -------------------------------------------------------------- drag and drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)


BRAND_FONT = "Bahnschrift SemiBold"


class LogoMark(QWidget):
    """The company mark: a gradient tile that keeps flowing, with a halo, a passing shine,
    and a little hop when the cursor touches it."""

    SIZE = 52

    def __init__(self, letter: str = "К", parent=None):
        super().__init__(parent)
        self.letter = letter
        self.setFixedSize(self.SIZE, self.SIZE)
        self._flow = 0.0
        self._shine = -1.0
        self._pop = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._flow_anim = QVariantAnimation(self, duration=7000, startValue=0.0, endValue=1.0, loopCount=-1)
        self._flow_anim.valueChanged.connect(self._on_flow)
        self._shine_anim = QVariantAnimation(self, duration=1100, startValue=-0.5, endValue=1.5)
        self._shine_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._shine_anim.valueChanged.connect(self._on_shine)
        self._shine_anim.finished.connect(lambda: self._on_shine(-1.0))
        self._shine_timer = QTimer(self, interval=5200)
        self._shine_timer.timeout.connect(self._shine_anim.start)
        self._pop_anim = QVariantAnimation(self, duration=420)
        self._pop_anim.valueChanged.connect(self._on_pop)

    def _on_flow(self, v):
        self._flow = float(v)
        self.update()

    def _on_shine(self, v):
        self._shine = float(v)
        self.update()

    def _on_pop(self, v):
        self._pop = float(v)
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self._flow_anim.start()
        self._shine_timer.start()
        QTimer.singleShot(700, self._shine_anim.start)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._flow_anim.stop()
        self._shine_timer.stop()

    def enterEvent(self, e):
        super().enterEvent(e)
        self._pop_anim.stop()
        self._pop_anim.setStartValue(self._pop)
        self._pop_anim.setEndValue(1.0)
        self._pop_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._pop_anim.start()
        if self._shine_anim.state() != QVariantAnimation.State.Running:
            self._shine_anim.start()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._pop_anim.stop()
        self._pop_anim.setStartValue(self._pop)
        self._pop_anim.setEndValue(0.0)
        self._pop_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pop_anim.start()

    def paintEvent(self, _):
        import math

        s = self.SIZE
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        c = QPointF(s / 2, s / 2)
        breathe = 0.5 + 0.5 * math.sin(self._flow * 2 * math.pi)
        halo = QRadialGradient(c, s * 0.62)
        halo.setColorAt(0.55, QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(),
                                     max(0, min(255, int(60 + 50 * breathe + 60 * self._pop)))))
        halo.setColorAt(1, QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 0))
        p.fillRect(self.rect(), halo)

        p.translate(c)
        k = 1.0 + 0.12 * self._pop
        p.scale(k, k)
        p.rotate(-7 * self._pop)
        p.translate(-c)

        tile = QRectF(7, 7, s - 14, s - 14)
        ang = self._flow * 2 * math.pi
        dx, dy = math.cos(ang) * tile.width() * 0.75, math.sin(ang) * tile.height() * 0.75
        g = QLinearGradient(c.x() - dx, c.y() - dy, c.x() + dx, c.y() + dy)
        g.setColorAt(0, ACCENT)
        g.setColorAt(0.5, ACCENT2)
        g.setColorAt(1, ACCENT)
        path = QPainterPath()
        path.addRoundedRect(tile, 12, 12)
        p.fillPath(path, g)

        p.save()
        p.setClipPath(path)
        gloss = QLinearGradient(0, tile.top(), 0, tile.bottom())
        gloss.setColorAt(0, QColor(255, 255, 255, 70))
        gloss.setColorAt(0.5, QColor(255, 255, 255, 0))
        p.fillRect(tile, gloss)
        if self._shine > -0.9:
            x = tile.left() + self._shine * tile.width()
            band = QLinearGradient(x - 9, tile.top(), x + 9, tile.bottom())
            band.setColorAt(0, QColor(255, 255, 255, 0))
            band.setColorAt(0.5, QColor(255, 255, 255, 120))
            band.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(tile, band)
        p.restore()

        font = QFont(BRAND_FONT)
        font.setPixelSize(30)
        font.setBold(True)
        text = QPainterPath()
        text.addText(0, 0, font, self.letter)
        br = text.boundingRect()
        text.translate(tile.center().x() - br.center().x(), tile.center().y() - br.center().y())
        p.fillPath(text.translated(0, 1.5), QColor(0, 0, 0, 60))
        p.fillPath(text, QColor(255, 255, 255))
        p.end()


class BrandTitle(QWidget):
    """The company name in a distinctive typeface: the letters drop in once when the window
    opens, then a colour glides through them. The part after " - " is shown quietly beside it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.brand = ""
        self.tail = ""
        self.colors = {"text": QColor("#eceef5"), "muted": QColor("#8a8fa3"),
                       "a": QColor("#937aff"), "b": QColor("#22d3ee")}
        self._flow = 0.0
        self._intro = 0.0
        self._intro_done = False
        self._flow_anim = QVariantAnimation(self, duration=5200, startValue=0.0, endValue=1.0, loopCount=-1)
        self._flow_anim.valueChanged.connect(self._on_flow)
        self._intro_anim = QVariantAnimation(self, duration=1100, startValue=0.0, endValue=1.0)
        self._intro_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._intro_anim.valueChanged.connect(self._on_intro)
        self._intro_anim.finished.connect(self._intro_finished)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def _intro_finished(self):
        self._intro_done = True
        self._intro = 1.0
        self.update()

    def set_colors(self, text: str, muted: str, a: str, b: str):
        self.colors = {"text": QColor(text), "muted": QColor(muted), "a": QColor(a), "b": QColor(b)}
        self.update()

    def setText(self, text: str):
        if " - " in text:
            self.brand, self.tail = (x.strip() for x in text.split(" - ", 1))
        else:
            self.brand, _, self.tail = text.partition(" ")
        self.updateGeometry()
        self.update()

    def _fonts(self):
        f1 = QFont(BRAND_FONT)
        f1.setPixelSize(25)
        f1.setBold(True)
        f1.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        f2 = QFont("Bahnschrift Light")
        f2.setPixelSize(15)
        return f1, f2

    def sizeHint(self) -> QSize:
        f1, f2 = self._fonts()
        w = QFontMetricsF(f1).horizontalAdvance(self.brand)
        if self.tail:
            w += 14 + QFontMetricsF(f2).horizontalAdvance(self.tail)
        return QSize(int(w) + 8, 34)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _on_flow(self, v):
        self._flow = float(v)
        self.update()

    def _on_intro(self, v):
        self._intro = float(v)
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self._flow_anim.start()
        if not self._intro_done and self._intro_anim.state() != QVariantAnimation.State.Running:
            self._intro_anim.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._flow_anim.stop()

    def paintEvent(self, _):
        f1, f2 = self._fonts()
        fm1 = QFontMetricsF(f1)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        base = self.height() / 2 + (fm1.ascent() - fm1.descent()) / 2
        width = max(1.0, fm1.horizontalAdvance(self.brand))
        shift = self._flow * width * 2
        g = QLinearGradient(-shift, 0, width - shift, 0)
        a, b, t = self.colors["a"], self.colors["b"], self.colors["text"]
        for pos, col in ((0, a), (0.35, b), (0.7, t), (1, a)):
            g.setColorAt(pos, col)
        g.setSpread(QLinearGradient.Spread.RepeatSpread)
        p.setFont(f1)
        p.setPen(QPen(QBrush(g), 1))
        n = max(1, len(self.brand))
        x = 3.0
        for i, ch in enumerate(self.brand):
            k = min(1.0, max(0.0, (self._intro * (n + 5) - i) / 5))
            p.setOpacity(k)
            p.drawText(QPointF(x, base + (1 - k) * 12), ch)
            x += fm1.horizontalAdvance(ch)
        if self.tail:
            p.setOpacity(min(1.0, max(0.0, (self._intro - 0.6) / 0.4)))
            p.setFont(f2)
            p.setPen(self.colors["muted"])
            p.drawText(QPointF(x + 14, base - 1), self.tail)
        p.end()
