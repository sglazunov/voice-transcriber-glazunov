@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber - install

echo ============================================
echo   Voice Transcriber - install (Windows)
echo ============================================
echo.

REM Python 3.12 is required: native deps (ctranslate2/onnxruntime) support 3.12
REM but NOT 3.14. If it's missing, offer to install it.
set "PY312=py -3.12"
py -3.12 --version >nul 2>nul
if not errorlevel 1 goto py_ok
set "PY312=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PY312%" goto py_ok

echo.
echo ============================================================
echo  [!] Python 3.12 is required.
echo      It was not found (or a different version is installed,
echo      e.g. 3.14, which the recognition engine does not support).
echo ============================================================
choice /C YN /N /M "Download and install Python 3.12 automatically? [Y - yes / N - no]: "
if not errorlevel 2 goto py_install
echo.
echo  Cancelled. You can install Python 3.12 manually:
echo    https://www.python.org/downloads/release/python-3120/
echo  Tick "Add Python to PATH", then run install.bat again.
pause
exit /b 1

:py_install
echo.
echo  Installing Python 3.12...
where winget >nul 2>nul
if not errorlevel 1 (
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
) else (
  echo  winget not found - downloading the installer from python.org...
  curl -L -o "%TEMP%\python312-setup.exe" https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
  "%TEMP%\python312-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1
)

REM Re-detect after install
set "PY312=py -3.12"
py -3.12 --version >nul 2>nul
if not errorlevel 1 goto py_ok
set "PY312=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PY312%" goto py_ok
echo.
echo  [i] Python 3.12 was installed but is not visible in this window yet
echo      (PATH updates only in a new window). Close this window and run
echo      install.bat again.
pause
exit /b 1

:py_ok
echo  Python 3.12: %PY312%

echo [0/5] Checking Visual C++ Redistributable (needed by onnxruntime)...
winget install --id Microsoft.VCRedist.2015+.x64 --accept-source-agreements --accept-package-agreements --silent >nul 2>nul

echo [1/5] Creating virtual environment (Python 3.12)...
%PY312% -m venv .venv
if errorlevel 1 ( echo [!] Failed to create venv & pause & exit /b 1 )

call ".venv\Scripts\activate.bat"

echo [2/5] Upgrading pip...
python -m pip install --upgrade pip wheel >nul

echo [3/5] Installing dependencies (may take a few minutes)...
pip install -r requirements.txt
if errorlevel 1 ( echo [!] Failed to install dependencies & pause & exit /b 1 )

if "%VTX_MODEL%"=="" set VTX_MODEL=small
echo [4/5] Downloading the recognition model "%VTX_MODEL%"...
python -c "from faster_whisper import WhisperModel; WhisperModel('%VTX_MODEL%', device='cpu', compute_type='int8'); print('Model ready')"
if errorlevel 1 ( echo [!] Failed to download the model & pause & exit /b 1 )

echo [5/5] Local AI for the protocol (Ollama) - NOT installed here.
echo     You choose in the app: install the local engine on demand, or use a
echo     cloud engine by API key. (Recognition itself needs no AI engine.)

echo.
echo ============================================
echo   Done! Now run run.bat
echo ============================================
pause
