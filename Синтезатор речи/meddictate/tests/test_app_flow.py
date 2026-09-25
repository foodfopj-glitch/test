# -*- coding: utf-8 -*-
"""
Проверка всего приложения целиком: звук -> распознавание -> коррекция -> печать.

Микрофон подменяется файлом-записью, поэтому тест работает без звуковой карты
и без Windows. Требует PySide6 или PyQt6 и русскую модель в model/, иначе пропускается.
"""
from __future__ import annotations

import os
import sys
import time
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytest.importorskip("app.qt")
WAV = os.path.join(ROOT, "tests", "data", "speech.wav")
MODEL = os.path.join(ROOT, "model")

pytestmark = [
    pytest.mark.skipif(not os.path.isdir(MODEL), reason="нет русской модели в model/"),
    pytest.mark.skipif(not os.path.isfile(WAV), reason="нет tests/data/speech.wav"),
]


class FakeAudio:
    """Замена микрофона: отдаёт запись из файла."""

    def __init__(self) -> None:
        self.device_name = ""
        self.gain = 1.0
        self.vad = False
        self.vad_threshold_db = -48.0
        self.last_loud_ts = time.time()
        self.running = False
        self.level = 0.0

        class _Meter:
            level = 0.3

        self.meter = _Meter()

    def start(self) -> bool:
        self.running = True
        return True

    def stop(self) -> None:
        self.running = False


def test_полный_путь_диктовки():
    from app.qt import QApplication

    from app import config
    from app.app import Application

    os.environ["APPDATA"] = "/tmp/meddictate_test"        # изолируем настройки
    os.environ["HOME"] = os.environ.get("HOME", "/tmp")
    config.CONFIG_PATH = os.path.join("/tmp/meddictate_test", "config.json")

    if QApplication.instance() is None:
        QApplication([])

    args = type("Args", (), {"dev": True, "minimized": True})()
    application = Application(args)
    # микрофон и печать подменяем: проверяем логику, а не драйверы
    application.controller.audio = FakeAudio()
    application.injector.console_echo = False
    application.injector.target_pid = None
    application.injector.same_window_only = False

    # «поле ввода»: записываем всё, что печатает программа, и учитываем стирания
    field = {"text": ""}
    application.injector.type_text = lambda text: field.__setitem__("text", field["text"] + text)
    application.injector.backspace = lambda count: field.__setitem__(
        "text", field["text"][:-count] if count <= len(field["text"]) else "")

    assert application.controller.prepare(), "модель не подготовилась"
    assert application.controller.corrector is not None

    application._start_dictation()
    assert application.controller.active

    def pump(seconds: float) -> None:
        """В реальной программе цикл событий крутится сам, в тесте — выполняем его руками."""
        end = time.time() + seconds
        while time.time() < end:
            QApplication.processEvents()
            time.sleep(0.01)

    with wave.open(WAV) as handle:
        while True:
            block = handle.readframes(4000)
            if not block:
                break
            application.controller._on_block(block, -20.0)
    pump(1.5)
    application.stop_dictation()          # здесь договаривается остаток фразы
    pump(0.5)

    printed = field["text"]
    print("\nНапечатано:", printed)
    assert printed, "текст не напечатался"
    assert printed.lower().startswith("пациент"), printed
    # числа и единицы приведены к медицинскому виду
    assert "38,5" in printed, printed
    assert "140/90" in printed, printed
    assert "пациент жалуется" in printed.lower()
