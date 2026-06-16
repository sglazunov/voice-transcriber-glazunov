@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Создание локальной модели протоколов

set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" (
  echo [!] Ollama не найдена. Установите с https://ollama.com
  pause
  exit /b 1
)

echo Проверяю базовую модель qwen2.5:7b...
"%OLLAMA%" list | find /I "qwen2.5:7b" >nul || "%OLLAMA%" pull qwen2.5:7b

echo Создаю кастомную модель vtx-protocol из Modelfile...
"%OLLAMA%" create vtx-protocol -f Modelfile
if errorlevel 1 ( echo [!] Не удалось создать модель & pause & exit /b 1 )

echo.
echo ============================================
echo   Готово. Модель: vtx-protocol
echo   run.bat уже использует её (VTX_OLLAMA_MODEL=vtx-protocol).
echo ============================================
pause
