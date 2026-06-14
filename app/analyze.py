"""Transcript analysis: turn a raw transcript into a structured protocol.

The actual LLM call is delegated to a pluggable provider (see llm.py), so the
same analysis works with a free local model (Ollama), a free cloud model
(Groq) or a paid one (Claude). This module owns the prompt, long-transcript
chunking and the parsing/validation of the model's JSON answer.

Long meetings are the common case, so transcripts longer than a single context
window are processed map-reduce style: each chunk is summarised into notes,
then all notes are merged into the final protocol. This is what lets minor /
late tasks (e.g. a tag-naming aside near the end) survive instead of being
truncated away.
"""
from __future__ import annotations

import json
import re

from . import llm

# Single-pass threshold. Above this we chunk (map-reduce) so the WHOLE meeting
# is analysed, not just the first part.
_MAX_CHARS = 18000
# Size of each chunk when the transcript is too long for one pass.
_CHUNK_CHARS = 14000
# Cap the number of chunks so a huge file doesn't fan out into too many calls;
# beyond this we grow the chunk size instead.
_MAX_CHUNKS = 10

# Shared description of the JSON shape we want back.
_SCHEMA = (
    "{{\n"
    '  "summary": "краткое описание о чём шёл разговор (3-5 предложений)",\n'
    '  "detailed": [\n'
    '    {{"topic": "Название темы", "details": "Подробно: что обсуждали, кто что '
    'предложил, аргументы и возражения, цифры, к чему пришли"}}\n'
    "  ],\n"
    '  "key_thoughts": ["ключевая мысль 1", "ключевая мысль 2"],\n'
    '  "decisions": ["принятое решение/договорённость 1", "..."],\n'
    '  "tasks": ["крупная задача 1", "крупная задача 2"],\n'
    '  "minor_tasks": ["мелкая задача/доработка 1", "..."]\n'
    "}}"
)

_RULES = (
    "Правила:\n"
    "- summary: 3-5 предложений, суть встречи в целом.\n"
    "- detailed: ПОДРОБНЫЙ разбор по темам — раздели разговор на 4-9 тем/блоков. "
    "По каждой теме 3-6 предложений: что именно обсуждали, какие были мнения, цифры, "
    "решения, спорные моменты. Это самая важная часть — пиши детально и конкретно, "
    "ничего важного не упускай.\n"
    "- key_thoughts: 6-12 ключевых тезисов и выводов.\n"
    "- decisions: что именно решили/договорились (пустой список, если решений нет).\n"
    "- tasks: крупные задачи и действия из разговора.\n"
    "- minor_tasks: ОБЯЗАТЕЛЬНО выпиши и мелкие, второстепенные задачи и доработки — "
    "то, что прозвучало вскользь: мелкие правки UI, договорённости об именовании "
    "(названия тегов, кнопок, сущностей), кто кому что скинет/даст доступ, мелкие "
    "технические доделки. Не сворачивай их в одну строку — перечисли по пунктам.\n"
    "- Всё на русском языке. Верни ТОЛЬКО JSON, без markdown и пояснений."
)

_PROMPT_TEMPLATE = (
    "Проанализируй транскрипцию рабочей встречи (автоматическая расшифровка, возможны "
    "ошибки распознавания имён и терминов) и верни ответ ТОЛЬКО в виде JSON.\n\n"
    "Транскрипция:\n{transcript}\n\n"
    "Формат ответа:\n" + _SCHEMA + "\n\n" + _RULES
)

# Map step: condense one chunk into plain-text notes (not JSON).
_MAP_TEMPLATE = (
    "Это часть {i} из {n} расшифровки рабочей встречи (автоматическая, возможны "
    "ошибки). Кратко по-русски выпиши из ЭТОГО фрагмента:\n"
    "• Темы, которые обсуждались.\n"
    "• Ключевые мысли, решения и договорённости.\n"
    "• ВСЕ задачи и действия, включая мелкие и второстепенные (мелкие правки UI, "
    "договорённости об именовании — названия тегов/кнопок/сущностей, кто кому даёт "
    "доступ/что-то скидывает, мелкие техдоделки).\n"
    "Пиши списком, без вступления и заключения. Сохраняй конкретику.\n\n"
    "Фрагмент:\n{chunk}"
)

# Reduce step: merge all chunk notes into the final protocol JSON.
_REDUCE_TEMPLATE = (
    "Ниже — заметки, собранные по последовательным частям одной рабочей встречи. "
    "Объедини их в единый протокол, убери дубли, сохрани все детали и все задачи "
    "(включая мелкие). Верни ответ ТОЛЬКО в виде JSON.\n\n"
    "Заметки по частям:\n{notes}\n\n"
    "Формат ответа:\n" + _SCHEMA + "\n\n" + _RULES
)


def _extract_json(raw: str) -> dict:
    """Parse the model's answer into a dict, tolerating code fences / stray text."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _split_chunks(text: str) -> list[str]:
    """Split transcript into line-aligned chunks (keeps segments intact)."""
    size = _CHUNK_CHARS
    # Grow chunk size if we'd otherwise exceed the chunk cap.
    if len(text) > size * _MAX_CHUNKS:
        size = len(text) // _MAX_CHUNKS + 1
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > size and cur:
            chunks.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


def analyze_transcript(transcript_text: str, provider: str | None = None) -> dict:
    """Send the transcript to the chosen LLM provider and return structured analysis.

    `provider` is one of "ollama" | "groq" | "anthropic" | "auto" | None.
    Returns a dict with keys: summary, detailed, key_thoughts, decisions, tasks,
    minor_tasks, _provider. Raises RuntimeError if no provider is configured or
    the call fails.
    """
    backend = llm.get_provider(provider)
    text = (transcript_text or "").strip()

    if len(text) <= _MAX_CHARS:
        raw = backend.complete(_PROMPT_TEMPLATE.format(transcript=text), max_tokens=4000)
    else:
        chunks = _split_chunks(text)
        notes_parts = []
        for i, chunk in enumerate(chunks, 1):
            note = backend.complete(
                _MAP_TEMPLATE.format(i=i, n=len(chunks), chunk=chunk),
                max_tokens=1400,
                force_json=False,
            )
            notes_parts.append(f"=== Часть {i} ===\n{note.strip()}")
        notes = "\n\n".join(notes_parts)
        raw = backend.complete(_REDUCE_TEMPLATE.format(notes=notes), max_tokens=4000)

    result = _extract_json(raw)

    # Normalise — guarantee the shape the rest of the app expects.
    result.setdefault("summary", "")
    result.setdefault("detailed", [])
    for list_key in ("key_thoughts", "decisions", "tasks", "minor_tasks"):
        val = result.get(list_key, [])
        if isinstance(val, str):
            val = [val] if val.strip() else []
        result[list_key] = [str(x).strip() for x in val if str(x).strip()]
    result["detailed"] = _normalise_detailed(result["detailed"])
    result["_provider"] = backend.name
    return result


def _normalise_detailed(detailed) -> list[dict]:
    """Coerce the 'detailed' field into a list of {topic, details} dicts.

    Free models sometimes return a plain string, a list of strings, or a dict
    of topic->text instead of the requested list of objects.
    """
    if not detailed:
        return []
    if isinstance(detailed, str):
        return [{"topic": "", "details": detailed}]
    if isinstance(detailed, dict):
        return [{"topic": str(k), "details": str(v)} for k, v in detailed.items()]
    out = []
    for item in detailed:
        if isinstance(item, dict):
            topic = str(item.get("topic") or item.get("title") or "").strip()
            details = str(item.get("details") or item.get("text") or "").strip()
            if topic or details:
                out.append({"topic": topic, "details": details})
        elif isinstance(item, str) and item.strip():
            out.append({"topic": "", "details": item.strip()})
    return out
