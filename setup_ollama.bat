@echo off
chcp 65001 >nul
REM Доустановка локального ИИ-движка (Ollama) и модели для протоколов.
REM Запускается установщиком после установки программы (по желанию пользователя).

echo === Проверяю Visual C++ Redistributable ===
winget install --id Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements >nul 2>nul

set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" (
  echo === Устанавливаю Ollama ===
  winget install --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements
)

if not exist "%OLLAMA%" (
  echo [!] Не удалось установить Ollama автоматически.
  echo     Установите вручную с https://ollama.com и выполните: ollama pull qwen2.5:7b
  pause
  exit /b 1
)

echo === Запускаю сервер Ollama ===
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul || start "" /B "%OLLAMA%" serve
timeout /t 3 >nul

echo === Скачиваю модель qwen2.5:7b (~4.7 ГБ, один раз) ===
"%OLLAMA%" pull qwen2.5:7b

echo === Создаю настроенную модель протокола "vtx-protocol" ===
if exist "%~dp0Modelfile" (
  "%OLLAMA%" create vtx-protocol -f "%~dp0Modelfile"
) else (
  echo [!] Modelfile не найден рядом — пропускаю; будет использована qwen2.5:7b.
)

echo Готово.
