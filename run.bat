@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber

if not exist ".venv\Scripts\activate.bat" (
  echo [!] Сначала запустите install.bat
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"

REM --- настройки (можно менять) ---
if "%VTX_MODEL%"=="" set VTX_MODEL=small
set PYTHONUTF8=1
REM Диаризация (кто говорил): 1 чтобы включить (нужен HF_TOKEN и pyannote)
if "%VTX_DIARIZATION%"=="" set VTX_DIARIZATION=0
REM --------------------------------

echo.
echo  Сервер запускается. Откройте в браузере:
echo      http://localhost:8000
echo.
echo  Доступ с других устройств в той же сети: http://^<IP-этого-ПК^>:8000
echo  Чтобы остановить сервер - закройте это окно или нажмите Ctrl+C.
echo.

start "" http://localhost:8000
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
