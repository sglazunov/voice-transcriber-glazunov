@echo off
chcp 65001 >nul
REM Installs the local AI engine (Ollama) and the protocol model.
REM Run by the installer after install (if the user opts in).

echo === Checking Visual C++ Redistributable ===
winget install --id Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements >nul 2>nul

set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" (
  echo === Installing Ollama ===
  winget install --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements
)

if not exist "%OLLAMA%" (
  echo [!] Could not install Ollama automatically.
  echo     Install it manually from https://ollama.com and run: ollama pull qwen2.5:7b
  pause
  exit /b 1
)

echo === Starting the Ollama server ===
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul || start "" /B "%OLLAMA%" serve
timeout /t 3 >nul

echo === Downloading the qwen2.5:7b model (~4.7 GB, one-time) ===
"%OLLAMA%" pull qwen2.5:7b

echo === Creating the tuned protocol model "vtx-protocol" ===
if exist "%~dp0Modelfile" (
  "%OLLAMA%" create vtx-protocol -f "%~dp0Modelfile"
) else (
  echo [!] Modelfile not found nearby - skipping; qwen2.5:7b will be used.
)

echo Done.
