# -*- coding: utf-8 -*-
"""
Распознавание речи: загрузка модели Vosk, поток декодирования, склейка
с корректором.

Особенности:
  * модель ищется внутри exe, рядом с программой или в профиле пользователя;
    если её нет - качается один раз из интернета с прогрессом;
  * декодирование идёт в отдельном потоке, UI не тормозит;
  * для живого ввода обрабатывается только текущий сегмент, поэтому
    текст появляется через доли секунды после начала фразы.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional

from . import config
from .corrector import Corrector
from .dictionary import load_replacements, load_terms

MODEL_URLS = {
    config.BUILTIN_MODEL_DIR: config.BUILTIN_MODEL_URL,
    config.BIG_MODEL_DIR: config.BIG_MODEL_URL,
}


# --------------------------------------------------------------------- модель
def model_available(model_name: str = "") -> str:
    """Возвращает путь к существующей модели или пустую строку."""
    name = model_name or config.BUILTIN_MODEL_DIR
    candidates = [
        os.path.join(config.LOCAL_MODEL_DIR, name),
        os.path.join(config.LOCAL_MODEL_DIR),
        config.bundled_model_path(),
        os.path.join(os.path.dirname(config.data_dir()), "model"),
    ]
    for path in candidates:
        if path and os.path.isfile(os.path.join(path, "am", "final.mdl")):
            return path
    return ""


def install_bundled_model(progress: Optional[Callable[[str], None]] = None) -> str:
    """
    Копирует модель из exe в профиль пользователя: так программа стартует
    за доли секунды, а не распаковывает 90 МБ при каждом запуске.
    """
    src = config.bundled_model_path()
    if not src:
        return ""
    dst = os.path.join(config.LOCAL_MODEL_DIR, os.path.basename(src))
    if os.path.isfile(os.path.join(dst, "am", "final.mdl")):
        return dst
    try:
        os.makedirs(dst, exist_ok=True)
        if progress:
            progress("Первый запуск: распаковка модели…")
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return dst
    except OSError:
        return src


def download_model(model_name: str, progress: Optional[Callable[[str], None]] = None) -> str:
    """Скачивает модель с сайта Vosk (нужен интернет, один раз)."""
    url = MODEL_URLS.get(model_name)
    if not url:
        raise RuntimeError(f"Неизвестная модель: {model_name}")
    os.makedirs(config.LOCAL_MODEL_DIR, exist_ok=True)
    archive = os.path.join(config.LOCAL_MODEL_DIR, model_name + ".zip")
    if progress:
        progress("Скачивание модели…")
    with urllib.request.urlopen(url, timeout=30) as resp, open(archive, "wb") as fh:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(f"Скачивание модели: {done * 100 // total}%")
    if progress:
        progress("Распаковка модели…")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(config.LOCAL_MODEL_DIR)
    os.remove(archive)
    return os.path.join(config.LOCAL_MODEL_DIR, model_name)


# ------------------------------------------------------------------ лексикон
class Lexicon:
    """Знает, какие слова модель умеет сама (кэшируется)."""

    def __init__(self, model) -> None:  # noqa: ANN001
        self._model = model
        self._cache: dict[str, bool] = {}

    def has(self, word: str) -> bool:
        found = self._cache.get(word)
        if found is None:
            try:
                found = self._model.vosk_model_find_word(word) >= 0
            except Exception:
                found = False
            self._cache[word] = found
        return found


def build_corrector(model, settings: config.Settings) -> Corrector:
    """Собирает корректор из встроенного словаря + пользовательских файлов."""
    terms = load_terms(config.resource_path("terms_med.txt"))
    terms += load_terms(config.USER_TERMS_PATH)
    replacements = load_replacements(config.resource_path("replacements_med.txt"))
    if settings.punctuation_commands:
        pass
    else:
        replacements = [r for r in replacements
                        if r.write not in {",", ".", ";", ":", "?", "!", "…", "—", "-",
                                           "(", ")", "«", "»", "\n", "\n\n"}]
    replacements += load_replacements(config.USER_REPLACEMENTS_PATH)
    corrector = Corrector(
        terms=terms,
        replacements=replacements,
        threshold=settings.threshold,
        numbers=settings.numbers,
        units=settings.units,
        capitalize_sentences=settings.capitalize_sentences,
        final_period=settings.final_period,
        enabled=settings.correction,
    )
    if model is not None and settings.lexicon_gate:
        lexicon = Lexicon(model)
        corrector.mark_lexicon(lexicon.has)
    return corrector


# --------------------------------------------------------------- распознавание
@dataclass
class Segment:
    text: str
    duration: float
    final: bool = True


class AsrSession:
    """
    Поток распознавания. Кормите его блоками через feed(), забирайте
    результат через callbacks.
    """

    def __init__(
        self,
        model,
        corrector: Corrector,
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
        on_error: Callable[[str], None] | None = None,
        min_speech_len: float = 0.35,
    ) -> None:
        self.model = model
        self.corrector = corrector
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_error = on_error or (lambda msg: None)
        self.min_speech_len = min_speech_len
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=200)
        self._thread: threading.Thread | None = None
        self._rec = None
        self._stop = threading.Event()
        self._last_partial = ""
        self.listening = False
        #: Vosk не потокобезопасен: любое обращение к распознавателю - только под замком,
        #: иначе остановка диктовки во время обработки блока роняет процесс
        self._rec_lock = threading.Lock()
        #: сколько секунд речи накоплено в текущем сегменте (для живого ввода)
        self._segment_seconds = 0.0
        #: раньше этого не печатаем «на лету»: первые догадки модели шумные
        self.min_live_seconds = 1.0
        #: сколько ждём обработку очереди при остановке
        self._drain_timeout = 2.0

    # ------------------------------------------------------------- жизненный
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            self.listening = True
            self.reset()
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="asr", daemon=True)
        self._thread.start()
        self.listening = True

    def stop(self, flush: bool = True) -> None:
        """
        Останавливает диктовку.

        Перед завершением дожидаемся, пока поток распознавания обработает
        всё, что уже пришло с микрофона, иначе последние слова пропадут.
        """
        self.listening = False
        if self._rec is None:
            return
        if flush:
            deadline = time.time() + self._drain_timeout
            while not self._queue.empty() and time.time() < deadline:
                time.sleep(0.02)
            with self._rec_lock:
                try:
                    result = json.loads(self._rec.FinalResult())
                except Exception as exc:  # noqa: BLE001
                    self.on_error(f"Ошибка завершения распознавания: {exc}")
                    result = {}
            text = self.corrector.process(result.get("text", ""), final=True)
            if text.strip():
                self.on_final(text.strip())
        self._last_partial = ""

    def shutdown(self) -> None:
        self.listening = False
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def reset(self) -> None:
        if self._rec is not None:
            with self._rec_lock:
                try:
                    self._rec.Reset()
                except Exception:
                    pass
        self._last_partial = ""
        self._segment_seconds = 0.0

    # ---------------------------------------------------------------- данные
    def feed(self, data: bytes) -> None:
        if not self.listening:
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            pass

    # ----------------------------------------------------------------- поток
    def _run(self) -> None:
        import vosk
        vosk.SetLogLevel(-1)
        try:
            self._rec = vosk.KaldiRecognizer(self.model, 16000)
            self._rec.SetWords(True)
        except Exception as exc:  # noqa: BLE001
            self.on_error(f"Не удалось создать распознаватель: {exc}")
            return
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                self._feed_block(item)
            except Exception as exc:  # noqa: BLE001
                self.on_error(f"Ошибка распознавания: {exc}")

    def _feed_block(self, data: bytes) -> None:
        self._segment_seconds += len(data) / 2 / 16000
        with self._rec_lock:
            accepted = self._rec.AcceptWaveform(data)
            payload = self._rec.Result() if accepted else self._rec.PartialResult()
        if accepted:
            result = json.loads(payload)
            words = result.get("result") or []
            duration = (words[-1]["end"] - words[0]["start"]) if words else 0.0
            text = result.get("text", "").strip()
            self._segment_seconds = 0.0
            if text and duration >= self.min_speech_len:
                self._last_partial = ""
                self.on_final(self.corrector.process(text, final=True))
            elif not text:
                self._last_partial = ""
        else:
            partial = json.loads(payload).get("partial", "").strip()
            if (partial and partial != self._last_partial
                    and self._segment_seconds >= self.min_live_seconds):
                self._last_partial = partial
                self.on_partial(self.corrector.process(partial, final=False))


class DictationController:
    """
    Логика «включить/выключить»: микрофон + распознавание + автостоп по тишине.
    UI только дёргает start()/stop() и читает состояние.
    """

    def __init__(
        self,
        settings: config.Settings,
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
        on_state: Callable[[str], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        from .audio import AudioEngine

        self.settings = settings
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_state = on_state
        self.on_error = on_error or (lambda msg: None)
        self.model = None
        self.corrector: Corrector | None = None
        self.session: AsrSession | None = None
        self.active = False
        self._auto_stop_after = settings.auto_stop_silence
        self.audio = AudioEngine(
            on_block=self._on_block,
            device_name=settings.input_device,
            gain=settings.gain,
            vad=settings.vad,
            vad_threshold_db=settings.vad_threshold_db,
        )

    # --------------------------------------------------------------- запуск
    def prepare(self, progress: Optional[Callable[[str], None]] = None) -> bool:
        """Готовит модель (может занять время при первом запуске)."""
        if self.model is not None:
            return True
        import vosk
        vosk.SetLogLevel(-1)
        path = install_bundled_model(progress) or model_available(self.settings.model_name)
        if not path:
            try:
                path = download_model(self.settings.model_name, progress)
            except Exception as exc:  # noqa: BLE001
                self.on_error(f"Не удалось получить модель: {exc}")
                return False
        if progress:
            progress("Загрузка модели…")
        try:
            self.model = vosk.Model(path)
        except Exception as exc:  # noqa: BLE001
            self.on_error(f"Модель не загрузилась: {exc}")
            return False
        self.corrector = build_corrector(self.model, self.settings)
        self.session = AsrSession(
            self.model, self.corrector, self.on_partial, self.on_final,
            self.on_error, self.settings.min_speech_len,
        )
        return True

    def rebuild_corrector(self) -> None:
        """Пересобрать корректор после правки словарей/настроек."""
        if self.model is not None:
            self.corrector = build_corrector(self.model, self.settings)
            if self.session:
                self.session.corrector = self.corrector

    # ------------------------------------------------------------- диктовка
    def start(self) -> bool:
        if not self.prepare():
            return False
        if self.active:
            return True
        if not self.audio.start():
            self.on_error("Не удалось открыть микрофон. Проверьте настройки звука.")
            return False
        if self.session:
            self.session.corrector = self.corrector
            self.session.start()
        self.active = True
        self.on_state("listening")
        return True

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        # сначала закрываем микрофон: тогда в очереди не появятся новые блоки
        self.audio.stop()
        if self.session:
            self.session.stop(flush=True)
        self.on_state("idle")

    def toggle(self) -> bool:
        if self.active:
            self.stop()
            return False
        return self.start()

    # ---------------------------------------------------------------- детали
    def _on_block(self, data: bytes, db: float) -> None:
        if self.session:
            self.session.feed(data)

    def silence_seconds(self) -> float:
        return max(0.0, time.time() - self.audio.last_loud_ts)

    def should_auto_stop(self) -> bool:
        return (self.active and self._auto_stop_after > 0
                and self.silence_seconds() > self._auto_stop_after)

    @property
    def level(self) -> float:
        return self.audio.meter.level
