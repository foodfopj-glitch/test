@echo off
rem ====================================================================
rem  Сборка портативного MedDictate.exe
rem  Требуется Python 3.10-3.12 (любой, установленный в системе).
rem  Двойной щелчок по этому файлу - и через 3-5 минут в папке dist\
rem  появится один файл MedDictate.exe, который никуда не надо ставить.
rem ====================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [1/6] Проверка Python
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo Python не найден. Установите его с python.org
    echo и при установке отметьте галочку "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)
python -c "import sys; assert sys.version_info[:2] >= (3,10), 'нужен Python 3.10 или новее'"

echo [2/6] Установка зависимостей
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || (echo Ошибка установки зависимостей & pause & exit /b 1)
rem Интерфейс собирается на PySide6 (лицензия LGPL - exe можно передавать коллегам).
rem Если нужен PyQt6, поставьте requirements-pyqt.txt и уберите PyQt6 из exclude в meddictate.spec.

echo [3/6] Загрузка русской модели (если ещё нет)
python tools\fetch_model.py --check >nul 2>nul
if errorlevel 1 python tools\fetch_model.py || (echo Не удалось скачать модель & pause & exit /b 1)

echo [4/6] Самопроверка корректора
python meddictate.py --selftest || (echo Самопроверка не прошла & pause & exit /b 1)

echo [5/6] Сборка exe (это займет несколько минут)
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean meddictate.spec || (echo Ошибка сборки & pause & exit /b 1)

echo [6/6] Готово
echo.
echo   Файл: %cd%\dist\MedDictate.exe
echo   Размер:
dir /b /-c dist\MedDictate.exe
echo.
echo   Программа портативная: можно скопировать exe на флешку.
echo   Настройки и свои словари хранятся в %%APPDATA%%\MedDictate
echo.
pause
