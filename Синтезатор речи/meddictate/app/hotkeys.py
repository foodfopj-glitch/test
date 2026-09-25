# -*- coding: utf-8 -*-
"""
Глобальные горячие клавиши (Windows, RegisterHotKey).

Работает без прав администратора и не перехватывает клавиатуру целиком:
система сама сообщает нам, когда нажата наша комбинация. Для этого
поднимается отдельный поток с окном-«приёмником» сообщений.
"""
from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

#: имена клавиш, которые понимает окно настроек
_SPECIAL_KEYS = {
    "SPACE": 0x20, "TAB": 0x09, "RETURN": 0x0D, "ENTER": 0x0D, "ESC": 0x1B,
    "BACKSPACE": 0x08, "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PGUP": 0x21, "PGDOWN": 0x22, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
    "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
}
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    _SPECIAL_KEYS[_ch] = ord(_ch)


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+Space' -> (модификаторы, виртуальный код клавиши)."""
    mods = MOD_NOREPEAT
    vk = 0
    for raw in (text or "").replace(" ", "").split("+"):
        part = raw.upper()
        if part in {"CTRL", "CONTROL"}:
            mods |= MOD_CONTROL
        elif part == "ALT":
            mods |= MOD_ALT
        elif part == "SHIFT":
            mods |= MOD_SHIFT
        elif part in {"WIN", "SUPER", "META"}:
            mods |= MOD_WIN
        elif part:
            vk = _SPECIAL_KEYS.get(part, 0)
    return mods, vk


class HotkeyManager:
    """
    Регистрирует комбинации и вызывает колбэки из своего потока.

    :param hotkeys: {(id, комбинация): колбэк}
    """

    def __init__(self, hotkeys: Optional[dict[tuple[int, str], Callable[[], None]]] = None) -> None:
        self._hotkeys = hotkeys or {}
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.errors: list[str] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not IS_WINDOWS:
            self.errors.append("Глобальные клавиши работают только в Windows "
                               "(в режиме разработки используйте окошко программы).")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if IS_WINDOWS:
            try:
                import ctypes
                thread_id = getattr(self, "_thread_id", None)
                if thread_id:
                    ctypes.windll.user32.PostThreadMessageW(thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None

    # ---------------------------------------------------------- поток Windows
    def _run(self) -> None:  # pragma: no cover - выполняется только в Windows
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread_id = int(kernel32.GetCurrentThreadId())

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR),
                        ("lpszClassName", wintypes.LPCWSTR)]

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_HOTKEY:
                callback = self._callbacks.get(int(wparam))
                if callback:
                    try:
                        callback()
                    except Exception:
                        pass
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc = WNDPROC(wnd_proc)   # держим ссылку от сборщика мусора
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "MedDictateHotkeysWnd"
        user32.RegisterClassW(ctypes.byref(wc))
        hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "MedDictate", 0,
                                      0, 0, 0, 0, None, None, wc.hInstance, None)
        if not hwnd:
            self.errors.append("Не удалось создать окно горячих клавиш")
            return
        for (hotkey_id, combo), callback in self._hotkeys.items():
            mods, vk = parse_hotkey(combo)
            if not vk:
                self.errors.append(f"Не понял комбинацию: {combo}")
                continue
            if user32.RegisterHotKey(wintypes.HWND(hwnd), hotkey_id, mods, vk):
                self._callbacks[hotkey_id] = callback
            else:
                self.errors.append(f"Комбинация {combo} занята другой программой")

        msg = wintypes.MSG()
        while not self._stop.is_set():
            got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for hotkey_id in list(self._callbacks):
            user32.UnregisterHotKey(wintypes.HWND(hwnd), hotkey_id)
        user32.DestroyWindow(wintypes.HWND(hwnd))
