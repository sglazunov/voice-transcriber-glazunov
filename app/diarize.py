"""Optional speaker diarization via pyannote.audio.

This is intentionally isolated and lazy-imported: pyannote + torch do NOT fit
in 4 GB RAM alongside Whisper, so it stays OFF by default (VTX_DIARIZATION=0).
Enable it only after a RAM upgrade and after setting HF_TOKEN.

It assigns a speaker label to each transcript segment by majority time overlap
with the diarization turns.
"""
from __future__ import annotations

from typing import List

from . import config
from .transcribe import Segment

_pipeline = None


class DiarizationUnavailable(RuntimeError):
    pass


def _get_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    if not config.HF_TOKEN:
        raise DiarizationUnavailable(
            "HF_TOKEN is not set. Get a token at https://huggingface.co/settings/tokens "
            "and accept the terms for pyannote/speaker-diarization-3.1."
        )
    try:
        from pyannote.audio import Pipeline  # heavy import, only when needed
    except ImportError as e:
        raise DiarizationUnavailable(
            "pyannote.audio is not installed. Run: pip install pyannote.audio torch"
        ) from e

    _pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=config.HF_TOKEN
    )
    return _pipeline


def diarize(wav_path: str, segments: List[Segment]) -> List[Segment]:
    """Mutate `segments` in place, setting `.speaker`, and return them.

    Speaker labels are normalised to 'Спикер 1', 'Спикер 2', ... in order of
    first appearance.
    """
    pipeline = _get_pipeline()
    annotation = pipeline(wav_path)

    # Build a list of (start, end, raw_label) turns.
    turns = [(t.start, t.end, label) for t, _, label in annotation.itertracks(yield_label=True)]

    label_map: dict[str, str] = {}

    def nice(raw: str) -> str:
        if raw not in label_map:
            label_map[raw] = f"Спикер {len(label_map) + 1}"
        return label_map[raw]

    for seg in segments:
        best_label, best_overlap = None, 0.0
        for ts, te, raw in turns:
            overlap = min(seg.end, te) - max(seg.start, ts)
            if overlap > best_overlap:
                best_overlap, best_label = overlap, raw
        seg.speaker = nice(best_label) if best_label is not None else "Спикер ?"
    return segments
