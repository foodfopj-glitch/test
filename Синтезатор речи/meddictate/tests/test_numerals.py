# -*- coding: utf-8 -*-
"""Тесты чисел, единиц измерения и форматирования."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.numerals import format_text, words_to_numbers  # noqa: E402


def test_простые_числительные():
    assert words_to_numbers("сто сорок два") == "142"
    assert words_to_numbers("две тысячи сто двадцать три") == "2123"
    assert words_to_numbers("тысяча двести") == "1200"
    assert words_to_numbers("пятьсот пятьдесят пять") == "555"
    assert words_to_numbers("двадцать пять тысяч рублей") == "25000 рублей"


def test_рядом_стоящие_числа_не_суммируются():
    # «лейкоциты девять два» - это показатель 9,2, а не 11
    assert words_to_numbers("лейкоциты девять два") == "лейкоциты 9 2"
    assert words_to_numbers("девять и два") == "9 и 2"


def test_температура_и_давление():
    assert "38,5" in format_text("температура тридцать восемь и пять", final_period=False)
    assert "140/90" in format_text("давление сто сорок на девяносто", final_period=False)
    assert "9,2" in format_text("лейкоциты девять два", final_period=False)


def test_единицы():
    assert "500 мг" in format_text("пятьсот миллиграмм", final_period=False)
    assert "98%" in format_text("девяносто восемь процентов", final_period=False)
    assert "38°" in format_text("тридцать восемь градусов", final_period=False)
    assert "70 кг" in format_text("семьдесят килограмм", final_period=False)
    assert "мг/кг" in format_text("два миллиграмм на килограмм", final_period=False)


def test_регистр_и_точка():
    text = format_text("пациент жалуется на боль. температура 38,5", final_period=True)
    assert text.startswith("Пациент")
    assert "Температура" in text
    assert text.endswith(".")


def test_обычный_текст_не_портится():
    src = "Погода была тёплой, мы пошли гулять в парк."
    assert format_text(src, final_period=False).strip() == src
