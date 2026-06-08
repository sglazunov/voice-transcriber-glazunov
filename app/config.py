"""Runtime configuration, all overridable via environment variables.

Defaults are tuned for a low-end machine (4 GB RAM, 4 weak CPU cores,
no GPU) — the Lenovo ideapad acting as the server.
"""
import os
from pathlib import Path

# Where uploads and results live. Override with VTX_DATA_DIR.
DATA_DIR = Path(os.getenv("VTX_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
JOBS_FILE = DATA_DIR / "jobs.json"

# Whisper model. "small" is the sweet spot for Russian on this hardware.
# Use "base" if RAM/CPU is too tight, "medium"/"large-v3" only after upgrade.
MODEL = os.getenv("VTX_MODEL", "small")
DEVICE = os.getenv("VTX_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("VTX_COMPUTE_TYPE", "int8")
# 0 = let the engine use all available cores (adapts to whatever machine runs it).
CPU_THREADS = int(os.getenv("VTX_CPU_THREADS", "0"))
# beam_size=1 (greedy) is much faster on a slow CPU; bump to 5 for quality.
BEAM_SIZE = int(os.getenv("VTX_BEAM_SIZE", "1"))
DEFAULT_LANGUAGE = os.getenv("VTX_LANGUAGE", "ru")
VAD_FILTER = os.getenv("VTX_VAD", "1") == "1"

# Max upload size in MB. 2 GB by default so 1 GB videos go through comfortably.
MAX_UPLOAD_MB = int(os.getenv("VTX_MAX_UPLOAD_MB", "2048"))

# Diarization is opt-in and OFF by default — it does not fit in 4 GB.
DIARIZATION_ENABLED = os.getenv("VTX_DIARIZATION", "0") == "1"
HF_TOKEN = os.getenv("HF_TOKEN", "")

# AI analysis (protocol/summary generation). Requires Anthropic API key.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANALYSIS_MODEL = os.getenv("VTX_ANALYSIS_MODEL", "claude-sonnet-4-6")
ANALYSIS_ENABLED = bool(ANTHROPIC_API_KEY)

for _d in (DATA_DIR, UPLOAD_DIR, RESULT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
