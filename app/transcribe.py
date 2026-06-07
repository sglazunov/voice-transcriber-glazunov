"""faster-whisper wrapper. The model is loaded once and reused for every job."""
from __future__ import annotations

import threading
from dataclasses import dataclass, asdict
from typing import Callable, List, Optional

from faster_whisper import WhisperModel

from . import config

_model: Optional[WhisperModel] = None
_model_lock = threading.Lock()


def get_model() -> WhisperModel:
    """Lazily load the model once, guarded so two threads can't double-load it
    (which would blow the RAM budget on a 4 GB box)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = WhisperModel(
                    config.MODEL,
                    device=config.DEVICE,
                    compute_type=config.COMPUTE_TYPE,
                    cpu_threads=config.CPU_THREADS,
                )
    return _model


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: Optional[str] = None  # filled in later if diarization runs

    def to_dict(self) -> dict:
        return asdict(self)


def transcribe_file(
    audio_path: str,
    language: Optional[str] = None,
    on_segment: Optional[Callable[["Segment", float], None]] = None,
) -> tuple[List[Segment], dict]:
    """Transcribe an audio or video file.

    Video files (mp4/mkv/…) work directly — faster-whisper decodes the audio
    stream via PyAV/ffmpeg.

    on_segment(segment, total_seconds) is called for every segment as it is
    produced (faster-whisper yields them lazily), so the UI can stream the
    growing transcript and show real progress.
    """
    model = get_model()
    segments_iter, info = model.transcribe(
        audio_path,
        language=language or config.DEFAULT_LANGUAGE,
        vad_filter=config.VAD_FILTER,
        beam_size=config.BEAM_SIZE,
    )

    total = float(getattr(info, "duration", 0.0) or 0.0)
    out: List[Segment] = []
    for seg in segments_iter:
        s = Segment(start=seg.start, end=seg.end, text=seg.text.strip())
        out.append(s)
        if on_segment:
            on_segment(s, total)

    meta = {
        "language": getattr(info, "language", language),
        "language_probability": getattr(info, "language_probability", None),
        "duration": total,
        "model": config.MODEL,
    }
    return out, meta
