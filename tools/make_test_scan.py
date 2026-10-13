"""Makes a fake scan of a Russian contract (made-up data) to try the OCR on: tilt, dark borders, noise, shadow.

    python tools/make_test_scan.py out.pdf [--angle 2.5] [--truth truth.json]
The truth file lists the lines printed on the page, to compare with what the OCR read.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
import pymupdf

FONTS = Path(r"C:\Windows\Fonts")

TITLE = "ДОГОВОР ОКАЗАНИЯ УСЛУГ № 17/2026"
LINES = [
    ("c", TITLE, 15, True),
    ("l", "г. Казань                                                                         12 марта 2026 г.", 11, False),
    ("l", "", 11, False),
    ("l", "Общество с ограниченной ответственностью «Ромашка», именуемое в дальнейшем «Исполнитель»,", 11, False),
    ("l", "в лице директора Иванова Ивана Ивановича, действующего на основании Устава, с одной стороны,", 11, False),
    ("l", "и Индивидуальный предприниматель Петров Пётр Петрович, именуемый в дальнейшем «Заказчик»,", 11, False),
    ("l", "с другой стороны, заключили настоящий договор о нижеследующем:", 11, False),
    ("l", "", 11, False),
    ("h", "1. Предмет договора", 12, True),
    ("l", "1.1. Исполнитель обязуется выполнить печать и брошюровку рекламной продукции, а Заказчик", 11, False),
    ("l", "обязуется принять и оплатить работы в порядке и на условиях, предусмотренных договором.", 11, False),
    ("l", "1.2. Срок выполнения работ: 5 (пять) рабочих дней с момента получения макетов.", 11, False),
    ("l", "", 11, False),
    ("h", "2. Стоимость и порядок расчётов", 12, True),
    ("l", "2.1. Стоимость работ составляет 48 500,00 (сорок восемь тысяч пятьсот) рублей, НДС не облагается.", 11, False),
    ("l", "2.2. Оплата производится в течение 3 банковских дней на основании выставленного счёта.", 11, False),
    ("l", "", 11, False),
    ("h", "3. Реквизиты сторон", 12, True),
    ("l", "Исполнитель: ООО «Ромашка», ИНН 1655123407, КПП 165501001, ОГРН 1021600000124,", 11, False),
    ("l", "р/с 40702810900000012345 в АО «Тестбанк», БИК 049205000.", 11, False),
    ("l", "Заказчик: ИП Петров П. П., ИНН 165512345632, ОГРНИП 304165500000019.", 11, False),
    ("l", "", 11, False),
    ("l", "Исполнитель ____________ / Иванов И. И. /        Заказчик ____________ / Петров П. П. /", 11, False),
]


def build_page(path: Path):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    reg, bold = str(FONTS / "times.ttf"), str(FONTS / "timesbd.ttf")
    y = 90.0
    truth = []
    for kind, text, size, b in LINES:
        font = bold if b else reg
        name = "tb" if b else "tr"
        if text:
            if kind == "c":
                w = pymupdf.Font(fontfile=font).text_length(text, fontsize=size)
                x = (595 - w) / 2
            else:
                x = 62
            page.insert_text((x, y), text, fontsize=size, fontfile=font, fontname=name)
            truth.append(" ".join(text.split()))
        y += size * 1.55 if kind != "h" else size * 1.9
    doc.save(path)
    return truth


def degrade(img: np.ndarray, angle: float, rng: random.Random) -> np.ndarray:
    h, w = img.shape[:2]
    pad = int(0.08 * w)
    bg = np.full((h + 2 * pad, w + 2 * pad, 3), 70, np.uint8)       # dark scanner lid
    bg[pad:pad + h, pad:pad + w] = img
    H, W = bg.shape[:2]
    M = cv2.getRotationMatrix2D((W / 2, H / 2), angle, 1.0)
    out = cv2.warpAffine(bg, M, (W, H), borderValue=(60, 60, 60), flags=cv2.INTER_CUBIC)
    out = out.astype(np.float32)
    # uneven light: shadow across the page
    xs = np.linspace(0, 1, W)[None, :, None]
    ys = np.linspace(0, 1, H)[:, None, None]
    out *= 0.78 + 0.22 * (1 - 0.6 * xs - 0.3 * ys).clip(0, 1) ** 0.7
    # paper tint and noise
    out *= np.array([0.94, 0.97, 1.0], np.float32)[None, None, :]
    out += np.random.default_rng(rng.randint(0, 9999)).normal(0, 9, out.shape)
    out = cv2.GaussianBlur(out.clip(0, 255).astype(np.uint8), (3, 3), 0.8)
    # specks
    r = np.random.default_rng(5)
    for _ in range(260):
        x, yy = int(r.integers(pad, W - pad)), int(r.integers(pad, H - pad))
        cv2.circle(out, (x, yy), int(r.integers(1, 3)), (int(r.integers(80, 150)),) * 3, -1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--angle", type=float, default=2.5)
    ap.add_argument("--truth", default="")
    ap.add_argument("--dpi", type=int, default=200)
    a = ap.parse_args()
    out = Path(a.out)
    src = out.with_name(out.stem + ".clean.pdf")
    truth = build_page(src)
    pix = pymupdf.open(src)[0].get_pixmap(dpi=a.dpi, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)[:, :, ::-1].copy()
    scan = degrade(img, a.angle, random.Random(1))
    ok, jpg = cv2.imencode(".jpg", scan, [cv2.IMWRITE_JPEG_QUALITY, 70])
    doc = pymupdf.open()
    h, w = scan.shape[:2]
    p = doc.new_page(width=w * 72 / a.dpi, height=h * 72 / a.dpi)
    p.insert_image(p.rect, stream=jpg.tobytes())
    doc.save(out)
    if a.truth:
        Path(a.truth).write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    print("scan:", out, "lines:", len(truth))


if __name__ == "__main__":
    main()
