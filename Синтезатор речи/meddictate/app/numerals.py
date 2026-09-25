# -*- coding: utf-8 -*-
"""
Числа, единицы измерения, пунктуация, регистр.

Диктовка медицинского текста почти всегда содержит числа: температуру,
давление, дозировки, показатели анализов. Vosk отдаёт их словами
("тридцать восемь и пять"), а в карте нужны цифры ("38,5").

Модуль работает полностью офлайн, без зависимостей и очень быстро.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- числа
_UNITS = {
    "ноль": 0, "нуль": 0, "один": 1, "одна": 1, "одно": 1, "одного": 1,
    "два": 2, "две": 2, "двух": 2, "три": 3, "трёх": 3, "трех": 3,
    "четыре": 4, "четырёх": 4, "четырех": 4, "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9,
}
_TEENS = {
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19,
}
_TENS = {
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400,
    "пятьсот": 500, "шестьсот": 600, "семьсот": 700, "восемьсот": 800,
    "девятьсот": 900,
}
_THOUSANDS = {"тысяча": 1, "тысячи": 1, "тысяч": 1, "тыща": 1}
_MILLIONS = {"миллион": 1, "миллиона": 1, "миллионов": 1, "млн": 1}

_NUM_WORDS = {}
for d in (_UNITS, _TEENS, _TENS, _HUNDREDS):
    _NUM_WORDS.update(d)

# слова, после которых "X и Y" означает десятичную дробь: "температура 38 и 5"
_DECIMAL_CONTEXT = (
    "температура", "температуры", "температурой", "темп",
    # лабораторные показатели: "лейкоциты девять и два" -> "9,2"
    "лейкоциты", "эритроциты", "тромбоциты", "гемоглобин", "гематокрит",
    "лимфоциты", "нейтрофилы", "эозинофилы", "базофилы", "моноциты",
    "соэ", "срб", "креатинин", "мочевина", "билирубин", "глюкоза",
    "сахар", "фибриноген", "ферритин", "альбумин", "белок", "сатурация",
)
_FRACTION_MARKERS = {"запятая", "точка", "целых", "целая"}

# ------------------------------------------------------- единицы измерения
# канонические сокращения: сколько слов и как писать
_UNIT_MAP = {
    "миллиграмм": "мг", "миллиграмма": "мг", "миллиграммов": "мг", "мг": "мг",
    "микрограмм": "мкг", "микрограмма": "мкг", "микрограммов": "мкг", "мкг": "мкг",
    "грамм": "г", "грамма": "г", "граммов": "г", "гр": "г",
    "миллилитр": "мл", "миллилитра": "мл", "миллилитров": "мл", "мл": "мл",
    "литр": "л", "литра": "л", "литров": "л",
    "миллимоль": "ммоль", "миллимоля": "ммоль", "миллимолей": "ммоль",
    "микромоль": "мкмоль", "микромолей": "мкмоль",
    "микроединиц": "мкЕД", "единиц": "ЕД", "единица": "ЕД", "единицы": "ЕД",
    "международных": "МЕ", "ме": "МЕ",
    "процент": "%", "процента": "%", "процентов": "%", "проц": "%",
    "градус": "°", "градуса": "°", "градусов": "°",
    "килограмм": "кг", "килограмма": "кг", "килограммов": "кг", "кг": "кг",
    "миллиграмм_на_децилитр": "мг/дл",
    "таблетка": "таб", "таблетки": "таб", "таблеток": "таб", "таб": "таб",
    "капсула": "капс", "капсулы": "капс", "капсул": "капс",
    "капля": "кап", "капли": "кап", "капель": "кап",
    "ампула": "амп", "ампулы": "амп", "ампул": "амп",
    "мешок": "меш", "мешки": "меш",
    "доза": "доза", "дозы": "доза", "дозе": "доза",
    # лабораторные
    "клеток": "кл", "клетки": "кл", "копий": "коп", "копии": "коп",
    "миллиметров": "мм", "миллиметр": "мм", "сантиметр": "см", "см": "см",
    "ударов": "уд", "удара": "уд", "вдохов": "вд",
}
# единицы, которые принято писать слитно с числом без пробела
_NO_SPACE_UNITS = {"%", "°"}
#: все служебные слова-единицы: используются как защита от правок
UNIT_WORDS = frozenset(_UNIT_MAP)
# единицы, между которыми ставится "/" ("мг на кг" -> "мг/кг")
_RATIO_UNITS = {"мг", "мкг", "мл", "г", "ЕД", "МЕ", "кап", "ммоль", "мг/дл", "кг"}

_NUMBER_RE = re.compile(r"^\d+([,.]\d+)?$")

_WORD_BOUNDARY = re.compile(r"[^\w]+", re.UNICODE)


def _is_num_token(tok: str) -> bool:
    return bool(_NUMBER_RE.match(tok)) or tok.lower().replace("ё", "е") in _NUM_WORDS


def words_to_numbers(text: str) -> str:
    """Преобразует словесные числительные в цифры: "сто сорок два" -> "142"."""
    tokens = text.split()
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        key = tok.lower().strip(".,;:!?").replace("ё", "е")
        if key in _NUM_WORDS or key in _THOUSANDS or key in _MILLIONS:
            value, j = _parse_number(tokens, i)
            if value is not None:
                # "38 и 5" после слова "температура" -> "38,5"
                out.append(_fmt(value))
                i = j
                continue
        out.append(tok)
        i += 1
    text = " ".join(out)
    # десятичная дробь через "запятая"
    text = re.sub(r"\b(\d+)\s+зап[яa]т[aа]я\s+(\d+)\b", r"\1,\2", text)
    text = re.sub(r"\b(\d+)\s+точка\s+(\d+)\b", r"\1.\2", text)
    # давление: "140 на 90" -> "140/90"
    text = re.sub(
        r"\b(\d{2,3})\s+на\s+(\d{2,3})\b",
        lambda m: f"{m.group(1)}/{m.group(2)}"
        if int(m.group(1)) >= 40 and int(m.group(2)) >= 30 and int(m.group(2)) < 200
        else m.group(0),
        text,
    )
    return text


#: уровень числительного: единицы=1, десятки=2, сотни=3, тысячи=4, миллионы=5
_LEVELS: dict[str, int] = {}
_LEVELS.update({w: 1 for w in _UNITS})
_LEVELS.update({w: 1 for w in _TEENS})
_LEVELS.update({w: 2 for w in _TENS})
_LEVELS.update({w: 3 for w in _HUNDREDS})
_LEVELS.update({w: 4 for w in _THOUSANDS})
_LEVELS.update({w: 5 for w in _MILLIONS})


def _parse_number(tokens: list[str], i: int) -> tuple[int | None, int]:
    """
    Собирает одно числительное, начиная с tokens[i].

    Правила живого русского счёта:
      * разряды идут по убыванию: «сто сорок два» -> 142;
      * «тысяча»/«миллион» умножают уже набранное: «две тысячи сто двадцать три» -> 2123;
      * два рядом стоящих простых числа - это два числа, а не сумма:
        «девять два» -> 9 и 2 (показатель 9,2).
    """
    total = 0
    current = 0          # текущая группа (до сотен)
    min_level = 9        # минимальный разряд в текущей группе
    j = i
    used = 0
    while j < len(tokens):
        key = tokens[j].lower().strip(".,;:!?").replace("ё", "е")
        level = _LEVELS.get(key)
        if level is None:
            break
        if level >= 4:                      # тысяча / миллион - умножают группу
            current = (current or 1) * (1000 if level == 4 else 1_000_000)
            total += current
            current = 0
            min_level = 9
            j += 1
            used += 1
            continue
        if level >= min_level:              # разряд не понижается -> это уже другое число
            break
        current += _NUM_WORDS[key]
        min_level = level
        j += 1
        used += 1
    if used == 0:
        return None, i
    value = total + current
    if value > 100_000_000:
        return None, i
    return value, j


def _fmt(value: int) -> str:
    return str(value)


def fractions_from_context(text: str) -> str:
    """
    "температура 38 и 5" -> "температура 38,5".
    Срабатывает только рядом со словом-подсказкой, чтобы не портить обычный текст.
    """
    def repl(m: re.Match) -> str:
        return f"{m.group(1)} {m.group(2)},{m.group(3)}"

    pattern = (
        r"\b(" + "|".join(_DECIMAL_CONTEXT) + r")\b([^.!?\n]{0,24}?)\b(\d{1,3})\s+и\s+(\d)\b"
    )
    return re.sub(pattern, lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)},{m.group(4)}", text,
                  flags=re.IGNORECASE)


def fractions_adjacent(text: str) -> str:
    """
    "лейкоциты 9 2" -> "лейкоциты 9,2", "температура 38 5" -> "38,5".
    Только сразу после слова-показателя и только для однозначной второй части.
    """
    def repl(m: re.Match) -> str:
        return f"{m.group(1)}{m.group(2)}{m.group(3)},{m.group(4)}"

    pattern = (
        r"\b(" + "|".join(_DECIMAL_CONTEXT) + r")\b(\s+(?:\S+\s+){0,3}?)(\d{1,3}) (\d)\b"
    )
    return re.sub(pattern, repl, text, flags=re.IGNORECASE)


def apply_units(text: str) -> str:
    """Сокращает единицы измерения и склеивает с числом: "500 миллиграмм" -> "500 мг"."""
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        key = tok.lower().strip(".,;:!?").replace("ё", "е")
        unit = _UNIT_MAP.get(key)
        if unit and i > 0 and _is_num_token(out[-1]):
            # "процентов" -> "%", "градусов" -> "°"
            if unit in _NO_SPACE_UNITS:
                out[-1] = out[-1] + unit
            else:
                out.append(unit)
            i += 1
            # "миллиграмм на килограмм" -> "мг/кг"
            if (i + 1 < len(tokens) and tokens[i].lower() == "на"
                    and unit in _RATIO_UNITS):
                nxt = _UNIT_MAP.get(tokens[i + 1].lower().strip(".,;:!?"))
                if nxt:
                    out[-1] = out[-1] + "/" + nxt
                    i += 2
            continue
        out.append(tok)
        i += 1
    text = " ".join(out)
    # "в 500 мг 2 раза" - убираем лишние пробелы перед знаком
    text = re.sub(r"\s+%", "%", text)
    text = re.sub(r"\s+°", "°", text)
    return text


# --------------------------------------------------------- пунктуация/регистр
_SENTENCE_END = re.compile(r"([.!?…])(\s+|$)")


def capitalize(text: str) -> str:
    """Заглавная в начале текста и после точки; одиночное "я" не трогаем."""
    if not text:
        return text
    text = _SENTENCE_END.sub(lambda m: m.group(1) + " " + m.group(2)[1:], text)
    text = re.sub(r"^\s*([а-яёa-z])", lambda m: m.group(1).upper(), text)
    text = re.sub(
        r"([.!?…]\s+)([а-яё])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )
    return text


def ensure_final_period(text: str, enabled: bool = True) -> str:
    if not enabled or not text.strip():
        return text
    stripped = text.rstrip()
    if stripped and stripped[-1] not in ".!?…:;,-":
        return stripped + "."
    return text


def tidy_spaces(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)
    # пробел после запятой/точки с запятой, но не внутри числа (38,5)
    text = re.sub(r"(?<![0-9])([,;:])(?=\S)", r"\1 ", text)
    return text


def format_text(
    text: str,
    numbers: bool = True,
    units: bool = True,
    capitalize_sentences: bool = True,
    final_period: bool = True,
) -> str:
    """Единая точка входа форматирования. Порядок важен."""
    if not text:
        return text
    if numbers:
        text = words_to_numbers(text)
        text = fractions_from_context(text)
        text = fractions_adjacent(text)
    if units:
        text = apply_units(text)
    if capitalize_sentences:
        text = capitalize(text)
    text = tidy_spaces(text)
    text = ensure_final_period(text, final_period)
    return text
