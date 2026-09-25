# -*- coding: utf-8 -*-
"""
Прогон всей цепочки без микрофона: WAV-файл подставляется вместо микрофона.

Полезно, чтобы проверить словарь и коррекцию на своём материале:

    python tools/simulate_dictation.py запись.wav
    python tools/simulate_dictation.py запись.wav --realtime   # как в жизни, с паузами

Файл должен быть 16 кГц, моно, 16 бит (такой получается из диктофона
или после конвертации: ffmpeg -i in.m4a -ar 16000 -ac 1 -c:a pcm_s16le out.wav).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config                                     # noqa: E402
from app.asr import AsrSession, build_corrector, install_bundled_model, model_available  # noqa: E402
from app.insert import TextInjector                        # noqa: E402

BLOCK = 4000        # 0.25 с


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", help="файл 16 кГц моно")
    parser.add_argument("--realtime", action="store_true", help="подавать звук в темпе записи")
    parser.add_argument("--plain", action="store_true", help="без коррекции (как слышит модель)")
    args = parser.parse_args()

    settings = config.Settings()
    settings.correction = not args.plain
    settings.live_insert = True
    settings.final_period = True

    import vosk
    vosk.SetLogLevel(-1)
    path = install_bundled_model() or model_available(settings.model_name)
    if not path:
        print("Модель не найдена. Сначала: python tools/fetch_model.py")
        return 1
    print("Модель:", path)
    model = vosk.Model(path)
    corrector = build_corrector(model, settings)
    print(f"Терминов: {len(corrector.terms)} (модель знает сама "
          f"{sum(1 for t in corrector.terms if t.in_lexicon)}), замен: {len(corrector.replacements)}")

    injector = TextInjector(console_echo=True)
    injector.session_start()

    state = {"final": ""}

    def on_partial(text: str) -> None:
        injector.update_text(text)

    def on_final(text: str) -> None:
        state["final"] = (state["final"] + " " + text).strip()
        injector.update_text(state["final"])

    session = AsrSession(model, corrector, on_partial, on_final,
                         on_error=lambda msg: print("\n[ошибка]", msg))

    with wave.open(args.wav) as handle:
        if handle.getframerate() != 16000 or handle.getnchannels() != 1:
            print(f"Внимание: ожидалось 16 кГц моно, а тут "
                  f"{handle.getframerate()} Гц, каналов {handle.getnchannels()}")
        print("\n--- печатаем текст (как в поле ввода) ---")
        session.start()
        while True:
            data = handle.readframes(BLOCK)
            if not data:
                break
            session.feed(data)
            if args.realtime:
                time.sleep(BLOCK / 16000)
        time.sleep(0.4)          # дать потоку доработать
    session.stop(flush=True)
    session.shutdown()

    print("\n\n--- итоговый текст ---")
    print(state["final"] or "(пусто)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
