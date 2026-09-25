# -*- mode: python ; coding: utf-8 -*-
"""
Сборка одного портативного exe: PyInstaller + meddictate.spec.

Внутрь упаковывается всё необходимое:
  * код программы и PyQt6;
  * движок распознавания vosk (libvosk.dll);
  * русская модель (папка model/);
  * медицинский словарь и иконка.

Запуск:
    python -m PyInstaller --noconfirm meddictate.spec
Результат:
    dist/MedDictate.exe
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.getcwd())
MODEL_DIR = os.path.join(ROOT, "model")

datas = [
    ("data/terms_med.txt", "data"),
    ("data/replacements_med.txt", "data"),
    ("data/icon.ico", "data"),
    ("data/icon.png", "data"),
]

if os.path.isdir(MODEL_DIR) and os.path.isfile(os.path.join(MODEL_DIR, "am", "final.mdl")):
    datas.append((MODEL_DIR, "model"))
else:
    print("ВНИМАНИЕ: папка model/ с русской моделью не найдена.")
    print("Программа соберётся, но при первом запуске скачает модель из интернета.")
    print("Чтобы модель была внутри exe: python tools/fetch_model.py && повторить сборку.")

binaries = []
binaries += collect_dynamic_libs("vosk")          # libvosk.dll
binaries += collect_dynamic_libs("sounddevice")   # PortAudio
datas += collect_data_files("sounddevice")
datas += collect_data_files("vosk")

hiddenimports = [
    "vosk",
    "vosk.vosk_cffi",
    "_cffi_backend",
    "sounddevice",
    "_sounddevice_data",
    # интерфейс: PySide6 (LGPL). Если установлен только PyQt6 — см. app/qt.py
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtNetwork",
    "app", "app.qt", "app.app", "app.asr", "app.audio", "app.config",
    "app.corrector", "app.dictionary", "app.hotkeys", "app.insert", "app.main",
    "app.numerals", "app.overlay", "app.settings_dialog", "app.tray",
]
hiddenimports += collect_submodules("sounddevice")

excludes = [
    "tkinter", "matplotlib", "scipy", "pandas", "PIL.ImageQt",
    # второй Qt-бэкенд не нужен: в exe едет только выбранный
    "PyQt6", "PyQt5", "PySide2",
    # лишние модули Qt (заметно уменьшают размер)
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtBluetooth",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest", "PySide6.QtSql",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtSvgWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtUiTools", "PySide6.QtSpatialAudio",
]

a = Analysis(
    ["meddictate.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MedDictate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # для Qt/DLL сжатие UPX ломает подпись и часть библиотек
    console=False,             # программа работает без чёрного окна консоли
    disable_windowed_traceback=False,
    icon="data/icon.ico",
    version=None,
)
