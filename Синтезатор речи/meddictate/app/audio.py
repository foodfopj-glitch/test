# -*- coding: utf-8 -*-
"""
Микрофон: захват 16 кГц моно, отсев тишины, индикатор уровня.

sounddevice выбран потому, что он тащит PortAudio внутри колеса и не
требует установки драйверов. Поток открывается только когда нужно
слушать, чтобы не держать микрофон занятым постоянно.
"""
from __future__ import annotations

import array
import math
import threading
import time
from collections import deque
from typing import Callable, Optional

SAMPLE_RATE = 16000
BLOCK = 4000          # 0.25 с - оптимальный шаг для Vosk
BYTES_PER_BLOCK = BLOCK * 2


def list_input_devices() -> list[tuple[int, str]]:
    """Список микрофонов: [(индекс, имя), ...]."""
    try:
        import sounddevice as sd
    except Exception:
        return []
    out: list[tuple[int, str]] = []
    try:
        for idx, dev in enumerate(sd.query_devices()):
            try:
                if dev.get("max_input_channels", 0) > 0:
                    out.append((idx, dev.get("name", f"Устройство {idx}")))
            except Exception:
                continue
    except Exception:
        return []
    return out


class LevelMeter:
    """Сглаженный уровень сигнала 0..1 для индикатора в окне."""

    def __init__(self) -> None:
        self._level = 0.0
        self._lock = threading.Lock()

    def push(self, rms: float) -> None:
        target = min(1.0, rms * 8.0)
        with self._lock:
            self._level = max(target, self._level * 0.75)

    @property
    def level(self) -> float:
        with self._lock:
            return self._level


class AudioEngine:
    """
    Держит поток с микрофона и отдаёт блоки вызывающему коду.

    :param on_block: функция(bytes, rms_db) - вызывается из потока PortAudio,
                     поэтому внутри нельзя делать тяжёлых операций.
    """

    def __init__(
        self,
        on_block: Callable[[bytes, float], None],
        device_name: str = "",
        gain: float = 1.0,
        vad: bool = True,
        vad_threshold_db: float = -48.0,
    ) -> None:
        self.on_block = on_block
        self.device_name = device_name
        self.gain = max(0.1, min(8.0, gain))
        self.vad = vad
        self.vad_threshold_db = vad_threshold_db
        self.meter = LevelMeter()
        self._stream = None
        self._lock = threading.Lock()
        self.last_loud_ts = time.time()
        self._recent: deque[float] = deque(maxlen=40)

    # ------------------------------------------------------------ устройства
    def _device_index(self) -> Optional[int]:
        if not self.device_name:
            return None
        for idx, name in list_input_devices():
            if name == self.device_name:
                return idx
        return None

    # --------------------------------------------------------------- поток
    def start(self) -> bool:
        with self._lock:
            if self._stream is not None:
                return True
            try:
                import sounddevice as sd
            except Exception:
                return False
            try:
                idx = self._device_index()
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK,
                    dtype="int16",
                    channels=1,
                    device=idx,
                    callback=self._callback,
                )
                self._stream.start()
                self.last_loud_ts = time.time()
                return True
            except Exception:
                self._stream = None
                return False

    def stop(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self._stream is not None

    # ------------------------------------------------------------ обработка
    def _callback(self, indata, _frames, _time_info, status) -> None:  # noqa: ANN001
        try:
            raw = bytes(indata)
        except Exception:
            return
        samples = array.array("h")
        samples.frombytes(raw)
        if self.gain != 1.0:
            for i, value in enumerate(samples):
                scaled = int(value * self.gain)
                samples[i] = -32768 if scaled < -32768 else 32767 if scaled > 32767 else scaled
        if samples:
            acc = 0
            for value in samples:
                acc += value * value
            rms = math.sqrt(acc / len(samples))
            db = 20 * math.log10(rms / 32768.0) if rms > 0 else -100.0
        else:
            db = -100.0
        self.meter.push(0.0 if db < -95 else 10 ** (db / 20.0))
        self._recent.append(db)
        speaking = db > self.vad_threshold_db
        if speaking:
            self.last_loud_ts = time.time()
        if self.vad and not speaking:
            # тишину в распознавание не отправляем, но оставляем «хвост»,
            # чтобы не обрезать конец слова
            if len(self._recent) >= 3 and max(self._recent) < self.vad_threshold_db:
                return
        try:
            self.on_block(samples.tobytes(), db)
        except Exception:
            pass

    # ------------------------------------------------------------- служебное
    def test_level(self, seconds: float = 2.0) -> float:
        """Замер уровня для кнопки «Проверить микрофон»."""
        peak = 0.0
        deadline = time.time() + seconds
        while time.time() < deadline:
            peak = max(peak, self.meter.level)
            time.sleep(0.05)
        return peak
