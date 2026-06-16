@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Voice Transcriber - сборка .exe

if not exist ".venv\Scripts\activate.bat" (
  echo [!] Сначала запустите install.bat
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"

echo [1/2] Устанавливаю сборочные зависимости...
python -m pip install -r requirements-desktop.txt
if errorlevel 1 ( echo [!] Ошибка установки зависимостей & pause & exit /b 1 )

echo [2/2] Собираю VoiceTranscriber.exe (несколько минут)...
pyinstaller --noconfirm VoiceTranscriber.spec
if errorlevel 1 ( echo [!] Сборка не удалась & pause & exit /b 1 )

echo.
echo ============================================
echo   Готово: dist\VoiceTranscriber\VoiceTranscriber.exe
echo   Установщик: откройте installer.iss в Inno Setup и нажмите Compile.
echo ============================================
pause
