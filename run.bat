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

REM === Настройки под этот ПК (Ryzen 5 5500U, 12 потоков, 14 ГБ RAM) ===
set PYTHONUTF8=1
REM Модель Whisper: small уже скачана и грузится мгновенно. medium точнее, но
REM её ~1.5 ГБ качаются с HuggingFace при первом запуске (может зависнуть на
REM медленном интернете). Переключайтесь на medium только когда она скачается.
if "%VTX_MODEL%"=="" set VTX_MODEL=small
REM Качество распознавания (beam search) — у CPU есть запас
if "%VTX_BEAM_SIZE%"=="" set VTX_BEAM_SIZE=5
REM Физические ядра (6 у 5500U) — оптимум для движка, остальное оставляем ОС
if "%VTX_CPU_THREADS%"=="" set VTX_CPU_THREADS=6
REM Диаризация (кто говорил): 1 чтобы включить (нужен HF_TOKEN и pyannote)
if "%VTX_DIARIZATION%"=="" set VTX_DIARIZATION=0

REM === Протокол встречи: локальный ИИ через Ollama (бесплатно, оффлайн) ===
if "%VTX_OLLAMA%"=="" set VTX_OLLAMA=1
if "%VTX_OLLAMA_MODEL%"=="" set VTX_OLLAMA_MODEL=qwen2.5:7b
REM Запускаем сервер Ollama, если он установлен и ещё не поднят
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if exist "%OLLAMA_EXE%" (
  tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul || (
    echo  Запускаю Ollama...
    start "" /B "%OLLAMA_EXE%" serve
  )
)
REM Альтернативы (если не хотите локально): задайте свой ключ —
REM   set GROQ_API_KEY=...        (бесплатно, console.groq.com)
REM   set ANTHROPIC_API_KEY=...   (платно, console.anthropic.com)
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
