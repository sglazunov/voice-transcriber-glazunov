@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber - установка

echo ============================================
echo   Распознавание речи - установка (Windows)
echo ============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo [!] Python не найден.
  echo     Установите Python 3.10+ с https://www.python.org/downloads/
  echo     ВАЖНО: при установке отметьте "Add Python to PATH".
  pause
  exit /b 1
)

echo [1/4] Создаю виртуальное окружение...
py -3 -m venv .venv
if errorlevel 1 ( echo [!] Не удалось создать venv & pause & exit /b 1 )

call ".venv\Scripts\activate.bat"

echo [2/4] Обновляю pip...
python -m pip install --upgrade pip wheel >nul

echo [3/4] Устанавливаю зависимости (это может занять несколько минут)...
pip install -r requirements.txt
if errorlevel 1 ( echo [!] Ошибка установки зависимостей & pause & exit /b 1 )

if "%VTX_MODEL%"=="" set VTX_MODEL=small
echo [4/4] Скачиваю модель распознавания "%VTX_MODEL%"...
python -c "from faster_whisper import WhisperModel; WhisperModel('%VTX_MODEL%', device='cpu', compute_type='int8'); print('Модель готова')"
if errorlevel 1 ( echo [!] Не удалось скачать модель & pause & exit /b 1 )

echo.
echo ============================================
echo   Готово! Запустите run.bat
echo ============================================
pause
