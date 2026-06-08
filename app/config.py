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

# ---- AI analysis (protocol / meeting-summary generation) -------------------
# The protocol can be built by any of several LLM providers. Each transcript
# job picks one. Providers fall into two buckets:
#   FREE  — Ollama (fully local/offline) and Groq (free cloud tier)
#   PAID  — Anthropic Claude (billed per token, highest quality)

# "auto" = use whichever is available, preferring free providers so you never
# get billed unexpectedly. Override per-job from the UI or globally here.
LLM_PROVIDER = os.getenv("VTX_LLM_PROVIDER", "auto")

# --- Paid: Anthropic Claude (per-token billing) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANALYSIS_MODEL = os.getenv("VTX_ANALYSIS_MODEL", "claude-sonnet-4-6")

# --- Free: Groq cloud (free tier; get a key at https://console.groq.com) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("VTX_GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Free: Ollama (fully local, no key; needs Ollama running locally) ---
# Set VTX_OLLAMA=1 after installing Ollama (https://ollama.com) and pulling a
# model, e.g.  ollama pull llama3.1
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("VTX_OLLAMA_MODEL", "llama3.1")
OLLAMA_ENABLED = os.getenv("VTX_OLLAMA", "0") == "1"

# Human-friendly labels shown in the UI provider picker.
PROVIDER_LABELS = {
    "ollama": "Локально · Ollama (бесплатно, оффлайн)",
    "groq": "Groq · Llama (бесплатно, облако)",
    "anthropic": "Claude (платно по токенам, точнее)",
}
# Order = preference for "auto" (free first, paid last).
PROVIDER_ORDER = ["ollama", "groq", "anthropic"]


def available_providers() -> list[str]:
    """Providers that are configured and therefore selectable right now."""
    out = []
    if OLLAMA_ENABLED:
        out.append("ollama")
    if GROQ_API_KEY:
        out.append("groq")
    if ANTHROPIC_API_KEY:
        out.append("anthropic")
    return [p for p in PROVIDER_ORDER if p in out]


def resolve_provider(name: str | None) -> str:
    """Turn a requested provider (or 'auto'/None) into a concrete one."""
    avail = available_providers()
    if not avail:
        raise RuntimeError(
            "Ни один LLM-провайдер не настроен. Включите Ollama (VTX_OLLAMA=1) "
            "или задайте GROQ_API_KEY / ANTHROPIC_API_KEY."
        )
    if name and name != "auto":
        if name not in avail:
            raise RuntimeError(f"Провайдер '{name}' не настроен.")
        return name
    return avail[0]  # PROVIDER_ORDER puts free providers first


ANALYSIS_ENABLED = bool(available_providers())

for _d in (DATA_DIR, UPLOAD_DIR, RESULT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
