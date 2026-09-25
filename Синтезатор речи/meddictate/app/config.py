# -*- coding: utf-8 -*-
"""
Настройки и пути. Всё хранится рядом с пользователем, а не рядом с exe:
    %APPDATA%\\MedDictate\\config.json
    %APPDATA%\\MedDictate\\terms_user.txt
    %APPDATA%\\MedDictate\\replacements_user.txt
    %APPDATA%\\MedDictate\\model\\   (модель, если её нет внутри exe)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields

APP_NAME = "MedDictate"
APP_TITLE = "МедДиктовка"
APP_VERSION = "1.0.0"

#: встроенная модель (то, что кладём в exe)
BUILTIN_MODEL_DIR = "vosk-model-small-ru-0.22"
BUILTIN_MODEL_URL = ("https://alphacephei.com/vosk/models/"
                     "vosk-model-small-ru-0.22.zip")
BIG_MODEL_DIR = "vosk-model-ru-0.42"
BIG_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip"


def app_dir() -> str:
    """Папка с данными пользователя."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def data_dir() -> str:
    """Папка со встроенными данными (словари, иконка)."""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "data")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def resource_path(*parts: str) -> str:
    return os.path.join(data_dir(), *parts)


def bundled_model_path() -> str:
    """Путь к модели внутри сборки exe (или None)."""
    if getattr(sys, "frozen", False):
        cand = os.path.join(getattr(sys, "_MEIPASS", ""), "model")
        if os.path.isdir(cand):
            return cand
    return ""


CONFIG_PATH = os.path.join(app_dir(), "config.json")
LOG_PATH = os.path.join(app_dir(), "meddictate.log")
USER_TERMS_PATH = os.path.join(app_dir(), "terms_user.txt")
USER_REPLACEMENTS_PATH = os.path.join(app_dir(), "replacements_user.txt")
LOCAL_MODEL_DIR = os.path.join(app_dir(), "model")


@dataclass
class Settings:
    """Пользовательские настройки (сохраняются в config.json)."""

    # --- режим работы
    mode: str = "hotkey"                 # hotkey | continuous
    hotkey_toggle: str = "Ctrl+Alt+Space"
    hotkey_continuous: str = "Ctrl+Alt+C"
    hotkey_undo: str = "Ctrl+Alt+Z"
    auto_stop_silence: float = 3.0       # сек тишины -> автостоп (0 = выключено)
    min_speech_len: float = 0.35         # короче этого не вставляем (защита от щелчка)

    # --- звук
    input_device: str = ""               # имя устройства или "" = по умолчанию
    vad: bool = True                     # не отправлять тишину в распознавание
    vad_threshold_db: float = -48.0
    gain: float = 1.0                    # усиление микрофона

    # --- распознавание
    model_name: str = BUILTIN_MODEL_DIR  # папка модели
    lexicon_gate: bool = True            # учитывать лексикон модели при правках

    # --- вставка текста
    insert_method: str = "unicode"       # unicode | scancode
    char_delay_ms: int = 0
    newline_enter: bool = False          # \n отправлять как Enter
    same_window_only: bool = True        # печатать только в то окно, где начали
    live_insert: bool = True             # печатать по мере распознавания

    # --- коррекция текста
    correction: bool = True
    threshold: float = 0.55
    numbers: bool = True                 # числа цифрами
    units: bool = True                   # мг, мл, %
    punctuation_commands: bool = True    # "запятая" -> ","
    capitalize_sentences: bool = True
    final_period: bool = True

    # --- окно
    overlay_x: int = -1
    overlay_y: int = -1
    overlay_visible: bool = True
    overlay_alpha: float = 0.94

    # --- системное
    autostart: bool = False
    start_minimized: bool = False

    def save(self, path: str = CONFIG_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str = CONFIG_PATH) -> "Settings":
        cfg = cls()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return cfg
        known = {f.name for f in fields(cls)}
        for key, value in raw.items():
            if key in known:
                setattr(cfg, key, value)
        return cfg


# --------------------------------------------------------------- автозапуск
_AUTORUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(enabled: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                exe = sys.executable if getattr(sys, "frozen", False) else \
                    f'"{sys.executable}" "{os.path.join(os.path.dirname(data_dir()), "main.py")}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}" --minimized')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def is_autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTORUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False
