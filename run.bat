@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber

if not exist ".venv\Scripts\activate.bat" (
  echo [!] Run install.bat first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"

REM === Settings for this PC (Ryzen 5 5500U, 12 threads, 14 GB RAM) ===
set PYTHONUTF8=1
REM Whisper model: "small" is already downloaded and loads instantly. "medium"
REM is more accurate but its ~1.5 GB download from HuggingFace can stall on a
REM slow connection. Switch to medium only after it has finished downloading.
if "%VTX_MODEL%"=="" set VTX_MODEL=small
REM Recognition quality (beam search) - the CPU has headroom for it.
if "%VTX_BEAM_SIZE%"=="" set VTX_BEAM_SIZE=5
REM Physical cores (6 on the 5500U) - the sweet spot for the engine.
if "%VTX_CPU_THREADS%"=="" set VTX_CPU_THREADS=6
REM Diarization (who spoke): set to 1 to enable (needs HF_TOKEN and pyannote).
if "%VTX_DIARIZATION%"=="" set VTX_DIARIZATION=0

REM === Meeting protocol: local AI via Ollama (free, offline) ===
if "%VTX_OLLAMA%"=="" set VTX_OLLAMA=1
REM Tuned protocol model - created automatically on first run.
if "%VTX_OLLAMA_MODEL%"=="" set VTX_OLLAMA_MODEL=vtx-protocol
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA_EXE%" goto :no_ollama
REM Start the Ollama server if it isn't running yet.
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul || ( echo  Starting Ollama... & start "" /B "%OLLAMA_EXE%" serve & timeout /t 3 >nul )
REM First run: create the custom vtx-protocol model from the Modelfile (once).
"%OLLAMA_EXE%" list 2>nul | find /I "vtx-protocol" >nul || (
  echo  Preparing protocol model "vtx-protocol" ^(one-time; may download qwen2.5:7b ~4.7 GB^)...
  "%OLLAMA_EXE%" list 2>nul | find /I "qwen2.5:7b" >nul || "%OLLAMA_EXE%" pull qwen2.5:7b
  "%OLLAMA_EXE%" create vtx-protocol -f "%~dp0Modelfile"
)
goto :ollama_done
:no_ollama
echo.
echo  [i] Local engine (Ollama) is not installed - that's OK.
echo      In the app (protocol mode) pick "local" to install it on demand,
echo      or use a cloud engine by API key. Recognition works either way.
:ollama_done
REM Cloud alternatives: set GROQ_API_KEY=...  /  set ANTHROPIC_API_KEY=...
REM --------------------------------

echo.
echo  Server is starting. Open in your browser:
echo      http://localhost:8000
echo.
echo  From other devices on the same network: http://^<this-PC-IP^>:8000
echo  To stop the server - close this window or press Ctrl+C.
echo.

start "" http://localhost:8000
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
