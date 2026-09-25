# -*- coding: utf-8 -*-
"""
Мини-окошко программы.

Небольшая плавающая панель поверх всех окон: состояние, индикатор уровня
микрофона, живой текст и кнопки управления. Окно не забирает фокус
(WindowDoesNotAcceptFocus), поэтому клик по кнопкам не мешает печати
в ЕМИАС/Word/браузер.
"""
from __future__ import annotations

from .qt import (QColor, QFont, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                  QLabel, QPainter, QPainterPath, QPoint, QPushButton, QSizePolicy,
                  Qt, QVBoxLayout, QWidget, Signal)

STATUS_STYLE = {
    "idle": ("Готов", "#8b98a8"),
    "listening": ("Слушаю…", "#2ecc71"),
    "paused": ("Пауза", "#f1c40f"),
    "blocked": ("Сменилось окно — печать на паузе", "#e67e22"),
    "error": ("Ошибка", "#e74c3c"),
    "loading": ("Готовлю модель…", "#3498db"),
}


class LevelBar(QWidget):
    """Индикатор уровня микрофона."""

    def __init__(self) -> None:
        super().__init__()
        self._level = 0.0
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_level(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._level) > 0.02:
            self._level = value
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 3, 3)
        painter.fillPath(path, QColor("#2b3440"))
        if self._level > 0.01:
            filled = QPainterPath()
            filled.addRoundedRect(0, 0, self.width() * self._level, self.height(), 3, 3)
            color = QColor("#2ecc71") if self._level < 0.85 else QColor("#e74c3c")
            painter.fillPath(filled, color)


class Overlay(QWidget):
    """Плавающая панель управления диктовкой."""

    toggled = Signal()
    mode_changed = Signal(str)
    settings_requested = Signal()
    hidden = Signal()
    copy_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, settings) -> None:  # noqa: ANN001
        super().__init__()
        self.settings = settings
        self._drag_pos: QPoint | None = None
        self._state = "idle"

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        except Exception:
            pass
        self.setFixedWidth(380)

        self._build_ui()
        self.set_state("idle")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card.setStyleSheet("""
            QFrame#card {
                background: rgba(24, 30, 38, 0.95);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }
            QLabel { color: #e8eef6; }
            QLabel#hint { color: #8b98a8; }
            QPushButton {
                background: rgba(255,255,255,0.07); color: #e8eef6;
                border: none; border-radius: 7px; padding: 4px 7px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.16); }
            QPushButton#mic[active="true"] { background: #2ecc71; color: #0d1117; }
            QPushButton#close:hover { background: #e74c3c; }
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        # --- строка 1: название и кнопки управления
        top = QHBoxLayout()
        top.setSpacing(4)
        title = QLabel("МедДиктовка")
        font = title.font()
        font.setPointSize(max(9, font.pointSize()))
        font.setBold(True)
        title.setFont(font)
        top.addWidget(title)
        top.addStretch(1)

        self.mic_btn = QPushButton("Вкл")
        self.mic_btn.setObjectName("mic")
        self.mic_btn.setFixedWidth(56)
        self.mic_btn.setToolTip("Включить/выключить диктовку")
        self.mic_btn.clicked.connect(self.toggled.emit)
        top.addWidget(self.mic_btn)

        gear = QPushButton("⚙")
        gear.setFixedWidth(30)
        gear.setToolTip("Настройки: микрофон, клавиши, словарь")
        gear.clicked.connect(self.settings_requested.emit)
        top.addWidget(gear)

        close = QPushButton("—")
        close.setObjectName("close")
        close.setFixedWidth(30)
        close.setToolTip("Свернуть окошко в трей (программа продолжит работать)")
        close.clicked.connect(self._on_hide)
        top.addWidget(close)
        card_layout.addLayout(top)

        # --- строка 2: состояние и переключатель режима
        state_row = QHBoxLayout()
        state_row.setSpacing(4)
        self.status = QLabel("Готов")
        self.status.setFont(QFont(self.status.font().family(), 9))
        state_row.addWidget(self.status)
        state_row.addStretch(1)

        self.mode_btn = QPushButton("🎙 клавиша")
        self.mode_btn.setFixedWidth(112)
        self.mode_btn.setToolTip("Режим: по горячей клавише или непрерывно")
        self.mode_btn.clicked.connect(self._on_mode_clicked)
        state_row.addWidget(self.mode_btn)
        card_layout.addLayout(state_row)

        # --- строка 3: текст, который распознаётся
        self.text = QLabel("Нажмите «Вкл» или Ctrl + Alt + Space и говорите")
        self.text.setObjectName("hint")
        self.text.setWordWrap(True)
        self.text.setMinimumHeight(34)
        self.text.setMaximumHeight(60)
        self.text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.text.setFont(QFont(self.text.font().family(), 10))
        card_layout.addWidget(self.text)

        # --- строка 4: уровень микрофона
        self.level = LevelBar()
        card_layout.addWidget(self.level)

        # --- строка 5: подсказка (сокращается) и кнопки действий
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setFont(QFont(self.hint.font().family(), 8))
        self.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.hint.setMinimumWidth(10)
        bottom.addWidget(self.hint, 1)

        self.undo_btn = QPushButton("Стереть")
        self.undo_btn.setFixedWidth(62)
        self.undo_btn.setToolTip("Удалить весь вставленный текст (Ctrl + Alt + Z)")
        self.undo_btn.clicked.connect(self.cancel_requested.emit)
        bottom.addWidget(self.undo_btn)

        self.copy_btn = QPushButton("Копия")
        self.copy_btn.setFixedWidth(58)
        self.copy_btn.setToolTip("Скопировать распознанный текст в буфер обмена")
        self.copy_btn.clicked.connect(self.copy_requested.emit)
        bottom.addWidget(self.copy_btn)
        card_layout.addLayout(bottom)

        root.addWidget(self.card)

    # -------------------------------------------------------------- внешний вид
    def _on_mode_clicked(self) -> None:
        new_mode = "continuous" if self.settings.mode == "hotkey" else "hotkey"
        self.settings.mode = new_mode
        self.set_mode(new_mode)
        self.mode_changed.emit(new_mode)

    def set_mode(self, mode: str) -> None:
        if mode == "continuous":
            self.mode_btn.setText("🔁 непрерывно")
            self.mode_btn.setToolTip("Непрерывный режим: слушает, пока не остановите")
        else:
            self.mode_btn.setText("🎙 клавиша")
            self.mode_btn.setToolTip("Диктовка по горячей клавише")

    def set_state(self, state: str) -> None:
        self._state = state
        label, color = STATUS_STYLE.get(state, STATUS_STYLE["idle"])
        self.status.setText(label)
        self.status.setStyleSheet(f"color: {color};")
        active = state == "listening"
        self.mic_btn.setText("Стоп" if active else "Вкл")
        self.mic_btn.setProperty("active", "true" if active else "false")
        self.mic_btn.style().unpolish(self.mic_btn)
        self.mic_btn.style().polish(self.mic_btn)
        if not active:
            self.level.set_level(0.0)
            self.level.update()

    def set_level(self, value: float) -> None:
        self.level.set_level(value)

    def set_text(self, text: str, placeholder: bool = False) -> None:
        shown = text.strip() or "…"
        if len(shown) > 260:
            shown = "…" + shown[-260:]
        self.text.setText(shown)
        self.text.setStyleSheet("color: #8b98a8;" if placeholder else "color: #e8eef6;")

    def set_hint(self, text: str) -> None:
        """Подсказка с сокращением по ширине окна (полный текст - в подсказке-тултипе)."""
        self._hint_full = text
        width = max(20, self.hint.width())
        shown = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width)
        self.hint.setText(shown)
        self.hint.setToolTip(text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if getattr(self, "_hint_full", ""):
            self.set_hint(self._hint_full)

    # ------------------------------------------------------------------ drag
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None:
            self._drag_pos = None
            self.settings.overlay_x = self.x()
            self.settings.overlay_y = self.y()
            self.settings.save()
            event.accept()

    def _on_hide(self) -> None:
        self.hide()
        self.hidden.emit()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Крестик не закрывает программу: окно уходит в трей."""
        event.ignore()
        self._on_hide()

    def restore_position(self) -> None:
        if self.settings.overlay_x >= 0 and self.settings.overlay_y >= 0:
            self.move(self.settings.overlay_x, self.settings.overlay_y)
        else:
            screen = self.screen().availableGeometry() if self.screen() else None
            if screen:
                self.move(screen.right() - self.width() - 30, screen.bottom() - 170)
