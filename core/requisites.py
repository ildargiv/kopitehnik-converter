"""Checks of what the OCR read: tax numbers, registration numbers, dates and sums. Returns what looks wrong."""
from __future__ import annotations

import re
from datetime import date

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
          "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
ONES = {"ноль": 0, "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
        "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
        "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
        "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
        "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100, "двести": 200,
        "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600, "семьсот": 700, "восемьсот": 800,
        "девятьсот": 900}
SCALES = (("тысяч", 1000), ("миллион", 10 ** 6), ("миллиард", 10 ** 9))
LOOK_DIGIT = set("оОOoзЗбБlIдДSsB")        # letters that stand in for digits in bad reads
LAT, CYR = re.compile(r"[A-Za-z]"), re.compile(r"[А-Яа-яЁё]")


def inn_ok(s: str) -> bool:
    d = [int(c) for c in s]
    if len(d) == 10:
        return d[9] == sum(a * b for a, b in zip(d, (2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10
    if len(d) == 12:
        n1 = sum(a * b for a, b in zip(d, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10
        n2 = sum(a * b for a, b in zip(d, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10
        return d[10] == n1 and d[11] == n2
    return False


def ogrn_ok(s: str) -> bool:
    if len(s) == 13:
        return int(s[:12]) % 11 % 10 == int(s[12])
    if len(s) == 15:
        return int(s[:14]) % 13 % 10 == int(s[14])
    return False


def words_to_int(text: str) -> int | None:
    """'сорок восемь тысяч пятьсот' -> 48500; None when it is not a number in words."""
    total = part = 0
    seen = False
    for w in re.findall(r"[а-яё]+", text.lower()):
        if w in ONES:
            part += ONES[w]
            seen = True
            continue
        for stem, mult in SCALES:
            if w.startswith(stem):
                total += (part or 1) * mult
                part = 0
                seen = True
                break
        else:
            return None
    return total + part if seen else None


def check_line(text: str, conf: float = 1.0) -> list[str]:
    """Reasons to doubt the line (empty list: nothing suspicious)."""
    why: list[str] = []
    for m in re.finditer(r"(ИНН|КПП|ОГРНИП|ОГРН|БИК|р/с|р/сч|к/с)[\s:№]*([0-9A-Za-zА-Яа-яЁё]{5,25})", text):
        label, val = m.group(1), m.group(2)
        if label != "КПП" and not val.isdigit():
            if any(c in LOOK_DIGIT or c.isalpha() for c in val):
                why.append(f"{label}: в номере есть буквы ({val})")
            continue
        if label == "ИНН" and not inn_ok(val):
            why.append(f"ИНН {val}: не сходится контрольное число или неверная длина")
        elif label in ("ОГРН", "ОГРНИП") and not ogrn_ok(val):
            why.append(f"{label} {val}: не сходится контрольное число или неверная длина")
        elif label == "КПП" and not re.fullmatch(r"\d{4}[0-9A-Z]{2}\d{3}", val):
            why.append(f"КПП {val}: должно быть 9 знаков")
        elif label == "БИК" and not re.fullmatch(r"04\d{7}", val):
            why.append(f"БИК {val}: должно быть 9 цифр, начинается с 04")
        elif label in ("р/с", "р/сч", "к/с") and len(val) != 20:
            why.append(f"{label} {val}: должно быть 20 цифр")
    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text):
        try:
            date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            why.append(f"дата {m.group(0)} не существует")
    for m in re.finditer(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text):
        mon = MONTHS.get(m.group(2).lower())
        if mon:
            try:
                date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                why.append(f"дата {m.group(0)} не существует")
    # sum in digits against the same sum in words
    for m in re.finditer(r"(\d[\d\s ]*\d)(?:[,.](\d{2}))?\s*\(([^)]*)\)", text):
        num = int(re.sub(r"\D", "", m.group(1)))
        val = words_to_int(m.group(3))
        if val is not None and val != num:
            why.append(f"сумма {m.group(1)} не совпадает с прописью ({m.group(3).strip()})")
    # digits that are really letters, and words mixing Latin and Cyrillic letters
    for tok in re.findall(r"\S+", text):
        core = tok.strip(".,;:()«»\"'")
        if len(core) < 2:
            continue
        if LAT.search(core) and CYR.search(core):
            why.append(f"«{core}»: латинские и русские буквы вперемешку")
        elif re.search(r"\d", core) and re.fullmatch(r"[\d,.оОзЗбlIO]+", core) and re.search(r"[оОзЗбlIO]", core):
            why.append(f"«{core}»: в числе похоже на букву")
    if conf < 0.8:
        why.append(f"низкая уверенность распознавания ({conf:.0%})")
    seen, out = set(), []
    for w in why:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out
