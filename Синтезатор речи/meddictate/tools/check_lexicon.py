# -*- coding: utf-8 -*-
"""
Отчёт: какие термины словаря модель распознавания знает сама, а какие нет.

Для терминов, которых нет в лексиконе модели, включается фонетический
«спасатель» (низкий порог). Для известных - высокий порог, чтобы не
портить правильно услышанные слова.

Запуск:  python tools/check_lexicon.py [путь_к_модели]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.dictionary import load_terms  # noqa: E402


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "model")
    if not os.path.isdir(model_path):
        print(f"Не найдена модель: {model_path}\nСкачать: python tools/fetch_model.py")
        return 1

    import vosk
    vosk.SetLogLevel(-1)
    model = vosk.Model(model_path)

    terms = load_terms(os.path.join(root, "data", "terms_med.txt"))
    user = load_terms(os.path.join(root, "data", "terms_user.txt"))
    terms += user

    known, unknown = [], []
    cache: dict[str, bool] = {}

    def is_word(w: str) -> bool:
        if w not in cache:
            cache[w] = model.vosk_model_find_word(w) >= 0
        return cache[w]

    for term in terms:
        (known if all(is_word(w) for w in term.words) else unknown).append(term.text)

    print(f"Всего терминов: {len(terms)}")
    print(f"  модель знает сама:      {len(known)}")
    print(f"  спасатель работает на:  {len(unknown)}")
    report = os.path.join(root, "data", "lexicon_report.txt")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write("# Отчёт: термины, которых нет в лексиконе модели "
                 "(для них активен фонетический спасатель)\n")
        for t in sorted(unknown):
            fh.write(t + "\n")
        fh.write("\n# --- модель знает сама ---\n")
        for t in sorted(known):
            fh.write(t + "\n")
    print(f"Отчёт: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
