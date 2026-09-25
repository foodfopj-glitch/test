# -*- coding: utf-8 -*-
"""
Точка входа программы «МедДиктовка».

Собирает всё вместе: микрофон → распознавание → коррекция → печать в
активное окно, плюс окошко, трей, горячие клавиши и настройки.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import config

log = logging.getLogger("meddictate")


# --------------------------------------------------------------- самопроверка
def self_test() -> int:
    """Быстрая проверка корректора и чисел без микрофона."""
    from .corrector import Corrector
    from .dictionary import load_replacements, load_terms
    from .numerals import format_text

    print("МедДиктовка", config.APP_VERSION, "— самопроверка\n")

    cases_number = [
        ("температура тридцать восемь и пять", "температура 38,5"),
        ("давление сто сорок на девяносто", "давление 140/90"),
        ("пятьсот миллиграмм два раза в день", "500 мг 2 раза в день"),
        ("лейкоциты девять и два", "лейкоциты 9,2"),
        ("девяносто восемь процентов", "98%"),
        ("две тысячи сто двадцать три", "2123"),
    ]
    ok = True
    print("Числа и единицы:")
    for src, want in cases_number:
        got = format_text(src, final_period=False).rstrip(".").strip()
        mark = "ок " if want.lower() in got.lower() else "!! "
        ok &= want.lower() in got.lower()
        print(f"  {mark}{src}  ->  {got}")

    terms = load_terms(config.resource_path("terms_med.txt"))
    terms += load_terms(config.USER_TERMS_PATH)
    reps = load_replacements(config.resource_path("replacements_med.txt"))
    corrector = Corrector(terms=terms, replacements=reps, threshold=0.55,
                          final_period=False)
    cases_corr = [
        ("съем жалуется на боль", "пациент жалуется"),
        ("нижней доля правого лёгкого", "нижней доли"),
        ("артериальное давление сто тридцать на восемьдесят", "130/80"),
        ("максим лента по пятьсот миллиграмм", "амоксициллин"),
        ("в не больничная пневмония", "внебольничная"),
    ]
    print("\nМедицинские формулировки:")
    for src, want in cases_corr:
        got = corrector.process(src, final=True)
        mark = "ок " if want.lower() in got.lower() else "!! "
        print(f"  {mark}{src}\n     -> {got}")

    print("\nЗащита обычного текста (меняться не должно):")
    for src in ["Погода была тёплой, мы пошли гулять в парк.",
                "Сегодня обсудили план работы на неделю."]:
        got = corrector.process(src, final=True).strip()
        same = got.lower().rstrip(".") == src.lower().rstrip(".")
        ok &= same
        print(f"  {'ок ' if same else '!! '}{got}")
    print("\nГотово. Ошибок:", "нет" if ok else "см. строки с «!!»")
    return 0


def model_check() -> int:
    """Отчёт, какие термины словаря модель знает сама."""
    from .asr import build_corrector, install_bundled_model, model_available
    import vosk
    vosk.SetLogLevel(-1)
    path = install_bundled_model() or model_available()
    if not path:
        print("Модель не найдена. Запустите программу один раз или выполните "
              "tools/fetch_model.py")
        return 1
    model = vosk.Model(path)
    corrector = build_corrector(model, config.Settings())
    known = sum(1 for t in corrector.terms if t.in_lexicon)
    print(f"Всего терминов: {len(corrector.terms)}")
    print(f"  модель знает сама:   {known}")
    print(f"  спасает словарь:     {len(corrector.terms) - known}")
    print(f"Замен и команд: {len(corrector.replacements)}")
    return 0


# --------------------------------------------------------------------- запуск
def main(argv: list[str] | None = None) -> int:
    # в сборке без консоли sys.stdout/sys.stderr равны None: печать упала бы
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    parser = argparse.ArgumentParser(prog="meddictate", description=config.APP_TITLE)
    parser.add_argument("--selftest", action="store_true", help="проверка корректора без микрофона")
    parser.add_argument("--model-check", action="store_true", help="отчёт по словарю и модели")
    parser.add_argument("--minimized", action="store_true", help="запустить свёрнутым в трей")
    parser.add_argument("--dev", action="store_true", help="печатать текст в консоль (разработка)")
    args = parser.parse_args(argv)

    if args.selftest:
        return self_test()
    if args.model_check:
        return model_check()

    logging.basicConfig(
        filename=config.LOG_PATH, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8",
    )

    def _hook(exc_type, exc_value, exc_tb):
        logging.getLogger("meddictate").error("Неожиданная ошибка",
                                              exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
    if args.dev and sys.platform != "win32":
        logging.getLogger().addHandler(logging.StreamHandler())
        print("Режим разработки: текст будет печататься в консоль.")

    try:
        from .app import Application
    except ImportError as exc:
        print("Не найден Qt (PySide6 или PyQt6). Выполните: pip install -r requirements.txt")
        print("Подробность:", exc)
        return 1
    return Application(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
