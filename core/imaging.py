"""Colour adjustment, framing (rotate / mirror / crop) and saving."""
from __future__ import annotations

import math

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from .sheet import SheetSettings


# --------------------------------------------------------------------------- settings

@dataclass
class ColorSettings:
    """All values are slider positions in the range -100..100, 0 = unchanged."""

    brightness: int = 0
    contrast: int = 0
    saturation: int = 0
    gamma: int = 0
    red: int = 0
    green: int = 0
    blue: int = 0
    cyan: int = 0
    magenta: int = 0
    yellow: int = 0
    auto: int = 0                                   # 0..100, strength of automatic levels
    wb: tuple[float, float, float] = (1.0, 1.0, 1.0)  # white balance gains from the pipette

    def is_neutral(self) -> bool:
        ints = (getattr(self, f.name) for f in fields(self) if f.name != "wb")
        return not any(ints) and tuple(self.wb) == (1.0, 1.0, 1.0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ColorSettings":
        data = dict(data or {})
        names = {f.name for f in fields(cls)}
        wb = data.pop("wb", None)
        out = cls(**{k: int(v) for k, v in data.items() if k in names and k != "wb"})
        if wb and len(wb) == 3:
            out.wb = tuple(float(x) for x in wb)
        return out


# Ratio presets: key -> (long side, short side). Orientation is decided per image.
RATIOS: dict[str, tuple[float, float] | None] = {
    "original": None,
    "3:2": (3, 2),      # 10x15, 20x30
    "4:3": (4, 3),
    "5:4": (5, 4),      # 20x25
    "7:5": (7, 5),      # 13x18
    "1:1": (1, 1),
    "16:9": (16, 9),
    "a4": (297, 210),
}

UNIT_TO_INCH = {"cm": 1 / 2.54, "mm": 1 / 25.4, "in": 1.0}

# Sizes offered in the "custom size" preset list: (width, height, unit)
SIZE_PRESETS = [
    (10, 15, "cm"), (13, 18, "cm"), (15, 21, "cm"), (20, 25, "cm"), (20, 30, "cm"),
    (21, 29.7, "cm"), (9, 12, "cm"), (3, 4, "cm"), (3.5, 4.5, "cm"), (4, 6, "in"), (5, 7, "in"), (8, 10, "in"),
]


@dataclass
class FrameSettings:
    ratio: str = "original"
    auto_orient: bool = True     # ratio follows the photo's own orientation
    portrait: bool = False       # used when auto_orient is off
    rotate: int = 0              # clockwise degrees: 0, 90, 180, 270
    mirror_h: bool = False
    mirror_v: bool = False
    # Used when ratio == "custom": exact print size.
    size_w: float = 10.0
    size_h: float = 15.0
    unit: str = "cm"             # cm, mm, in
    fit: bool = False            # False: crop to the size, True: keep the whole photo and pad
    fill: str = "#ffffff"        # padding colour in fit mode


@dataclass
class OutputSettings:
    fmt: str = "JPEG"            # JPEG, PNG, TIFF, PDF
    quality: int = 95
    dpi: int = 300
    keep_structure: bool = True  # mirror input sub-folders in the output
    merge_pdf: bool = False      # PDF output: everything in one file


@dataclass
class JobSettings:
    color: ColorSettings = field(default_factory=ColorSettings)
    frame: FrameSettings = field(default_factory=FrameSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    sheet: SheetSettings = field(default_factory=SheetSettings)
    # Per-file crop offsets chosen by dragging in the preview: str(path) -> (x, y) in -1..1
    offsets: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Per-file colour settings that replace ``color`` for that file only.
    color_overrides: dict[str, ColorSettings] = field(default_factory=dict)
    # PDFs changed in the PDF editor: str(original path) -> edited copy that is converted instead.
    replacements: dict[str, str] = field(default_factory=dict)
    # Per-file free straightening angle in degrees (clockwise) and crop frame (normalised x0, y0, x1, y1)
    # drawn with the mouse; the frame is relative to the straightened picture.
    angles: dict[str, float] = field(default_factory=dict)
    crops: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)

    def color_for(self, path) -> ColorSettings:
        return self.color_overrides.get(str(path), self.color)


EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tif", "PDF": ".pdf"}


# --------------------------------------------------------------------------- colour

def _clamp(v: float) -> int:
    return 0 if v < 0 else 255 if v > 255 else int(round(v))


def build_luts(c: ColorSettings) -> list[int]:
    """One 768-entry lookup table (R, G, B) for every per-channel adjustment."""
    # Cyan/magenta/yellow are the opposites of red/green/blue.
    gains = (
        (1 + (c.red - c.cyan) / 200) * c.wb[0],
        (1 + (c.green - c.magenta) / 200) * c.wb[1],
        (1 + (c.blue - c.yellow) / 200) * c.wb[2],
    )
    bright = 1 + c.brightness / 100
    contrast = 1 + c.contrast / 100 if c.contrast < 0 else 1 + c.contrast / 50
    gamma = 2 ** (c.gamma / 50)  # -100..100 -> 0.25..4, >1 lightens midtones
    lut: list[int] = []
    for gain in gains:
        for x in range(256):
            v = x * gain * bright
            v = (v - 127.5) * contrast + 127.5
            v = max(0.0, min(255.0, v))
            if gamma != 1:
                v = 255 * (v / 255) ** (1 / gamma)
            lut.append(_clamp(v))
    return lut


def auto_levels(img: Image.Image, strength: int) -> Image.Image:
    """Stretch every channel to the full range (fixes dull and tinted photos)."""
    stretched = ImageOps.autocontrast(img, cutoff=0.5)
    return Image.blend(img, stretched, max(0, min(100, strength)) / 100)


def white_balance_from_pixel(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Gains that turn the picked pixel into neutral grey."""
    r, g, b = (max(1, v) for v in rgb)
    grey = (r + g + b) / 3
    return tuple(round(max(0.4, min(2.5, grey / v)), 4) for v in (r, g, b))


def apply_color(img: Image.Image, c: ColorSettings) -> Image.Image:
    if c.is_neutral():
        return img
    info = img.info
    if c.auto:
        img = auto_levels(img, c.auto)
    out = img.point(build_luts(c))
    if c.saturation:
        out = ImageEnhance.Color(out).enhance(max(0.0, 1 + c.saturation / 100))
    out.info.update(info)
    return out


# --------------------------------------------------------------------------- frame

def orient(img: Image.Image, f: FrameSettings) -> Image.Image:
    info = img.info
    if f.rotate % 360:
        # PIL rotates counter-clockwise, the UI talks clockwise.
        img = img.rotate(-(f.rotate % 360), expand=True)
    if f.mirror_h:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if f.mirror_v:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    img.info.update(info)
    return img


def straighten(img: Image.Image, angle: float) -> Image.Image:
    """Turn by a small angle (clockwise) and cut away the empty corners: the largest same-shaped part stays."""
    if not angle:
        return img
    info = img.info
    w, h = img.size
    a = math.radians(abs(angle) % 180)
    k = 1.0 / (abs(math.cos(a)) + abs(math.sin(a)) * max(w / h, h / w))
    turned = img.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=False)
    cw, ch = max(1, round(w * k)), max(1, round(h * k))
    left, top = (w - cw) // 2, (h - ch) // 2
    out = turned.crop((left, top, left + cw, top + ch))
    out.info.update(info)
    return out


def ratio_pair(f: FrameSettings) -> tuple[float, float] | None:
    """(long side, short side) of the chosen format, or None for "original"."""
    if f.ratio == "custom":
        a, b = max(f.size_w, f.size_h), min(f.size_w, f.size_h)
        return (a, b) if b > 0 else None
    return RATIOS.get(f.ratio)


def is_portrait(size: tuple[int, int], f: FrameSettings) -> bool:
    return (size[1] > size[0]) if f.auto_orient else f.portrait


def target_pixels(size: tuple[int, int], f: FrameSettings, dpi: int) -> tuple[int, int] | None:
    """Exact output size in pixels for a custom print size, or None."""
    if f.ratio != "custom" or not ratio_pair(f):
        return None
    long_px = max(1, round(max(f.size_w, f.size_h) * UNIT_TO_INCH.get(f.unit, 1 / 2.54) * dpi))
    short_px = max(1, round(min(f.size_w, f.size_h) * UNIT_TO_INCH.get(f.unit, 1 / 2.54) * dpi))
    return (short_px, long_px) if is_portrait(size, f) else (long_px, short_px)


def fit_pad(img: Image.Image, f: FrameSettings) -> tuple[Image.Image, tuple[float, float, float, float]]:
    """Pad the whole photo to the chosen aspect ratio. Returns the image and
    where the photo sits inside it (normalised box)."""
    long_side, short_side = ratio_pair(f)
    w, h = img.size
    target = short_side / long_side if is_portrait(img.size, f) else long_side / short_side
    if w / h > target:
        nw, nh = w, max(h, round(w / target))
    else:
        nw, nh = max(w, round(h * target)), h
    canvas = Image.new("RGB", (nw, nh), f.fill)
    left, top = (nw - w) // 2, (nh - h) // 2
    canvas.paste(img, (left, top))
    canvas.info.update(img.info)
    return canvas, (left / nw, top / nh, (left + w) / nw, (top + h) / nh)


def crop_box(size: tuple[int, int], f: FrameSettings, offset=(0.0, 0.0)) -> tuple[int, int, int, int] | None:
    """Crop rectangle for an image of ``size`` (after orientation), or None."""
    ratio = ratio_pair(f)
    if not ratio or (f.ratio == "custom" and f.fit):
        return None
    w, h = size
    long_side, short_side = ratio
    portrait = is_portrait(size, f)
    target = short_side / long_side if portrait else long_side / short_side
    if w / h > target:
        cw, ch = round(h * target), h
    else:
        cw, ch = w, round(w / target)
    cw, ch = max(1, min(cw, w)), max(1, min(ch, h))
    ox, oy = offset
    left = round((w - cw) / 2 * (1 + max(-1.0, min(1.0, ox))))
    top = round((h - ch) / 2 * (1 + max(-1.0, min(1.0, oy))))
    return left, top, left + cw, top + ch


def apply_frame(img: Image.Image, f: FrameSettings, offset=(0.0, 0.0), dpi: int | None = None,
                angle: float = 0.0, crop=None) -> Image.Image:
    """Rotate, mirror, crop or pad. With ``dpi`` a custom size is resized to exact pixels.
    ``angle`` straightens the picture, ``crop`` is a frame drawn with the mouse (normalised box)."""
    img = straighten(orient(img, f), angle)
    if crop and not (f.ratio == "custom" and f.fit and ratio_pair(f)):
        w, h = img.size
        box = (round(crop[0] * w), round(crop[1] * h), round(crop[2] * w), round(crop[3] * h))
        if box[2] - box[0] >= 1 and box[3] - box[1] >= 1 and box != (0, 0, w, h):
            info = img.info
            img = img.crop(box)
            img.info.update(info)
        crop = None
        offset = (0.0, 0.0)
        px = target_pixels(img.size, f, dpi) if dpi else None
        if px and img.size != px:
            info = img.info
            img = img.resize(px, Image.Resampling.LANCZOS)
            img.info.update(info)
        return img
    px = target_pixels(img.size, f, dpi) if dpi else None
    if f.ratio == "custom" and f.fit and ratio_pair(f):
        img, _ = fit_pad(img, f)
    else:
        box = crop_box(img.size, f, offset)
        if box and box != (0, 0, *img.size):
            info = img.info
            img = img.crop(box)
            img.info.update(info)
    if px and img.size != px:
        info = img.info
        img = img.resize(px, Image.Resampling.LANCZOS)
        img.info.update(info)
    return img


# --------------------------------------------------------------------------- save

def save_image(img: Image.Image, path: Path, out: OutputSettings) -> None:
    save_images([img], path, out)


def save_images(images: list[Image.Image], path: Path, out: OutputSettings) -> None:
    """Save one image, or several pages into one PDF/TIFF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = images[0]
    if out.fmt == "PDF":
        img.save(path, "PDF", resolution=float(out.dpi), save_all=True, append_images=images[1:], quality=95)
        return
    kwargs: dict = {"dpi": (out.dpi, out.dpi)}
    icc = img.info.get("icc_profile")
    if icc:
        kwargs["icc_profile"] = icc
    if out.fmt == "JPEG":
        kwargs.update(quality=int(out.quality), optimize=True)
        if out.quality >= 90:
            kwargs["subsampling"] = 0  # full colour resolution for print
    elif out.fmt == "PNG":
        kwargs["compress_level"] = 6
    elif out.fmt == "TIFF":
        kwargs["compression"] = "tiff_lzw"
        if len(images) > 1:
            kwargs.update(save_all=True, append_images=images[1:])
    img.save(path, out.fmt, **kwargs)
