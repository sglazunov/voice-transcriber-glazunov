@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber - установка

echo ============================================
echo   Распознавание речи - установка (Windows)
echo ============================================
echo.

REM ── Нужен именно Python 3.12: нативные пакеты (ctranslate2/onnxruntime)
REM    поддерживают 3.12, но НЕ 3.14. Если его нет — предложим установить.
set "PY312=py -3.12"
py -3.12 --version >nul 2>nul
if not errorlevel 1 goto py_ok
set "PY312=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PY312%" goto py_ok

echo.
echo ============================================================
echo  [!] Для работы нужен Python 3.12.
echo      Сейчас он не найден (или установлена другая версия —
echo      например 3.14, которую движок распознавания не поддерживает).
echo ============================================================
choice /C YN /N /M "Скачать и установить Python 3.12 автоматически? [Y - да / N - нет]: "
if not errorlevel 2 goto py_install
echo.
echo  Установка отменена. Python 3.12 можно поставить вручную:
echo    https://www.python.org/downloads/release/python-3120/
echo  При установке отметьте "Add Python to PATH", затем запустите install.bat снова.
pause
exit /b 1

:py_install
echo.
echo  Устанавливаю Python 3.12...
where winget >nul 2>nul
if not errorlevel 1 (
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
) else (
  echo  winget не найден - скачиваю установщик с python.org...
  curl -L -o "%TEMP%\python312-setup.exe" https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
  "%TEMP%\python312-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1
)

REM Повторная проверка после установки
set "PY312=py -3.12"
py -3.12 --version >nul 2>nul
if not errorlevel 1 goto py_ok
set "PY312=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PY312%" goto py_ok
echo.
echo  [i] Python 3.12 установлен, но ещё не виден в этом окне (PATH обновится
echo      только в новом окне). Закройте это окно и запустите install.bat ещё раз.
pause
exit /b 1

:py_ok
echo  Python 3.12: %PY312%

echo [0/5] Проверяю Visual C++ Redistributable (нужен для onnxruntime)...
winget install --id Microsoft.VCRedist.2015+.x64 --accept-source-agreements --accept-package-agreements --silent >nul 2>nul

echo [1/5] Создаю виртуальное окружение (Python 3.12)...
%PY312% -m venv .venv
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
