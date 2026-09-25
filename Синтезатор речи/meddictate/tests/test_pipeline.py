# -*- coding: utf-8 -*-
"""
Интеграционные тесты: распознавание аудио + живая печать в «экран».

Тест с аудио требует модель в model/ и файл tests/data/speech.wav
(он создаётся скриптом tests/tts_e2e.py --speak). Без них тест пропускается.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.corrector import Corrector  # noqa: E402
from app.dictionary import load_replacements, load_terms  # noqa: E402
from app.insert import TextInjector  # noqa: E402


class FakeInjector(TextInjector):
    """TextInjector, который «печатает» в строку вместо Windows-окна."""

    def __init__(self) -> None:
        super().__init__(console_echo=False)
        self.screen = ""
        self.backspaces = 0

    def type_text(self, text: str) -> None:      # noqa: D102
        self.screen += text

    def backspace(self, count: int) -> None:     # noqa: D102
        self.backspaces += count
        self.screen = self.screen[:-count] if count <= len(self.screen) else ""

    def focus_ok(self) -> bool:                  # noqa: D102
        return True


@pytest.fixture()
def corrector() -> Corrector:
    terms = load_terms(os.path.join(ROOT, "data", "terms_med.txt"))
    reps = load_replacements(os.path.join(ROOT, "data", "replacements_med.txt"))
    return Corrector(terms=terms, replacements=reps, threshold=0.55, final_period=True)


def test_живая_печать_дописывает_без_стирания(corrector: Corrector):
    """Если распознавание только добавляет слова, стирать ничего не нужно."""
    injector = FakeInjector()
    injector.session_start()
    for partial in ["Пациент", "Пациент жалуется", "Пациент жалуется на боль"]:
        injector.update_text(partial)
    assert injector.screen == "Пациент жалуется на боль"
    assert injector.backspaces == 0


def test_живая_печать_переписывает_хвост(corrector: Corrector):
    """Когда корректор заменил слово, хвост переписывается, а не дублируется."""
    injector = FakeInjector()
    injector.session_start()
    injector.update_text(corrector.process("назначена максим", final=False))
    assert "максим" in injector.screen
    injector.update_text(corrector.process("назначена максим лента", final=True))
    assert "амоксициллин" in injector.screen.lower()
    assert "максим" not in injector.screen.lower()
    assert injector.backspaces > 0          # хвост действительно перепечатывался


def test_коррекция_во_время_живой_печати(corrector: Corrector):
    """Исправление термина происходит ещё до конца фразы."""
    injector = FakeInjector()
    injector.session_start()
    injector.update_text(corrector.process("назначена максим лента", final=True))
    assert "амоксициллин" in injector.screen.lower()


def test_слишком_большое_расхождение_не_ломает_текст():
    """Если текст правили руками, программа не должна стирать чужое."""
    injector = FakeInjector()
    injector.session_start()
    injector.update_text("Первое предложение.")
    injector.screen = "Совсем другой текст, который написал врач."
    injector.update_text("Первое предложение. Второе.")
    assert injector.screen.startswith("Совсем другой текст")


# --------------------------------------------------------------------- аудио
MODEL = os.path.join(ROOT, "model")
WAV = os.path.join(ROOT, "tests", "data", "speech.wav")


@pytest.mark.skipif(not os.path.isdir(MODEL), reason="нет модели в model/")
@pytest.mark.skipif(not os.path.isfile(WAV), reason="нет tests/data/speech.wav")
def test_распознавание_аудио(corrector: Corrector):
    """
    Полный конвейер: WAV -> Vosk -> корректор.
    Проверяем, что медицинские термины и числа приведены к нужному виду.
    """
    import json
    import wave

    import vosk
    vosk.SetLogLevel(-1)
    model = vosk.Model(MODEL)
    for term in corrector.terms:
        term.in_lexicon = all(model.vosk_model_find_word(w) >= 0 for w in term.words)

    rec = vosk.KaldiRecognizer(model, 16000)
    parts = []
    with wave.open(WAV) as handle:
        while True:
            data = handle.readframes(4000)
            if not data:
                break
            if rec.AcceptWaveform(data):
                parts.append(json.loads(rec.Result()).get("text", ""))
        parts.append(json.loads(rec.FinalResult()).get("text", ""))
    raw = " ".join(p for p in parts if p)
    assert raw, "модель ничего не распознала"
    text = corrector.process(raw, final=True)
    print("\nраспознано:", raw)
    print("после коррекции:", text)
    assert any(term in text.lower() for term in
               ("пневмония", "давление", "температура", "анализ")), text
    assert "/" in text or "%" in text or any(ch.isdigit() for ch in text), \
        "числа не приведены к цифрам"
