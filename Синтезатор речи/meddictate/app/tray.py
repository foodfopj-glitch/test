# -*- coding: utf-8 -*-
"""
Значок в системном трее и его меню.
"""
from __future__ import annotations

import os

from .qt import QAction, QApplication, QIcon, QMenu, QSystemTrayIcon

from . import config


def app_icon() -> QIcon:
    """Иконка приложения: из data/icon.ico, иначе рисуем на месте."""
    for name in ("icon.ico", "icon.png"):
        path = config.resource_path(name)
        if os.path.isfile(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    return _fallback_icon()


def _fallback_icon() -> QIcon:  # pragma: no cover
    from .qt import QColor, QPainter, QPixmap, Qt

    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2ecc71"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(6, 6, 52, 52)
    painter.setBrush(QColor("#0d1117"))
    painter.drawRoundedRect(26, 16, 12, 24, 6, 6)
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    """
    Меню трея. Все действия отдаются наружу через callbacks,
    чтобы логика осталась в main.py.
    """

    def __init__(self, window, on_quit) -> None:  # noqa: ANN001
        super().__init__(app_icon(), window)
        self.window = window
        self.setToolTip(f"{config.APP_TITLE} — диктовка медицинского текста")

        menu = QMenu()

        self.action_show = QAction("Показать окошко", menu)
        self.action_show.triggered.connect(self._show_window)
        menu.addAction(self.action_show)

        self.action_dictate = QAction("Включить диктовку", menu)
        menu.addAction(self.action_dictate)

        menu.addSeparator()

        self.action_mode = QAction("Режим: по горячей клавише", menu)
        menu.addAction(self.action_mode)

        self.action_settings = QAction("Настройки…", menu)
        menu.addAction(self.action_settings)

        self.action_about = QAction("О программе", menu)
        menu.addAction(self.action_about)

        self.action_quit = QAction("Выход", menu)
        self.action_quit.triggered.connect(on_quit)
        menu.addAction(self.action_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        if hasattr(self, "setQuitOnLastWindowClosed"):
            QApplication.setQuitOnLastWindowClosed(False)

    # ------------------------------------------------------------------ сервис
    def _show_window(self) -> None:
        self.window.show()
        self.window.raise_()

    def _on_activated(self, reason) -> None:  # noqa: ANN001
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.window.isVisible():
                self.window.hide()
            else:
                self._show_window()

    def notify(self, title: str, message: str) -> None:
        try:
            self.showMessage(title, message, app_icon(), 4000)
        except Exception:
            pass

    def set_dictating(self, active: bool, mode: str) -> None:
        self.action_dictate.setText("Остановить диктовку" if active else "Включить диктовку")
        self.action_mode.setText("Режим: непрерывно" if mode == "continuous"
                                 else "Режим: по горячей клавише")
        color = "🟢" if active else ("🎙" if mode == "hotkey" else "🔁")
        self.setToolTip(f"{config.APP_TITLE} {color}")
