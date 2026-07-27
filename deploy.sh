#!/usr/bin/env bash
# One-shot setup on an Ubuntu/Debian server.  Run:  bash deploy.sh
#
# Installs system deps, creates the venv, installs Python requirements,
# pre-downloads a Whisper model and (optionally) installs a systemd unit
# generated for THIS machine's user/path — so nothing is hardcoded.
#
# Env overrides:
#   VTX_MODEL=medium     model to pre-download (small|medium|large-v3|…)
#   PORT=8000            port to listen on
#   WITH_PLAYWRIGHT=1    also install Playwright + Chromium (meeting recorder)
#   WITH_OCR=1           also install Tesseract (on-screen text recognition)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python3}"
PORT="${PORT:-8000}"
VTX_MODEL="${VTX_MODEL:-medium}"
RUN_USER="${SUDO_USER:-$USER}"

echo "==> App:  $APP_DIR"
echo "==> User: $RUN_USER   Port: $PORT   Model: $VTX_MODEL"

# ---------------------------------------------------------------- system deps
echo "==> Installing system packages…"
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq
  # ffmpeg   — audio/video decoding (and screen capture later)
  # libgomp1 — required by the onnxruntime/ctranslate2 wheels
  # tzdata   — timezone database (meeting times)
  sudo apt-get install -y ffmpeg python3-venv python3-pip libgomp1 tzdata curl
  if [ "${WITH_OCR:-0}" = "1" ]; then
    sudo apt-get install -y tesseract-ocr tesseract-ocr-rus
  fi
else
  echo "!! Not apt-based. Install manually: ffmpeg, python3-venv, libgomp1." >&2
fi

# Python 3.14 breaks ctranslate2/onnxruntime; 3.10–3.12 are fine.
PYV="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
echo "==> Python $PYV"
case "$PYV" in
  3.10|3.11|3.12) ;;
  *) echo "!! Python $PYV is untested (need 3.10–3.12). Continuing anyway." >&2 ;;
esac

# --------------------------------------------------------------------- venv
echo "==> Creating virtualenv…"
[ -d "$APP_DIR/.venv" ] || "$PY" -m venv "$APP_DIR/.venv"
VPY="$APP_DIR/.venv/bin/python"
"$VPY" -m pip install --upgrade pip wheel -q
"$VPY" -m pip install -r "$APP_DIR/requirements.txt"

# ------------------------------------------------------- optional: recorder
if [ "${WITH_PLAYWRIGHT:-0}" = "1" ]; then
  echo "==> Installing Playwright + Chromium (meeting recorder)…"
  "$VPY" -m pip install playwright
  sudo "$VPY" -m playwright install --with-deps chromium
fi

# ------------------------------------------------- pre-download the model
echo "==> Pre-downloading Whisper model '$VTX_MODEL' (first run would be slow)…"
VTX_MODEL="$VTX_MODEL" "$VPY" - <<'PY'
import os
from faster_whisper import download_model
m = os.environ.get("VTX_MODEL", "medium")
print(f"Fetching: {m}")
download_model(m)          # into the HF cache, without loading it into RAM
print("Model cached.")
PY

# ------------------------------------------------------------ systemd unit
UNIT=/etc/systemd/system/voicetx.service
echo
read -r -p "Install systemd service (autostart on boot)? [Y/n] " ans || ans=Y
ans="$(printf '%s' "${ans:-Y}" | tr '[:upper:]' '[:lower:]')"
if [ "$ans" = "y" ]; then
  sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Voice Transcriber (speech-to-text + meeting protocols)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=VTX_MODEL=$VTX_MODEL
Environment=VTX_COMPUTE_TYPE=int8
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now voicetx
  sleep 2
  sudo systemctl --no-pager --lines=5 status voicetx || true
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

==> Готово.
Сайт:      http://${IP:-<IP сервера>}:$PORT/
Логи:      sudo journalctl -u voicetx -f
Рестарт:   sudo systemctl restart voicetx
Обновить:  cd "$APP_DIR" && git pull && .venv/bin/pip install -r requirements.txt && sudo systemctl restart voicetx
EOF
