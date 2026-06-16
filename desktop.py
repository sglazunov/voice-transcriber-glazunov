"""Desktop entry point — run the app in a native window instead of a browser.

Same FastAPI backend as the web version (`app/`), just wrapped in a desktop
shell:

  * starts the uvicorn server on a background thread, on a free localhost port;
  * starts the local Ollama server too (best effort), so the protocol feature
    works out of the box;
  * opens a native OS window (Edge WebView2 on Windows) pointing at the server.

Run with `--selftest` to verify the server boots and answers without opening a
window (used by CI / smoke tests).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"


def _resource_dir() -> Path:
    """App root, both when run from source and when frozen by PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _server_up(url: str, timeout: float = 1.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def _wait_until_up(url: str, timeout: float = 40.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if _server_up(url):
            return True
        time.sleep(0.3)
    return False


def _start_ollama() -> None:
    """Start the local Ollama server if installed and not already running."""
    if _server_up("http://127.0.0.1:11434/api/version"):
        return
    exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if not exe.exists():
        return
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.Popen([str(exe), "serve"], creationflags=flags)
    except Exception:
        pass


def _start_server() -> tuple[object, int]:
    """Launch uvicorn on a daemon thread; return (server, port)."""
    import uvicorn

    # Mirror run.bat defaults (overridable from the environment).
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("VTX_MODEL", "small")
    os.environ.setdefault("VTX_OLLAMA", "1")
    # Tuned local protocol model (created via make_protocol_model.bat).
    os.environ.setdefault("VTX_OLLAMA_MODEL", "vtx-protocol")

    from app.main import app  # imported after env is set so config picks it up

    port = _free_port()
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="vtx-uvicorn").start()
    return server, port


def main() -> int:
    selftest = "--selftest" in sys.argv

    _start_ollama()
    server, port = _start_server()
    base = f"http://{HOST}:{port}"

    if not _wait_until_up(f"{base}/healthz"):
        print("ERROR: сервер не запустился", file=sys.stderr)
        return 1

    if selftest:
        print(f"OK: сервер отвечает на {base}/healthz")
        server.should_exit = True
        return 0

    import webview

    webview.create_window(
        "Voice Transcriber — распознавание встреч",
        base,
        width=1180,
        height=860,
        min_size=(900, 600),
    )
    webview.start()  # blocks until the window is closed
    server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
