"""FastAPI app: web upload UI + REST API for transcription jobs."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config, llm, analyze
from .jobs import store, STATUS_DONE, STATUS_ANALYZING, STATUS_CANCELLED


def _provider_list() -> list[dict]:
    """Currently configured/available providers with display labels."""
    return [
        {"id": p, "label": config.PROVIDER_LABELS.get(p, p)}
        for p in config.available_providers()
    ]


def _ollama_label(name: str) -> str:
    """Human label for one installed Ollama model (marks custom / default)."""
    short = name.split(":")[0]
    default_short = config.OLLAMA_MODEL.split(":")[0]
    disp = name[:-7] if name.endswith(":latest") else name  # drop noisy :latest
    tags = []
    if short.startswith("vtx"):
        tags.append("настроенная")           # our Modelfile-built model
    if short == default_short:
        tags.append("по умолчанию")
    if not tags:
        tags.append("базовая")
    return f"Локально · {disp} ({', '.join(tags)})"


def _engine_list() -> list[dict]:
    """Engines for the UI picker: each installed Ollama model + cloud providers.

    Ollama models are returned as value "ollama:<model>"; cloud providers as
    their plain id. The tuned/default model is sorted first.
    """
    avail = config.available_providers()
    engines: list[dict] = []
    if "ollama" in avail:
        models = llm.list_ollama_models()
        default_short = config.OLLAMA_MODEL.split(":")[0]

        def rank(m: str) -> tuple:
            short = m.split(":")[0]
            return (0 if short == default_short else
                    1 if short.startswith("vtx") else 2, m)

        if models:
            for m in sorted(models, key=rank):
                engines.append({"value": f"ollama:{m}", "label": _ollama_label(m)})
        else:
            # Ollama enabled but server down / no models yet — offer the default.
            engines.append({"value": "ollama",
                            "label": f"Локально · {config.OLLAMA_MODEL} (по умолчанию)"})
    for p in avail:
        if p == "ollama":
            continue
        engines.append({"value": p, "label": config.PROVIDER_LABELS.get(p, p)})
    return engines

app = FastAPI(title="Voice Transcriber", version="1.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac",
               ".mp4", ".mkv", ".webm", ".mov", ".wma", ".amr"}

# Whisper models selectable per job (accuracy vs speed).
ALLOWED_MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]


# ---- Web UI ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "jobs": [j.to_public() for j in store.list()],
            "diarization_enabled": config.DIARIZATION_ENABLED,
            "analysis_enabled": bool(config.available_providers()),
            "providers": _provider_list(),
            "model": config.MODEL,
            "models": ALLOWED_MODELS,
            "max_upload_mb": config.MAX_UPLOAD_MB,
        },
    )


# ---- REST API -------------------------------------------------------------
@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    language: str = Form(config.DEFAULT_LANGUAGE),
    model: str = Form(""),
    diarize: bool = Form(False),
    analyze: bool = Form(False),
    provider: str = Form("auto"),
    hint: str = Form(""),
    glossary: str = Form(""),
    instructions: str = Form(""),
    custom_prompt: str = Form(""),
    capture_screen: bool = Form(False),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Неподдерживаемый формат: {ext or '?'}")

    dest = config.UPLOAD_DIR / f"{_safe_stem(file.filename)}{ext}"
    size = 0
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"Файл больше {config.MAX_UPLOAD_MB} МБ")
            out.write(chunk)

    want_diar = diarize  # honour the UI toggle; readiness is reported separately
    want_analyze = analyze and bool(config.available_providers())
    model_sel = model.strip() if model.strip() in ALLOWED_MODELS else ""
    job = store.create(file.filename, str(dest), language, want_diar,
                       initial_prompt=hint.strip(), glossary=glossary.strip(),
                       analyze=want_analyze, provider=provider,
                       analysis_instructions=instructions.strip(),
                       analysis_prompt=custom_prompt.strip(),
                       capture_screen=capture_screen, model=model_sel)
    return JSONResponse({"job_id": job.id, **job.to_public()}, status_code=201)


@app.get("/api/jobs")
def list_jobs():
    return [j.to_public() for j in store.list()]


# ---- LLM providers (protocol engine) --------------------------------------
class ProviderKey(BaseModel):
    provider: str
    api_key: str
    extra: str = ""   # YandexGPT: folder id · GigaChat: scope (optional)


@app.get("/api/providers")
def list_providers():
    """All known providers + which are currently usable (for the UI picker)."""
    avail = set(config.available_providers())
    return {
        "available": config.available_providers(),
        "engines": _engine_list(),
        "ollama_status": llm.ollama_status(),
        "ollama_install_url": "https://ollama.com/download",
        "providers": [
            {
                "id": p,
                "label": config.PROVIDER_LABELS.get(p, p),
                "available": p in avail,
                "needs_key": p in config.KEY_PROVIDERS,
            }
            for p in config.PROVIDER_ORDER
        ],
    }


@app.post("/api/providers/connect")
def connect_provider(body: ProviderKey):
    """Set an API key at runtime and verify it with a tiny live call.

    The key is held in memory only (not persisted to disk). On success the
    provider becomes selectable in the engine picker immediately.
    """
    provider = body.provider.strip().lower()
    key = body.api_key.strip()
    extra = body.extra.strip()
    if provider not in config.KEY_PROVIDERS:
        raise HTTPException(400, f"Подключение по ключу не поддерживается для '{provider}'")
    if not key:
        raise HTTPException(400, "Введите ключ")
    if provider == "yandex" and not extra:
        raise HTTPException(400, "Для YandexGPT укажите folder id (идентификатор каталога)")

    # Tentatively set the credentials, then validate with a cheap non-JSON ping
    # so bad credentials fail fast and are rolled back.
    config.set_provider_key(provider, key, extra)
    try:
        llm.get_provider(provider).complete("Ответь одним словом: ok",
                                            max_tokens=5, force_json=False)
    except Exception as e:
        config.set_provider_key(provider, "", "")  # roll back the bad key
        raise HTTPException(400, f"Не удалось подключиться: {e}")

    return {"ok": True, "connected": provider, "providers": _provider_list()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return job.to_public()


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str):
    return _control(job_id, "pause")


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    return _control(job_id, "resume")


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return _control(job_id, "cancel")


class ReanalyzeBody(BaseModel):
    provider: str = "auto"
    instructions: str | None = None
    custom_prompt: str | None = None


@app.post("/api/jobs/{job_id}/reanalyze")
def reanalyze_job(job_id: str, body: ReanalyzeBody):
    try:
        job = store.reanalyze(job_id, provider=body.provider,
                              instructions=body.instructions,
                              custom_prompt=body.custom_prompt)
    except KeyError:
        raise HTTPException(404, "Задача не найдена")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return job.to_public()


@app.get("/api/prompt/default")
def prompt_default():
    """The built-in analysis prompt, for the expert-mode editor."""
    return {"prompt": analyze.EXPERT_PROMPT_DEFAULT}


def _control(job_id: str, action: str):
    fn = {"pause": store.pause, "resume": store.resume, "cancel": store.cancel}[action]
    try:
        job = fn(job_id)
    except KeyError:
        raise HTTPException(404, "Задача не найдена")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return job.to_public()


@app.get("/api/jobs/{job_id}/partial")
def get_partial(job_id: str):
    """Live transcript-so-far for the streaming UI."""
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return {
        "status": job.status,
        "progress": job.progress,
        "segments": store.partial(job_id),
        "analysis": store.analysis_progress(job_id),
    }


@app.get("/api/jobs/{job_id}/result")
def get_result(job_id: str, format: str = "txt", provider: str = ""):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    if format not in {"txt", "srt", "json", "docx", "screen"}:
        raise HTTPException(400, "format должен быть txt | srt | json | docx | screen")

    # Word protocol: one document per engine. Pick the requested provider, or
    # default to the most recently generated one.
    if format == "docx":
        prov = provider or (job.docx_providers[-1] if job.docx_providers else "")
        if not prov:
            raise HTTPException(404, "Протокол ещё не сгенерирован")
        path = store.docx_path(job_id, prov)
        if not path.exists():
            raise HTTPException(404, "Протокол для этого движка отсутствует")
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{_safe_stem(job.filename)}_{prov}_протокол.docx",
        )

    # Allow download whenever the file exists — covers finished jobs and the
    # partial transcript saved when a job is cancelled. Still-running jobs
    # simply have no file yet and fall through to 404 below.
    fmt_file = "screen.txt" if format == "screen" else format
    path = store.result_path(job_id, fmt_file)
    if not path.exists():
        if job.status not in {STATUS_DONE, STATUS_CANCELLED}:
            raise HTTPException(409, f"Задача ещё не готова (статус: {job.status})")
        raise HTTPException(404, "Результат отсутствует")
    if format in ("txt", "screen"):
        return PlainTextResponse(path.read_text(encoding="utf-8"))
    media = "application/json" if format == "json" else "text/plain"
    return FileResponse(path, media_type=media,
                        filename=f"{_safe_stem(job.filename)}.{format}")


def _safe_stem(name: str | None) -> str:
    stem = Path(name or "audio").stem
    keep = "".join(c if c.isalnum() or c in "-_ " else "_" for c in stem).strip()
    return (keep or "audio")[:80]


@app.get("/api/diarization/status")
def diarization_status():
    """What's needed for speaker diarization (for the UI toggle hints)."""
    from .diarize import readiness
    return readiness()


class HfToken(BaseModel):
    token: str


@app.post("/api/diarization/token")
def diarization_token(body: HfToken):
    """Set the HuggingFace token (for diarization) at runtime; report readiness."""
    from .diarize import readiness
    token = body.token.strip()
    if not token:
        raise HTTPException(400, "Введите токен")
    config.set_hf_token(token)
    return readiness()


@app.get("/api/screen/status")
def screen_status():
    """What's needed for on-screen text capture (OCR) — for the UI toggle hints."""
    from .screen_ocr import readiness
    return readiness()


@app.get("/api/ollama/status")
def ollama_status():
    """Whether the local engine (Ollama) is installed/ready + install progress."""
    from . import ollama_setup
    return ollama_setup.status()


@app.post("/api/ollama/install")
def ollama_install():
    """Download & install Ollama + the protocol model on demand (background)."""
    from . import ollama_setup
    return ollama_setup.install()


@app.post("/api/ollama/install/cancel")
def ollama_install_cancel():
    """Request cancellation of an in-progress Ollama install."""
    from . import ollama_setup
    return ollama_setup.cancel()


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": config.MODEL, "diarization": config.DIARIZATION_ENABLED}
