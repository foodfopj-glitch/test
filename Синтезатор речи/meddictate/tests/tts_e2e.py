# -*- coding: utf-8 -*-
"""
Сквозной тест коррекции: синтез речи -> распознавание Vosk -> коррекция.

Требует: vosk с русской моделью в ./model и (для синтеза) piper-tts с
русским голосом. Запуск:
    python tests/tts_e2e.py                 # только проверка корректора
    python tests/tts_e2e.py --speak         # полный прогон через синтез речи
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from app.corrector import Corrector                       # noqa: E402
from app.dictionary import load_replacements, load_terms  # noqa: E402

PHRASES: list[tuple[str, bool]] = [
    ("Пациент жалуется на боль в груди и одышку при физической нагрузке. "
     "Температура тридцать восемь и пять. Объективно состояние средней тяжести. "
     "Артериальное давление сто сорок на девяносто.", True),
    ("Диагноз: внебольничная пневмония нижней доли правого лёгкого. "
     "Назначен амоксициллин по пятьсот миллиграмм два раза в день.", True),
    ("Рекомендованы спирография, эхокардиография и общий анализ крови. Явка через десять дней.", True),
    ("Жалобы на головную боль, головокружение и тошноту. Уровень сатурации девяносто восемь процентов.", True),
    ("Пациент с сахарным диабетом второго типа принимает метформин тысяча миллиграмм два раза в день.", True),
    ("Проведена фиброгастродуоденоскопия, выявлен эрозивный гастрит и дуоденит.", True),
    ("Артериальное давление сто тридцать на восемьдесят, частота сердечных сокращений семьдесят два удара в минуту.", True),
    ("Назначены цефтриаксон один грамм внутримышечно и омепразол двадцать миллиграмм утром.", True),
    ("В анализе крови гемоглобин сто двадцать, лейкоциты девять и два, СОЭ двадцать пять.", True),
    ("Больная отмечает снижение аппетита, потерю массы тела и общую слабость.", True),
    # контроль: обычная речь, словарь не должен ничего переделывать
    ("Сегодня мы обсудили план работы на неделю. Коллеги подготовили отчёт, и завтра у нас встреча.", False),
    ("Погода в Риге была тёплой, поэтому мы пошли гулять в парк возле дома.", False),
]


def build_corrector(model_path: str | None = None) -> tuple[Corrector, object | None]:
    terms = load_terms(os.path.join(ROOT, "data", "terms_med.txt"))
    reps = load_replacements(os.path.join(ROOT, "data", "replacements_med.txt"))
    model = None
    if model_path and os.path.isdir(model_path):
        import vosk
        vosk.SetLogLevel(-1)
        model = vosk.Model(model_path)
        for t in terms:
            t.in_lexicon = all(model.vosk_model_find_word(w) >= 0 for w in t.words)
    corr = Corrector(terms=terms, replacements=reps, threshold=0.55,
                     numbers=True, units=True, final_period=True)
    return corr, model


def synth(text: str, out_wav: str, voice: str) -> bool:
    """Синтез речи piper + приведение к 16 кГц моно."""
    import numpy as np
    raw = out_wav + ".raw.wav"
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "piper", "-m", voice, "-f", raw],
                       input=text.encode("utf-8"), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:  # pragma: no cover
        print("Синтез недоступен:", exc)
        return False
    with wave.open(raw) as w:
        sr, data = w.getframerate(), w.readframes(w.getnframes())
    x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    n = int(len(x) * 16000 / sr)
    xi = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(xi.tobytes())
    os.remove(raw)
    return True


def recognize(model, wav: str) -> str:
    import json
    import vosk
    rec = vosk.KaldiRecognizer(model, 16000)
    with wave.open(wav) as w:
        parts = []
        while True:
            data = w.readframes(4000)
            if not data:
                break
            if rec.AcceptWaveform(data):
                parts.append(json.loads(rec.Result()).get("text", ""))
        parts.append(json.loads(rec.FinalResult()).get("text", ""))
    return " ".join(p for p in parts if p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speak", action="store_true", help="прогнать через синтез речи")
    ap.add_argument("--model", default=os.path.join(ROOT, "model"))
    ap.add_argument("--voice", default=os.environ.get("PIPER_VOICE",
                    "/tmp/voices/ru_RU-dmitri-medium.onnx"))
    ap.add_argument("--tmp", default="/tmp/e2e")
    ap.add_argument("--fresh", action="store_true", help="перераспознать аудио заново")
    args = ap.parse_args()

    corr, model = build_corrector(args.model)
    print(f"Терминов загружено: {len(corr.terms)} | замен: {len(corr.replacements)}")
    if model is None:
        print("Модель не найдена — тест только корректора (--speak недоступен)")
        return 1

    os.makedirs(args.tmp, exist_ok=True)
    fixed_total = 0
    for idx, (phrase, medical) in enumerate(PHRASES, 1):
        cache = os.path.join(args.tmp, f"raw{idx}.txt")
        if not args.speak:
            raw = phrase
        elif os.path.isfile(cache) and not args.fresh:
            raw = open(cache, encoding="utf-8").read().strip()
        else:
            wav = os.path.join(args.tmp, f"p{idx}.wav")
            if not synth(phrase, wav, args.voice):
                return 1
            raw = recognize(model, wav)
            open(cache, "w", encoding="utf-8").write(raw)
        t0 = time.perf_counter()
        fixed = corr.process(raw, final=True)
        dt = (time.perf_counter() - t0) * 1000
        changed = raw.strip() != fixed.strip()
        if changed:
            fixed_total += 1
        kind = "мед." if medical else "КОНТРОЛЬ"
        print(f"\n--- {idx} ({kind}) {dt:.1f} мс ---")
        print("  распознано :", raw)
        print("  после      :", fixed)

    # замер скорости на длинном хвосте (для живого ввода)
    long_text = " ".join(p for p, _ in PHRASES[:8])
    t0 = time.perf_counter()
    for _ in range(20):
        corr.process(long_text, final=False)
    dt = (time.perf_counter() - t0) / 20 * 1000
    print(f"\nСкорость обработки длинного текста ({len(long_text.split())} слов): {dt:.2f} мс на обновление")
    print(f"Фраз изменено: {fixed_total}/{len(PHRASES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
