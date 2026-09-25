@echo off
rem Запуск из исходников без сборки exe (для проверки/правок словаря).
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt >nul 2>nul
python meddictate.py %*
pause
