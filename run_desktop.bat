@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber (Desktop)

if not exist ".venv\Scripts\pythonw.exe" (
  echo [!] Run install.bat first, then:
  echo     .venv\Scripts\python -m pip install -r requirements-desktop.txt
  pause
  exit /b 1
)

REM Launch as a normal app - in its own window, no console.
set PYTHONUTF8=1
start "" ".venv\Scripts\pythonw.exe" desktop.py
