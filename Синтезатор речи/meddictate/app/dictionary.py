# -*- coding: utf-8 -*-
"""
Словарь: термины, фразы-шаблоны, жёсткие замены.

Пользовательские файлы лежат рядом с настройками и подхватываются
автоматически при старте:
    terms_user.txt         - свои термины (по одному в строке)
    replacements_user.txt  - свои замены вида  слышно = нужно

Строки, начинающиеся с '#', игнорируются. Пустые строки игнорируются.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable


def normalize_word(w: str) -> str:
    """Нижний регистр, ё->е, только буквы/цифры."""
    w = w.lower().replace("ё", "е")
    return re.sub(r"[^\w]+", "", w, flags=re.UNICODE)


@dataclass
class Term:
    """Термин словаря: одно слово или словосочетание."""
    text: str
    words: list[str] = field(default_factory=list)   # нормализованные слова
    in_lexicon: bool = False                          # знает ли модель это слово сама
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.words:
            self.words = [normalize_word(w) for w in self.text.split() if normalize_word(w)]

    @property
    def n_words(self) -> int:
        return len(self.words)


@dataclass
class Replacement:
    """Жёсткая замена: услышали -> пишем. Сравнение по словам, без регистра."""
    heard: list[str]
    write: str

    @property
    def n_words(self) -> int:
        return len(self.heard)


def _strip_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    return line.rstrip("\n")


def load_terms(path: str) -> list[Term]:
    terms: list[Term] = []
    if not path or not os.path.isfile(path):
        return terms
    with open(path, "r", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = _strip_comment(raw).strip()
            if not line:
                continue
            line = line.split("#", 1)[0].strip() if " #" in line else line
            if not line:
                continue
            terms.append(Term(text=line))
    return terms


def load_replacements(path: str) -> list[Replacement]:
    """Формат строки: `слышим = пишем`  (может быть несколько слов слева)."""
    reps: list[Replacement] = []
    if not path or not os.path.isfile(path):
        return reps
    with open(path, "r", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = _strip_comment(raw).strip()
            if not line or "=" not in line:
                continue
            left, right = line.split("=", 1)
            heard = [normalize_word(w) for w in left.split() if normalize_word(w)]
            right = right.strip().replace("\\n", "\n")
            if not heard:
                continue
            # перевод служебных обозначений
            right = (right.replace("<пробел>", " ").replace("<enter>", "\n")
                          .replace("<nl>", "\n"))
            reps.append(Replacement(heard=heard, write=right))
    # длинные фразы должны срабатывать раньше коротких
    reps.sort(key=lambda r: r.n_words, reverse=True)
    return reps


def merge_terms(*groups: Iterable[Term]) -> list[Term]:
    """Объединяет списки терминов, убирая дубликаты (по нормализованному тексту)."""
    seen: set[str] = set()
    out: list[Term] = []
    for group in groups:
        for term in group:
            key = " ".join(term.words)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(term)
    return out
