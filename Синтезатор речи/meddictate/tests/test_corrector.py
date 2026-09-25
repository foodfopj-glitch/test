# -*- coding: utf-8 -*-
"""
Тесты корректора: словарь терминов не должен портить обычный текст
и должен вытаскивать медицинские формулировки из ошибок распознавания.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.corrector import Corrector  # noqa: E402
from app.dictionary import load_replacements, load_terms  # noqa: E402


@pytest.fixture(scope="module")
def corrector() -> Corrector:
    terms = load_terms(os.path.join(ROOT, "data", "terms_med.txt"))
    reps = load_replacements(os.path.join(ROOT, "data", "replacements_med.txt"))
    return Corrector(terms=terms, replacements=reps, threshold=0.55, final_period=False)


@pytest.mark.parametrize("heard, want", [
    ("съем жалуется на боль в груди", "пациент жалуется"),
    ("диагноз не больничная пневмония", "внебольничная пневмония"),
    ("нижней доля правого лёгкого", "нижней доли"),
    ("назначена максим лента по пятьсот миллиграмм", "амоксициллин"),
    ("артериальное давление сто тридцать на восемьдесят", "130/80"),
    ("уровень с оторваться девяносто восемь процентов", "98%"),
])
def test_исправления(corrector: Corrector, heard: str, want: str):
    got = corrector.process(heard, final=True)
    assert want.lower() in got.lower(), f"{heard!r} -> {got!r}, ждали {want!r}"


@pytest.mark.parametrize("text", [
    "Погода в Риге была тёплой, поэтому мы пошли гулять в парк.",
    "Сегодня мы обсудили план работы на неделю.",
    "Артериальное давление 130/80, частота сердечных сокращений 72 в минуту.",
    "Пациент с сахарным диабетом второго типа принимает метформин 1000 мг.",
    "Жалобы на головную боль, головокружение и тошноту.",
])
def test_обычный_текст_не_меняется(corrector: Corrector, text: str):
    """Главное требование к корректору: НЕ портить уже правильный текст."""
    got = corrector.process(text, final=True).strip()
    assert got.lower().rstrip(".") == text.lower().rstrip("."), f"испортил: {got!r}"


def test_не_меняет_термин_на_термин(corrector: Corrector):
    """«цефтриаксон» не должен превращаться в «цефуроксим» - это разные препараты."""
    got = corrector.process("назначены цефтриаксон один грамм", final=True)
    assert "цефтриаксон" in got.lower()


def test_защита_незаконченного_слова(corrector: Corrector):
    """В потоке последние слова ещё могут измениться - их не трогаем."""
    live = corrector.process("назначена максим", final=False)
    assert "максим" in live.lower()             # при final=False не исправляем
    done = corrector.process("назначена максим лента", final=True)
    assert "амоксициллин" in done.lower()       # а после завершения фразы - исправляем


def test_журнал_правок(corrector: Corrector):
    corrector.process("назначена максим лента", final=True)
    assert any(c.written.lower() == "амоксициллин" for c in corrector.changes)
