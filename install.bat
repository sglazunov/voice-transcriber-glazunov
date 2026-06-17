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
  echo     Установите Python 3.12 с https://www.python.org/downloads/
  echo     ВАЖНО: при установке отметьте "Add Python to PATH".
  pause
  exit /b 1
)

REM Нативные пакеты (ctranslate2/onnxruntime) поддерживают Python 3.12,
REM но НЕ 3.14. Требуем именно 3.12.
py -3.12 --version >nul 2>nul
if errorlevel 1 (
  echo [!] Нужен Python 3.12. Установите его:
  echo     winget install Python.Python.3.12
  echo     (Python 3.14 не поддерживается движком распознавания.)
  pause
  exit /b 1
)

echo [0/5] Проверяю Visual C++ Redistributable (нужен для onnxruntime)...
winget install --id Microsoft.VCRedist.2015+.x64 --accept-source-agreements --accept-package-agreements --silent >nul 2>nul

echo [1/5] Создаю виртуальное окружение (Python 3.12)...
py -3.12 -m venv .venv
if errorlevel 1 ( echo [!] Не удалось создать venv & pause & exit /b 1 )

call ".venv\Scripts\activate.bat"

echo [2/5] Обновляю pip...
python -m pip install --upgrade pip wheel >nul

echo [3/5] Устанавливаю зависимости (это может занять несколько минут)...
pip install -r requirements.txt
if errorlevel 1 ( echo [!] Ошибка установки зависимостей & pause & exit /b 1 )

if "%VTX_MODEL%"=="" set VTX_MODEL=small
echo [4/5] Скачиваю модель распознавания "%VTX_MODEL%"...
python -c "from faster_whisper import WhisperModel; WhisperModel('%VTX_MODEL%', device='cpu', compute_type='int8'); print('Модель готова')"
if errorlevel 1 ( echo [!] Не удалось скачать модель & pause & exit /b 1 )

echo [5/5] Локальный ИИ для протокола (Ollama)...
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if exist "%OLLAMA_EXE%" goto :ollama_ok
echo     Устанавливаю Ollama...
winget install --id Ollama.Ollama --accept-source-agreements --accept-package-agreements --silent
if exist "%OLLAMA_EXE%" goto :ollama_ok
echo     [i] Не удалось установить автоматически. Скачайте вручную:
echo         https://ollama.com/download   (протокол можно строить и через облако по ключу)
start "" https://ollama.com/download
:ollama_ok
echo     (Модель протокола создастся автоматически при первом запуске run.bat.)

echo.
echo ============================================
echo   Готово! Запустите run.bat
echo ============================================
pause
