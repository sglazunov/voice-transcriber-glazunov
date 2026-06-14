"""FastAPI app: web upload UI + REST API for transcription jobs."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config, llm
from .jobs import store, STATUS_DONE, STATUS_ANALYZING, STATUS_CANCELLED


def _provider_list() -> list[dict]:
    """Currently configured/available providers with display labels."""
    return [
        {"id": p, "label": config.PROVIDER_LABELS.get(p, p)}
        for p in config.available_providers()
    ]

app = FastAPI(title="Voice Transcriber", version="1.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac",
               ".mp4", ".mkv", ".webm", ".mov", ".wma", ".amr"}


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
            "max_upload_mb": config.MAX_UPLOAD_MB,
        },
    )


# ---- REST API -------------------------------------------------------------
@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    language: str = Form(config.DEFAULT_LANGUAGE),
    diarize: bool = Form(False),
    analyze: bool = Form(False),
    provider: str = Form("auto"),
    hint: str = Form(""),
    glossary: str = Form(""),
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

    want_diar = diarize and config.DIARIZATION_ENABLED
    want_analyze = analyze and bool(config.available_providers())
    job = store.create(file.filename, str(dest), language, want_diar,
                       initial_prompt=hint.strip(), glossary=glossary.strip(),
                       analyze=want_analyze, provider=provider)
    return JSONResponse({"job_id": job.id, **job.to_public()}, status_code=201)


@app.get("/api/jobs")
def list_jobs():
    return [j.to_public() for j in store.list()]


# ---- LLM providers (protocol engine) --------------------------------------
class ProviderKey(BaseModel):
    provider: str
    api_key: str


@app.get("/api/providers")
def list_providers():
    """All known providers + which are currently usable (for the UI picker)."""
    avail = set(config.available_providers())
    return {
        "available": config.available_providers(),
        "providers": [
            {
                "id": p,
                "label": config.PROVIDER_LABELS.get(p, p),
                "available": p in avail,
                "needs_key": p in {"anthropic", "groq"},
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
    if provider not in {"anthropic", "groq"}:
        raise HTTPException(400, "Ключ поддерживается только для Claude (anthropic) и Groq")
    if not key:
        raise HTTPException(400, "Введите ключ")

    # Tentatively set the key, then validate with a cheap non-JSON ping so a
    # bad key fails fast and is rolled back.
    previous = config.ANTHROPIC_API_KEY if provider == "anthropic" else config.GROQ_API_KEY
    config.set_provider_key(provider, key)
    try:
        llm.get_provider(provider).complete("Ответь одним словом: ok",
                                            max_tokens=5, force_json=False)
    except Exception as e:
        config.set_provider_key(provider, previous)  # roll back the bad key
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
    }


@app.get("/api/jobs/{job_id}/result")
def get_result(job_id: str, format: str = "txt"):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    if format not in {"txt", "srt", "json", "docx"}:
        raise HTTPException(400, "format должен быть txt | srt | json | docx")

    # Allow download whenever the file exists — covers finished jobs and the
    # partial transcript saved when a job is cancelled. Still-running jobs
    # simply have no file yet and fall through to 404 below.
    path = store.result_path(job_id, format)
    if not path.exists():
        if job.status not in {STATUS_DONE, STATUS_CANCELLED}:
            raise HTTPException(409, f"Задача ещё не готова (статус: {job.status})")
        raise HTTPException(404, "Результат отсутствует")
    if format == "txt":
        return PlainTextResponse(path.read_text(encoding="utf-8"))
    if format == "docx":
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{_safe_stem(job.filename)}_протокол.docx",
        )
    media = "application/json" if format == "json" else "text/plain"
    return FileResponse(path, media_type=media,
                        filename=f"{_safe_stem(job.filename)}.{format}")


def _safe_stem(name: str | None) -> str:
    stem = Path(name or "audio").stem
    keep = "".join(c if c.isalnum() or c in "-_ " else "_" for c in stem).strip()
    return (keep or "audio")[:80]


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": config.MODEL, "diarization": config.DIARIZATION_ENABLED}
