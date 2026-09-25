# -*- coding: utf-8 -*-
"""
Вставка текста в активное поле.

Печатаем ровно туда, где стоит курсор, «как будто вы набираете руками»:
через SendInput с юникод-символами (работает в ЕМИАС, Word, браузере,
мессенджерах). Текст печатается по мере распознавания, а не в конце,
поэтому важно уметь аккуратно исправлять хвост: если модель уточнила
слово - стираем несколько символов и печатаем заново.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

# --------------------------------------------------------------------- WinAPI
if IS_WINDOWS:  # pragma: no cover - работает только на Windows
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_SCANCODE = 0x0008
    VK_BACK = 0x08
    VK_LSHIFT = 0xA0
    VK_RETURN = 0x0D
    VK_CONTROL = 0x11
    VK_V = 0x56

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
        item = INPUT(type=INPUT_KEYBOARD)
        item.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
        return item

    def _send(items: list["INPUT"]) -> int:
        if not items:
            return 0
        arr = (INPUT * len(items))(*items)
        return int(user32.SendInput(len(items), arr, ctypes.sizeof(INPUT)))

    def foreground_window() -> int:
        return int(user32.GetForegroundWindow())

    def window_pid(hwnd: int) -> int:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value)
else:  # dev-режим на не-Windows: пишем в консоль
    def foreground_window() -> int:  # noqa: D103
        return 0

    def window_pid(_hwnd: int) -> int:  # noqa: D103
        return 0


# -------------------------------------------------------------------- вставка
class TextInjector:
    """
    Печатает текст в активное окно и умеет «переписывать» хвост.

    :param method: unicode (по умолчанию) | scancode | clipboard
    """

    #: сколько символов максимум стираем при уточнении текста
    MAX_BACKSPACE = 120

    def __init__(
        self,
        method: str = "unicode",
        char_delay_ms: int = 0,
        newline_enter: bool = False,
        same_window_only: bool = True,
        console_echo: bool = False,
    ) -> None:
        self.method = method
        self.char_delay_ms = max(0, char_delay_ms)
        self.newline_enter = newline_enter
        self.same_window_only = same_window_only
        self.console_echo = console_echo or not IS_WINDOWS
        self.typed = ""            # что, по нашей уверенности, уже напечатано
        self.target_pid: Optional[int] = None
        self.blocked_focus = False

    # ------------------------------------------------------------- сессия
    def session_start(self) -> None:
        self.typed = ""
        self.blocked_focus = False
        if IS_WINDOWS:
            hwnd = foreground_window()
            pid = window_pid(hwnd) if hwnd else None
            # если нажатие пришло из нашего же окошка - цель не считаем заданной,
            # иначе печать заблокируется сразу после клика по кнопке «Вкл»
            self.target_pid = None if pid == os.getpid() else pid
        else:
            self.target_pid = None

    def session_end(self) -> None:
        self.typed = ""

    def focus_ok(self) -> bool:
        if not IS_WINDOWS or not self.same_window_only or self.target_pid is None:
            return True
        hwnd = foreground_window()
        if not hwnd:
            return False
        return window_pid(hwnd) == self.target_pid

    # -------------------------------------------------------------- печать
    def type_text(self, text: str) -> None:
        if not text:
            return
        if self.console_echo:
            sys.stdout.write(text)
            sys.stdout.flush()
        if not IS_WINDOWS:
            return
        if self.method == "clipboard":
            self._paste_clipboard(text)
            return
        for chunk in self._split_enter(text):
            if chunk == "\n":
                self._send_special(0x0D)
                continue
            self._send_chars(chunk)

    def backspace(self, count: int) -> None:
        if count <= 0:
            return
        if self.console_echo:
            sys.stdout.write("\b" * count + " " * count + "\b" * count)
            sys.stdout.flush()
        if not IS_WINDOWS:
            return
        for _ in range(count):
            self._send_special(0x08)
            if self.char_delay_ms:
                time.sleep(self.char_delay_ms / 1000.0)

    # -------------------------------------------------------------- основное
    def update_text(self, new_text: str) -> bool:
        """
        Приводит текст в поле к new_text. Возвращает False, если напечатать
        не удалось (например, сменилось окно).
        """
        if not self.focus_ok():
            self.blocked_focus = True
            return False
        self.blocked_focus = False
        old = self.typed
        if new_text == old:
            return True
        if not old:
            self.type_text(new_text)
            self.typed = new_text
            return True
        if new_text.startswith(old):
            self.type_text(new_text[len(old):])
            self.typed = new_text
            return True
        common = _common_prefix(old, new_text)
        diff = len(old) - common
        if diff <= self.MAX_BACKSPACE:
            self.backspace(diff)
            self.type_text(new_text[common:])
            self.typed = new_text
            return True
        # расхождение слишком глубоко: скорее всего текст правили руками.
        # Ничего не ломаем - печатаем только новый хвост, если он однозначен.
        tail = new_text[len(old):] if new_text.startswith(old) else ""
        if tail:
            self.type_text(tail)
            self.typed = new_text
        return True

    def undo_all(self) -> None:
        """Стереть всё, что напечатали в этой сессии (Ctrl+Alt+Z)."""
        if self.focus_ok():
            self.backspace(len(self.typed))
        self.typed = ""

    # ------------------------------------------------------------- механика
    def _split_enter(self, text: str) -> list[str]:
        if not self.newline_enter:
            return [text.replace("\n", " ")]
        parts: list[str] = []
        buffer = ""
        for ch in text:
            if ch == "\n":
                parts.append(buffer)
                parts.append("\n")
                buffer = ""
            else:
                buffer += ch
        parts.append(buffer)
        return [p for p in parts if p]

    def _send_chars(self, text: str) -> None:
        if self.method == "scancode" and all(ord(c) < 128 for c in text):
            items = []
            for ch in text:
                vk = user32.VkKeyScanW(ord(ch))
                if vk == -1:
                    continue
                code = vk & 0xFF
                shift = (vk >> 8) & 0xFF
                if shift & 1:
                    items.append(_key_input(VK_LSHIFT, 0x2A, KEYEVENTF_SCANCODE))  # Shift вниз
                items.append(_key_input(code, 0, 0))
                items.append(_key_input(code, 0, KEYEVENTF_KEYUP))
                if shift & 1:
                    items.append(_key_input(VK_LSHIFT, 0x2A,
                                            KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP))
            _send(items)
            return
        # юникод-ввод: работает для любых языков и раскладок
        items = []
        raw = text.encode("utf-16-le")
        for idx in range(0, len(raw), 2):
            code = raw[idx] | (raw[idx + 1] << 8)
            items.append(_key_input(0, code, KEYEVENTF_UNICODE))
            items.append(_key_input(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        if self.char_delay_ms:
            # печатаем порциями, если пользователь просил медленнее
            step = max(2, 200 // max(1, self.char_delay_ms))
            for i in range(0, len(items), step):
                _send(items[i:i + step])
                time.sleep(self.char_delay_ms * step / 1000.0 / 2)
        else:
            _send(items)

    def _send_special(self, vk: int) -> None:  # noqa: D102
        _send([_key_input(vk, 0, 0), _key_input(vk, 0, KEYEVENTF_KEYUP)])

    def _paste_clipboard(self, text: str) -> None:
        """
        Вставка через буфер обмена (для очень больших фрагментов).

        Буфер заполняем средствами Qt: он сам корректно управляет памятью
        клипборда. Ручной WinAPI здесь опасен - система может обратиться к
        уже освобождённой памяти.
        """
        try:
            from .qt import QGuiApplication
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(text)
            else:
                return
        except Exception:
            return
        _send([_key_input(VK_CONTROL, 0, 0), _key_input(VK_V, 0, 0),
               _key_input(VK_V, 0, KEYEVENTF_KEYUP),
               _key_input(VK_CONTROL, 0, KEYEVENTF_KEYUP)])


def _common_prefix(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    idx = 0
    while idx < limit and a[idx] == b[idx]:
        idx += 1
    return idx
