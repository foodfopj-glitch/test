# -*- coding: utf-8 -*-
"""
Приложение целиком: окошко, трей, микрофон, печать текста, настройки.
"""
from __future__ import annotations

import sys
import threading

from .qt import (QApplication, QGuiApplication, QMessageBox, QObject, QSystemTrayIcon,
                 QTimer, Signal)

from . import config

log = __import__("logging").getLogger("meddictate")
from .asr import DictationController
from .hotkeys import HotkeyManager
from .insert import TextInjector
from .overlay import Overlay
from .settings_dialog import SettingsDialog
from .tray import Tray


class Bridge(QObject):
    """Сигналы из рабочих потоков в поток интерфейса."""

    partial = Signal(str)
    final = Signal(str)
    state = Signal(str)
    error = Signal(str)
    progress = Signal(str)
    ready = Signal()


class Application:
    def __init__(self, args) -> None:  # noqa: ANN001
        self.args = args
        self.settings = config.Settings.load()
        # используем уже существующее приложение Qt, если оно есть
        # (важно для автотестов и повторного запуска внутри процесса)
        self.qt = QApplication.instance() or QApplication(sys.argv[:1])
        self.qt.setApplicationName(config.APP_NAME)
        self.qt.setApplicationDisplayName(config.APP_TITLE)
        self.qt.setQuitOnLastWindowClosed(False)

        self.ok = self._single_instance()
        if not self.ok:
            return

        self.bridge = Bridge()
        self.overlay = Overlay(self.settings)
        self.injector = TextInjector(
            method=self.settings.insert_method,
            char_delay_ms=self.settings.char_delay_ms,
            newline_enter=self.settings.newline_enter,
            same_window_only=self.settings.same_window_only,
            console_echo=self.args.dev,
        )
        self.controller = DictationController(
            self.settings,
            on_partial=self.bridge.partial.emit,
            on_final=self.bridge.final.emit,
            on_state=self.bridge.state.emit,
            on_error=self.bridge.error.emit,
        )
        self.committed = ""
        self.partial = ""
        self.last_text = ""
        self._preparing = False
        self._mic_test = None

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(self.overlay, self.quit)
        else:
            log.warning("Системный трей недоступен: окно не будет сворачиваться в трей")
        self.hotkeys = HotkeyManager({
            (1, self.settings.hotkey_toggle): self.toggle_dictation,
            (2, self.settings.hotkey_continuous): self.toggle_continuous,
            (3, self.settings.hotkey_undo): self.undo_insertion,
        })

        self._wire()
        self._start_timers()

        self.overlay.set_mode(self.settings.mode)
        self.overlay.restore_position()
        if not (self.args.minimized or self.settings.start_minimized):
            self.overlay.show()
        if self.tray:
            self.tray.show()
        self.hotkeys.start()
        for message in self.hotkeys.errors:
            self.overlay.set_hint(message)
        self.overlay.set_hint(self._hint_text())

    # ------------------------------------------------------------- один экземпляр
    def _single_instance(self) -> bool:
        from .qt import QLocalServer, QLocalSocket

        socket = QLocalSocket()
        socket.connectToServer(config.APP_NAME)
        if socket.waitForConnected(200):
            socket.write(b"show")
            socket.flush()
            socket.waitForBytesWritten(200)
            return False
        QLocalServer.removeServer(config.APP_NAME)
        self.server = QLocalServer()
        self.server.listen(config.APP_NAME)
        self.server.newConnection.connect(self._on_second_instance)
        return True

    def _on_second_instance(self) -> None:
        conn = self.server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(lambda: self._show_window())
            conn.disconnectFromServer()

    def _show_window(self) -> None:
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.activateWindow()

    # ---------------------------------------------------------------- связка
    def _wire(self) -> None:
        self.overlay.toggled.connect(self.toggle_dictation)
        self.overlay.settings_requested.connect(self.open_settings)
        self.overlay.copy_requested.connect(self.copy_last_text)
        self.overlay.cancel_requested.connect(self.undo_insertion)
        self.overlay.mode_changed.connect(self._on_mode_changed)
        self.overlay.hidden.connect(self._show_tray_hint)

        if self.tray:
            self.tray.action_dictate.triggered.connect(self.toggle_dictation)
            self.tray.action_mode.triggered.connect(self.toggle_continuous)
            self.tray.action_settings.triggered.connect(self.open_settings)
            self.tray.action_about.triggered.connect(self.show_about)

        self.bridge.partial.connect(self._on_partial)
        self.bridge.final.connect(self._on_final)
        self.bridge.state.connect(self._on_state)
        self.bridge.error.connect(self._on_error)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.ready.connect(self._start_dictation)

    def _start_timers(self) -> None:
        self.level_timer = QTimer()
        self.level_timer.setInterval(100)
        self.level_timer.timeout.connect(self._tick)
        self.level_timer.start()

    # ------------------------------------------------------------------ ввод
    def toggle_dictation(self) -> None:
        if self.controller.active:
            self.stop_dictation()
        else:
            self._prepare_and_start()

    def _prepare_and_start(self) -> None:
        if self.controller.model is not None:
            self._start_dictation()
            return
        if self._preparing:
            return
        self._preparing = True
        self.bridge.state.emit("loading")

        def worker() -> None:
            ok = self.controller.prepare(progress=self.bridge.progress.emit)
            self._preparing = False
            if ok:
                self.bridge.ready.emit()
            else:
                self.bridge.state.emit("error")

        threading.Thread(target=worker, name="prepare", daemon=True).start()

    def _start_dictation(self) -> None:
        self.committed = ""
        self.partial = ""
        self.last_text = ""
        self.injector.session_start()
        if not self.controller.start():
            return
        self.overlay.set_state("listening")
        if not self.overlay.isVisible():
            self.overlay.show()
        self._tray_state(True, self.settings.mode)

    def stop_dictation(self) -> None:
        self.controller.stop()
        self.injector.session_end()
        self.overlay.set_state("idle")
        self.overlay.set_text("", placeholder=True)
        self._tray_state(False, self.settings.mode)

    def toggle_continuous(self) -> None:
        """Горячая клавиша непрерывного режима: включить/выключить."""
        if self.controller.active and self.settings.mode == "continuous":
            self.stop_dictation()
            return
        self.settings.mode = "continuous"
        self.settings.save()
        self.overlay.set_mode("continuous")
        self._tray_state(self.controller.active, "continuous")
        self.overlay.set_hint(self._hint_text())
        self._prepare_and_start()

    def _on_mode_changed(self, mode: str) -> None:
        self.settings.save()
        self._tray_state(self.controller.active, mode)
        self.overlay.set_hint(self._hint_text())
        if mode == "continuous" and not self.controller.active:
            self._prepare_and_start()

    def undo_insertion(self) -> None:
        self.injector.undo_all()
        self.committed = ""
        self.partial = ""
        self.overlay.set_text("", placeholder=True)
        self.overlay.set_hint("Вставленный текст удалён")

    # --------------------------------------------------------------- события
    def _on_partial(self, text: str) -> None:
        self.partial = text
        self.overlay.set_text(text)
        self._show_changes()
        if self.settings.live_insert:
            self._push_text()

    def _on_final(self, text: str) -> None:
        self.partial = ""
        self.committed = (self.committed + " " + text).strip()
        self.last_text = self.committed
        self.overlay.set_text(self.committed)
        self._show_changes()
        self._push_text()

    def _push_text(self) -> None:
        full = self.committed
        if self.partial:
            full = (full + " " + self.partial).strip()
        if not full:
            return
        ok = self.injector.update_text(full)
        if not ok and self.injector.blocked_focus:
            self.overlay.set_state("blocked")
            self.overlay.set_hint("Печать приостановлена: активно другое окно")

    def _show_changes(self) -> None:
        """
        Показывает, какие слова программа исправила. Подстановки с низкой
        уверенностью помечаются «проверьте» - чтобы врач не пропустил
        сомнительное исправление (например, название препарата).
        """
        corrector = self.controller.corrector
        if corrector is None:
            return
        changes = [c for c in list(getattr(corrector, "changes", ())) if c.kind == "термин"]
        if not changes:
            self.overlay.set_hint(self._hint_text())
            return
        parts = []
        for item in changes[-2:]:
            prefix = "проверьте: " if item.score < 0.80 else ""
            parts.append(f"{prefix}«{item.heard}» → «{item.written}»")
        self.overlay.set_hint("Исправлено: " + "; ".join(parts))
        for item in changes:
            log.info("правка: %r -> %r (%.2f)", item.heard, item.written, item.score)

    def _on_state(self, state: str) -> None:
        self.overlay.set_state(state)
        self._tray_state(state == "listening", self.settings.mode)

    def _on_error(self, message: str) -> None:
        self.overlay.set_state("error")
        self.overlay.set_hint(message)
        log_error(message)

    def _on_progress(self, message: str) -> None:
        self.overlay.set_state("loading")
        self.overlay.set_hint(message)

    def _tray_state(self, active: bool, mode: str) -> None:
        if self.tray:
            self.tray.set_dictating(active, mode)

    def _tick(self) -> None:
        """Обновление индикатора, автостоп по тишине."""
        if self._mic_test is not None:
            self._mic_test_pump()
        if not self.controller.active:
            return
        self.overlay.set_level(self.controller.level)
        if self.injector.blocked_focus and self.injector.focus_ok():
            self.overlay.set_state("listening")
            self.overlay.set_hint(self._hint_text())
            self._push_text()
        if self.controller.should_auto_stop():
            self.stop_dictation()
            self.overlay.set_hint("Диктовка остановлена после тишины")

    def _show_tray_hint(self) -> None:
        if not self.tray:
            return
        self.tray.notify(config.APP_TITLE,
                         "Программа свёрнута в трей. Ctrl+Alt+Space — включить диктовку.")

    def _hint_text(self) -> str:
        if self.settings.mode == "continuous":
            return f"Непрерывный режим: {self.settings.hotkey_continuous} — пауза/продолжить"
        return f"{self.settings.hotkey_toggle} — начать/остановить диктовку"

    # ------------------------------------------------------------- служебное
    def copy_last_text(self) -> None:
        text = (self.committed + " " + self.partial).strip()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self.overlay.set_hint("Скопировано в буфер обмена")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.overlay,
                                on_test_mic=self._start_mic_test,
                                on_lexicon_check=self._lexicon_stats,
                                level_provider=lambda: self.controller.level)
        if dialog.exec():
            self._apply_settings()

    def _start_mic_test(self, device: str) -> None:
        from .audio import AudioEngine
        if self._mic_test is not None:
            self._mic_test.stop()
        engine = AudioEngine(on_block=lambda *_: None, device_name=device,
                             vad=False)
        engine.start()
        self._mic_test = engine

    def _mic_test_pump(self) -> None:
        engine = self._mic_test
        if engine is None:
            return
        # тест сам останавливается через 6 секунд
        if not hasattr(self, "_mic_test_started"):
            import time
            self._mic_test_started = time.time()
        import time
        if time.time() - self._mic_test_started > 6.0:
            engine.stop()
            self._mic_test = None
            del self._mic_test_started

    def _lexicon_stats(self) -> tuple[int, int]:
        if self.controller.corrector is None:
            self.controller.prepare()
        terms = self.controller.corrector.terms
        known = sum(1 for t in terms if t.in_lexicon)
        return len(terms), len(terms) - known

    def _apply_settings(self) -> None:
        s = self.settings
        s.save()
        was_active = self.controller.active
        self.stop_dictation()
        self.injector = TextInjector(
            method=s.insert_method, char_delay_ms=s.char_delay_ms,
            newline_enter=s.newline_enter, same_window_only=s.same_window_only,
            console_echo=self.args.dev,
        )
        self.controller.audio.device_name = s.input_device
        self.controller.audio.gain = s.gain
        self.controller.audio.vad = s.vad
        self.controller.audio.vad_threshold_db = s.vad_threshold_db
        self.controller.rebuild_corrector()
        self.hotkeys.stop()
        self.hotkeys = HotkeyManager({
            (1, s.hotkey_toggle): self.toggle_dictation,
            (2, s.hotkey_continuous): self.toggle_continuous,
            (3, s.hotkey_undo): self.undo_insertion,
        })
        self.hotkeys.start()
        self.overlay.set_mode(s.mode)
        self.overlay.set_hint(self._hint_text())
        if was_active:
            self._prepare_and_start()

    def show_about(self) -> None:
        QMessageBox.information(
            self.overlay, "О программе",
            f"{config.APP_TITLE} {config.APP_VERSION}\n\n"
            "Распознавание русской медицинской речи офлайн (движок Vosk).\n"
            "Словарь терминов, числа и дозировки приводятся к виду, принятому\n"
            "в медицинских записях. Интернет не нужен.\n\n"
            f"Словарь пользователя: {config.USER_TERMS_PATH}\n"
            f"Журнал: {config.LOG_PATH}",
        )

    def quit(self) -> None:
        try:
            self.stop_dictation()
            if self.controller.session is not None:
                self.controller.session.shutdown()
            self.controller.audio.stop()
            self.hotkeys.stop()
            if self.tray:
                self.tray.hide()
        except Exception:
            pass
        self.qt.quit()

    def run(self) -> int:
        if not self.ok:
            return 0
        try:
            return self.qt.exec()
        except KeyboardInterrupt:
            return 0


def log_error(message: str) -> None:
    import logging
    logging.getLogger("meddictate").error(message)
