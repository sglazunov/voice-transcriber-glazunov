@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber (Desktop)

if not exist ".venv\Scripts\pythonw.exe" (
  echo [!] Сначала запустите install.bat, затем:
  echo     .venv\Scripts\python -m pip install -r requirements-desktop.txt
  pause
  exit /b 1
)

REM Запуск как обычной программы — в отдельном окне, без консоли.
set PYTHONUTF8=1
start "" ".venv\Scripts\pythonw.exe" desktop.py
