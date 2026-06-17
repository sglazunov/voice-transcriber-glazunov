@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber - build .exe

if not exist ".venv\Scripts\activate.bat" (
  echo [!] Run install.bat first
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"

echo [1/2] Installing build dependencies...
python -m pip install -r requirements-desktop.txt
if errorlevel 1 ( echo [!] Failed to install dependencies & pause & exit /b 1 )

echo [2/2] Building VoiceTranscriber.exe (a few minutes)...
pyinstaller --noconfirm VoiceTranscriber.spec
if errorlevel 1 ( echo [!] Build failed & pause & exit /b 1 )

echo.
echo ============================================
echo   Done: dist\VoiceTranscriber\VoiceTranscriber.exe
echo   Installer: open installer.iss in Inno Setup and press Compile.
echo ============================================
pause
