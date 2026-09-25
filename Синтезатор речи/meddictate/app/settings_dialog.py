# -*- coding: utf-8 -*-
"""
Окно настроек: микрофон, режим, горячие клавиши, вставка, коррекция, словарь.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                 QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                 QSlider, QSpinBox, QTabWidget, QTimer, Qt, QVBoxLayout, QWidget)

from . import config


def _open_in_editor(path: str) -> None:
    """Открывает файл словаря в блокноте (создаёт, если нет)."""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# Свои термины: по одному в строке.\n"
                     "# Пример:\n# апиксабан\n# фиброгастродуоденоскопия\n")
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class SettingsDialog(QDialog):
    def __init__(self, settings: config.Settings, parent=None,
                 on_test_mic=None, on_lexicon_check=None,
                 level_provider=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_test_mic = on_test_mic
        self.on_lexicon_check = on_lexicon_check
        self.level_provider = level_provider or (lambda: 0.0)
        self._mic_test_until = 0

        self.setWindowTitle("Настройки — " + config.APP_TITLE)
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        tabs = QTabWidget(self)
        tabs.addTab(self._tab_general(), "Основное")
        tabs.addTab(self._tab_sound(), "Звук")
        tabs.addTab(self._tab_insert(), "Вставка")
        tabs.addTab(self._tab_correction(), "Коррекция")
        tabs.addTab(self._tab_dictionary(), "Словарь")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self._mic_timer = QTimer(self)
        self._mic_timer.setInterval(120)
        self._mic_timer.timeout.connect(self._update_mic_level)

    # ------------------------------------------------------------- вкладки
    def _tab_general(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.mode = QComboBox()
        self.mode.addItem("По горячей клавише (нажал — говоришь)", "hotkey")
        self.mode.addItem("Непрерывно (слушает постоянно)", "continuous")
        self.mode.setCurrentIndex(0 if self.settings.mode == "hotkey" else 1)
        form.addRow("Режим по умолчанию:", self.mode)

        hk = QGroupBox("Горячие клавиши (глобальные)")
        hk_form = QFormLayout(hk)
        self.hk_toggle = QLineEdit(self.settings.hotkey_toggle)
        self.hk_continuous = QLineEdit(self.settings.hotkey_continuous)
        self.hk_undo = QLineEdit(self.settings.hotkey_undo)
        hk_form.addRow("Вкл/выкл диктовку:", self.hk_toggle)
        hk_form.addRow("Вкл/выкл непрерывный режим:", self.hk_continuous)
        hk_form.addRow("Отменить вставленный текст:", self.hk_undo)
        form.addRow(hk)

        self.autostart = QCheckBox("Запускать вместе с Windows")
        self.autostart.setChecked(config.is_autostart_enabled())
        form.addRow(self.autostart)

        self.start_minimized = QCheckBox("При запуске скрывать окошко в трей")
        self.start_minimized.setChecked(self.settings.start_minimized)
        form.addRow(self.start_minimized)

        hint = QLabel("Формат комбинации: Ctrl + Alt + Space, Ctrl + Shift + D, Alt + F9 …")
        hint.setStyleSheet("color: #666;")
        form.addRow(hint)
        return page

    def _tab_sound(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        row = QHBoxLayout()
        self.device = QComboBox()
        self.device.setMinimumWidth(280)
        self._fill_devices()
        row.addWidget(self.device)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self._fill_devices)
        row.addWidget(refresh)
        form.addRow("Микрофон:", row)

        self.gain = QDoubleSpinBox()
        self.gain.setRange(0.5, 4.0)
        self.gain.setSingleStep(0.1)
        self.gain.setValue(self.settings.gain)
        form.addRow("Усиление микрофона:", self.gain)

        self.vad = QCheckBox("Не отправлять тишину в распознавание (меньше ложного текста)")
        self.vad.setChecked(self.settings.vad)
        form.addRow(self.vad)

        self.vad_db = QDoubleSpinBox()
        self.vad_db.setRange(-80.0, -20.0)
        self.vad_db.setSingleStep(2.0)
        self.vad_db.setValue(self.settings.vad_threshold_db)
        self.vad_db.setSuffix(" дБ")
        form.addRow("Порог тишины:", self.vad_db)

        self.auto_stop = QDoubleSpinBox()
        self.auto_stop.setRange(0.0, 30.0)
        self.auto_stop.setSingleStep(0.5)
        self.auto_stop.setValue(self.settings.auto_stop_silence)
        self.auto_stop.setSuffix(" с (0 = выключено)")
        form.addRow("Автостоп после тишины:", self.auto_stop)

        test_row = QHBoxLayout()
        self.mic_test = QPushButton("Проверить микрофон")
        self.mic_test.clicked.connect(self._start_mic_test)
        test_row.addWidget(self.mic_test)
        self.mic_level = QLabel("—")
        test_row.addWidget(self.mic_level)
        test_row.addStretch(1)
        form.addRow(test_row)
        return page

    def _tab_insert(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.method = QComboBox()
        self.method.addItem("Символы (работает везде)", "unicode")
        self.method.addItem("Скан-коды клавиш (для старых программ)", "scancode")
        self.method.addItem("Через буфер обмена (для очень длинного текста)", "clipboard")
        self.method.setCurrentIndex({"unicode": 0, "scancode": 1, "clipboard": 2}
                                    .get(self.settings.insert_method, 0))
        form.addRow("Способ вставки:", self.method)

        self.live = QCheckBox("Печатать текст сразу, не дожидаясь конца фразы")
        self.live.setChecked(self.settings.live_insert)
        form.addRow(self.live)

        self.char_delay = QSpinBox()
        self.char_delay.setRange(0, 200)
        self.char_delay.setValue(self.settings.char_delay_ms)
        self.char_delay.setSuffix(" мс (0 = максимально быстро)")
        form.addRow("Пауза между символами:", self.char_delay)

        self.newline = QCheckBox("«Новая строка» отправлять клавишей Enter")
        self.newline.setChecked(self.settings.newline_enter)
        form.addRow(self.newline)

        self.same_window = QCheckBox("Печатать только в то окно, где начали диктовку")
        self.same_window.setChecked(self.settings.same_window_only)
        form.addRow(self.same_window)
        return page

    def _tab_correction(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.correction = QCheckBox("Исправлять термины по словарю")
        self.correction.setChecked(self.settings.correction)
        form.addRow(self.correction)

        self.threshold = QSlider(Qt.Orientation.Horizontal)
        self.threshold.setRange(45, 80)
        self.threshold.setValue(int(self.settings.threshold * 100))
        self.threshold_label = QLabel(f"{self.settings.threshold:.2f}")
        self.threshold.valueChanged.connect(
            lambda v: self.threshold_label.setText(f"{v / 100:.2f}"))
        row = QHBoxLayout()
        row.addWidget(self.threshold)
        row.addWidget(self.threshold_label)
        form.addRow("Строгость исправлений:", row)

        self.lexicon_gate = QCheckBox("Считать лексикон модели (безопаснее, меньше правок)")
        self.lexicon_gate.setChecked(self.settings.lexicon_gate)
        form.addRow(self.lexicon_gate)

        self.numbers = QCheckBox("Числа цифрами («температура тридцать восемь и пять» → «38,5»)")
        self.numbers.setChecked(self.settings.numbers)
        form.addRow(self.numbers)

        self.units = QCheckBox("Сокращать единицы («пятьсот миллиграмм» → «500 мг»)")
        self.units.setChecked(self.settings.units)
        form.addRow(self.units)

        self.punct = QCheckBox("Голосовые знаки («запятая», «точка», «новая строка»)")
        self.punct.setChecked(self.settings.punctuation_commands)
        form.addRow(self.punct)

        self.capitalize = QCheckBox("Заглавная буква в начале фраз")
        self.capitalize.setChecked(self.settings.capitalize_sentences)
        form.addRow(self.capitalize)

        self.period = QCheckBox("Точка в конце текста")
        self.period.setChecked(self.settings.final_period)
        form.addRow(self.period)
        return page

    def _tab_dictionary(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        info = QLabel(
            "Словарь отвечает за медицинские термины. Он состоит из двух частей:\n"
            "  • встроенный список (препараты, диагнозы, исследования, шаблоны осмотра);\n"
            "  • ваши файлы terms_user.txt и replacements_user.txt — их можно править\n"
            "    прямо сейчас, программа подхватит изменения после сохранения.\n\n"
            "Формат terms_user.txt: по одному термину в строке.\n"
            "Формат replacements_user.txt:  слышно = писать   (можно несколько слов)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        btn_terms = QPushButton("Открыть terms_user.txt")
        btn_terms.clicked.connect(lambda: _open_in_editor(config.USER_TERMS_PATH))
        row.addWidget(btn_terms)
        btn_repl = QPushButton("Открыть replacements_user.txt")
        btn_repl.clicked.connect(lambda: _open_in_editor(config.USER_REPLACEMENTS_PATH))
        row.addWidget(btn_repl)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        btn_check = QPushButton("Проверить словарь под модель")
        btn_check.clicked.connect(self._run_lexicon_check)
        row2.addWidget(btn_check)
        self.lexicon_result = QLabel("")
        self.lexicon_result.setStyleSheet("color: #666;")
        row2.addWidget(self.lexicon_result)
        row2.addStretch(1)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        btn_folder = QPushButton("Открыть папку программы")
        btn_folder.clicked.connect(lambda: _open_in_editor(config.app_dir()))
        row3.addWidget(btn_folder)
        layout.addLayout(row3)

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------- служебное
    def _fill_devices(self) -> None:
        from .audio import list_input_devices
        current = self.device.currentData() if self.device.count() else self.settings.input_device
        self.device.clear()
        self.device.addItem("По умолчанию (системный)", "")
        for _idx, name in list_input_devices():
            self.device.addItem(name, name)
        index = self.device.findData(current)
        self.device.setCurrentIndex(index if index >= 0 else 0)

    def _start_mic_test(self) -> None:
        if self.on_test_mic:
            self.on_test_mic(self.device.currentData() or "")
        self._mic_test_until = 40          # ~5 секунд по 120 мс
        self.mic_test.setText("Слушаю… говорите")
        self._mic_timer.start()

    def _update_mic_level(self) -> None:
        if self._mic_test_until <= 0:
            self._mic_timer.stop()
            self.mic_test.setText("Проверить микрофон")
            self.mic_level.setText("—")
            return
        self._mic_test_until -= 1
        level = max(0.0, min(1.0, float(self.level_provider() or 0.0)))
        self.mic_level.setText(("█" * int(level * 20)).ljust(20, "░"))

    def _run_lexicon_check(self) -> None:
        if not self.on_lexicon_check:
            return
        self.lexicon_result.setText("Считаю…")
        try:
            total, unknown = self.on_lexicon_check()
            self.lexicon_result.setText(
                f"Терминов: {total}, модель не знает {unknown} — их и спасает словарь.")
        except Exception as exc:  # noqa: BLE001
            self.lexicon_result.setText(f"Не получилось: {exc}")

    def _save(self) -> None:
        s = self.settings
        s.mode = self.mode.currentData()
        s.hotkey_toggle = self.hk_toggle.text().strip()
        s.hotkey_continuous = self.hk_continuous.text().strip()
        s.hotkey_undo = self.hk_undo.text().strip()
        s.start_minimized = self.start_minimized.isChecked()
        s.input_device = self.device.currentData() or ""
        s.gain = float(self.gain.value())
        s.vad = self.vad.isChecked()
        s.vad_threshold_db = float(self.vad_db.value())
        s.auto_stop_silence = float(self.auto_stop.value())
        s.insert_method = self.method.currentData()
        s.live_insert = self.live.isChecked()
        s.char_delay_ms = int(self.char_delay.value())
        s.newline_enter = self.newline.isChecked()
        s.same_window_only = self.same_window.isChecked()
        s.correction = self.correction.isChecked()
        s.threshold = self.threshold.value() / 100
        s.lexicon_gate = self.lexicon_gate.isChecked()
        s.numbers = self.numbers.isChecked()
        s.units = self.units.isChecked()
        s.punctuation_commands = self.punct.isChecked()
        s.capitalize_sentences = self.capitalize.isChecked()
        s.final_period = self.period.isChecked()

        if config.set_autostart(self.autostart.isChecked()):
            s.autostart = self.autostart.isChecked()
        s.save()
        self.accept()
