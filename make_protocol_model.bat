@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Create the local protocol model

set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" (
  echo [!] Ollama not found. Install it from https://ollama.com
  pause
  exit /b 1
)

echo Checking the base model qwen2.5:7b...
"%OLLAMA%" list | find /I "qwen2.5:7b" >nul || "%OLLAMA%" pull qwen2.5:7b

echo Creating the custom vtx-protocol model from Modelfile...
"%OLLAMA%" create vtx-protocol -f Modelfile
if errorlevel 1 ( echo [!] Failed to create the model & pause & exit /b 1 )

echo.
echo ============================================
echo   Done. Model: vtx-protocol
echo   run.bat already uses it (VTX_OLLAMA_MODEL=vtx-protocol).
echo ============================================
pause
