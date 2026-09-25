# -*- coding: utf-8 -*-
"""
Единая точка импорта Qt.

Программа работает и на PySide6 (лицензия LGPL — собранный exe можно свободно
передавать коллегам), и на PyQt6 (GPL — для внутреннего использования либо
с коммерческой лицензией Qt). Если установлены оба, выбирается PySide6.

Принудительный выбор: переменная окружения MEDDICTATE_QT=PyQt6 (или PySide6).

Использование в коде простое:

    from .qt import QWidget, QLabel, Qt, Signal
"""
from __future__ import annotations

import os

_EXPORTED = (
    "BACKEND", "QtCore", "QtGui", "QtWidgets", "QtNetwork", "Qt", "Signal", "Slot",
    # QtCore
    "QObject", "QTimer", "QPoint", "QSize",
    # QtGui
    "QAction", "QColor", "QFont", "QIcon", "QPixmap", "QPainter", "QPainterPath",
    "QGuiApplication",
    # QtWidgets
    "QApplication", "QCheckBox", "QComboBox", "QDialog", "QDialogButtonBox",
    "QDoubleSpinBox", "QFormLayout", "QFrame", "QGraphicsDropShadowEffect",
    "QGroupBox", "QHBoxLayout", "QLabel", "QLineEdit", "QMessageBox", "QMenu",
    "QPushButton", "QSizePolicy", "QSlider", "QSpinBox", "QSystemTrayIcon",
    "QTabWidget", "QVBoxLayout", "QWidget",
    # QtNetwork
    "QLocalServer", "QLocalSocket",
)
__all__ = list(_EXPORTED)

_PREFERRED = os.environ.get("MEDDICTATE_QT", "").strip()


def _import_pyside() -> bool:
    global QtCore, QtGui, QtWidgets, QtNetwork, Qt, Signal, Slot, BACKEND
    try:
        from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets
        from PySide6.QtCore import Qt, Signal, Slot
    except ImportError:
        return False
    BACKEND = "PySide6"
    return True


def _import_pyqt() -> bool:
    global QtCore, QtGui, QtWidgets, QtNetwork, Qt, Signal, Slot, BACKEND
    try:
        from PyQt6 import QtCore, QtGui, QtNetwork, QtWidgets
        from PyQt6.QtCore import Qt
        from PyQt6.QtCore import pyqtSignal as Signal
        from PyQt6.QtCore import pyqtSlot as Slot
    except ImportError:
        return False
    BACKEND = "PyQt6"
    return True


BACKEND = ""
_loaded = (_import_pyqt() if _PREFERRED == "PyQt6"
           else _import_pyside() if _PREFERRED == "PySide6"
           else (_import_pyside() or _import_pyqt()))

if not _loaded:  # pragma: no cover
    raise ImportError(
        "Не найден ни PySide6, ни PyQt6.\n"
        "Установите зависимости:  pip install -r requirements.txt"
    )

#: имена, которые различаются только модулем-источником; вытаскиваем их
#: из выбранного бэкенда, чтобы остальной код не знал о разнице
_CLASSES = [
    "QObject", "QTimer", "QPoint", "QSize",
    "QAction", "QColor", "QFont", "QIcon", "QPixmap", "QPainter", "QPainterPath",
    "QGuiApplication",
    "QApplication", "QCheckBox", "QComboBox", "QDialog", "QDialogButtonBox",
    "QDoubleSpinBox", "QFormLayout", "QFrame", "QGraphicsDropShadowEffect",
    "QGroupBox", "QHBoxLayout", "QLabel", "QLineEdit", "QMessageBox", "QMenu",
    "QPushButton", "QSizePolicy", "QSlider", "QSpinBox", "QSystemTrayIcon",
    "QTabWidget", "QVBoxLayout", "QWidget",
    "QLocalServer", "QLocalSocket",
]

for _name in _CLASSES:
    for _module in (QtWidgets, QtGui, QtCore, QtNetwork):
        if hasattr(_module, _name):
            globals()[_name] = getattr(_module, _name)
            break
    else:  # pragma: no cover
        raise ImportError(f"В {BACKEND} нет класса {_name}")

del _name, _module, _CLASSES
