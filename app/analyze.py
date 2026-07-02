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
import time

from . import llm

# Single-pass threshold. Above this we chunk (map-reduce) so the WHOLE meeting
# is analysed, not just the first part.
_MAX_CHARS = 16000
# Size of each chunk when the transcript is too long for one pass. Smaller
# chunks = more thorough extraction (the model reads each part more carefully).
_CHUNK_CHARS = 10000
# Overlap between chunks so a topic split across a boundary isn't lost.
_CHUNK_OVERLAP = 800
# Cap the number of chunks so a huge file doesn't fan out into too many calls;
# beyond this we grow the chunk size instead.
_MAX_CHUNKS = 16

# Shared description of the JSON shape we want back.
_SCHEMA = (
    "{{\n"
    '  "summary": "краткое описание о чём шёл разговор (4-6 предложений)",\n'
    '  "detailed": [\n'
    '    {{"topic": "Название темы", "details": "Очень подробно (5-10 предложений): что '
    'именно обсуждали по ЭТОЙ теме, какие были варианты и аргументы, конкретика, цифры, '
    'названия, примеры и к чему пришли"}}\n'
    "  ],\n"
    '  "key_thoughts": ["ключевая мысль/тезис 1", "..."],\n'
    '  "conclusions": ["вывод/итог 1", "вывод/итог 2"],\n'
    '  "decisions": ["принятое решение/договорённость 1", "..."],\n'
    '  "done_tasks": ["что уже сделано/выполнено к моменту встречи", "..."],\n'
    '  "tasks": ["крупная задача, которую нужно сделать (в общем виде, по сути работы)", "..."],\n'
    '  "minor_tasks": ["мелкая задача/доработка (в общем виде)", "..."]\n'
    "}}"
)

_RULES = (
    "ГЛАВНОЕ — ТОЧНОСТЬ, ПОЛНОТА и ЧЁТКОЕ РАЗДЕЛЕНИЕ ТЕМ. Опирайся СТРОГО на текст: "
    "ничего не выдумывай и не додумывай. Пройди по ВСЕЙ встрече от начала до конца и "
    "не упусти ни одной обсуждённой темы, договорённости или задачи. Сохраняй "
    "конкретику дословно: числа, проценты, сроки/даты, названия (модулей, тегов, "
    "систем, продуктов), термины. Если что-то сказано неуверенно или неясно из "
    "расшифровки — так и помечай («предположительно», «не до конца ясно»), но не "
    "пропускай.\n\n"
    "Правила:\n"
    "- БЕЗ СПИКЕРОВ. НЕ указывай, кто что сказал/предложил/возразил, не перечисляй "
    "участников и не привязывай пункты к именам или ролям. Протокол обезличенный — "
    "только суть обсуждения. Если в тексте встречаются метки вида «Спикер 1:», "
    "«Собеседник:» — ИГНОРИРУЙ их, бери только содержание реплик.\n"
    "- РАЗДЕЛЯЙ ТЕМЫ ЧЁТКО. Каждая тема в detailed — отдельный самостоятельный блок. "
    "НЕ смешивай разные темы в одном блоке и НЕ размазывай одну тему по нескольким. "
    "Если к теме возвращались в разных местах разговора — собери всё про неё в ОДИН "
    "блок. Разные вопросы — разные блоки. Не перескакивай между темами внутри блока.\n"
    "- Если в конце текста есть блок «ТЕКСТ С ЭКРАНА» — это распознанное содержимое "
    "того, что ПОКАЗЫВАЛИ на экране (слайды, код, документы, таблицы). Учитывай его "
    "наравне с речью; при необходимости добавь отдельную тему про показанное.\n"
    "- summary: 4-6 предложений, суть встречи в целом (без имён).\n"
    "- detailed: МАКСИМАЛЬНО ПОДРОБНЫЙ разбор по темам — раздели разговор на столько "
    "тем, сколько их реально было (обычно 6-15). По каждой теме 5-10 предложений: что "
    "именно обсуждали, какие были варианты и аргументы, конкретные детали, цифры, "
    "примеры, к чему в итоге пришли. Пиши развёрнуто и конкретно, НЕ обобщай и НЕ "
    "сокращай содержание, но и НЕ смешивай темы между собой.\n"
    "- key_thoughts: 8-15 ключевых тезисов и важных формулировок (по сути, без авторов).\n"
    "- conclusions: ВЫВОДЫ и итоги — к чему в целом пришли, оценка статуса/ситуации, "
    "общие заключения (4-8 пунктов).\n"
    "- decisions: что именно решили/договорились (пустой список, если решений нет).\n"
    "- done_tasks: что УЖЕ СДЕЛАНО/выполнено к моменту встречи (готово, закрыто, "
    "починено) — короткими формулировками, без имён.\n"
    "- tasks: что НУЖНО СДЕЛАТЬ — крупные задачи, сформулированные ОБОБЩЁННО, по сути "
    "работы, БЕЗ ответственных и без имён (например: «Доработать выгрузку отчётов», а "
    "НЕ «Сергею доработать…»).\n"
    "- minor_tasks: мелкие, второстепенные задачи и доработки (мелкие правки UI, "
    "договорённости об именовании — названия тегов/кнопок/сущностей, техдоделки) — "
    "тоже в общем виде, без имён.\n"
    "- Не путай сделанное с тем, что нужно сделать: done_tasks — прошедшее время, "
    "tasks и minor_tasks — будущее.\n"
    "- Не дублируй один и тот же факт в разных разделах.\n"
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
    "ошибки). Кратко по-русски, БЕЗ указания кто говорил, выпиши из ЭТОГО фрагмента:\n"
    "• Темы, которые обсуждались — каждую ОТДЕЛЬНЫМ пунктом, не смешивая разные темы; "
    "по каждой: что именно обсуждали, какие были варианты/аргументы, к чему пришли.\n"
    "• Ключевые мысли, решения и договорённости.\n"
    "• ВСЕ задачи и действия, включая мелкие (правки UI, договорённости об именовании "
    "— названия тегов/кнопок/сущностей, техдоделки). Формулируй ОБОБЩЁННО, по сути "
    "работы, БЕЗ привязки к людям.\n"
    "Выпиши ВСЁ существенное, ничего не пропускай. Сохраняй дословно числа, проценты, "
    "сроки/даты, названия и термины. Не выдумывай. Если есть метки спикеров — игнорируй "
    "их. Пиши списком, без вступления и заключения.\n\n"
    "Фрагмент:\n{chunk}"
)

# Reduce step: merge all chunk notes into the final protocol JSON.
_REDUCE_TEMPLATE = (
    "Ниже — заметки, собранные по последовательным частям одной рабочей встречи. "
    "Объедини их в ЕДИНЫЙ ПОДРОБНЫЙ протокол. ОБЪЕДИНЯЙ одинаковые темы из разных "
    "частей в ОДНУ тему (не создавай дублирующиеся темы и не дроби одну тему на "
    "несколько). Убери дословные повторы, но СОХРАНИ ВСЕ детали, темы, договорённости "
    "и задачи (включая мелкие) — НЕ сокращай содержательные пункты. Чётко разделяй "
    "разные темы между собой. НЕ указывай, кто что сказал; задачи формулируй "
    "обобщённо, без имён. Верни ответ ТОЛЬКО в виде JSON.\n\n"
    "Заметки по частям:\n{notes}\n\n"
    "Формат ответа:\n" + _SCHEMA + "\n\n" + _RULES
)


# The full instruction the model normally receives (everything except the
# transcript itself). Shown in "expert mode" so the user can edit it. Single
# braces here (no .format applied), unlike the templates above.
EXPERT_PROMPT_DEFAULT = (
    "Проанализируй транскрипцию рабочей встречи (она добавляется ниже; "
    "автоматическая расшифровка, возможны ошибки распознавания) и верни ответ "
    "ТОЛЬКО в виде JSON.\n\n"
    "Формат ответа:\n" + _SCHEMA.replace("{{", "{").replace("}}", "}") + "\n\n" + _RULES
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
    """Split transcript into line-aligned chunks with overlap (segments intact)."""
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
            # Carry the trailing ~_CHUNK_OVERLAP chars into the next chunk so a
            # topic spanning the boundary survives in both.
            ov: list[str] = []
            ov_len = 0
            for prev in reversed(cur):
                if ov_len + len(prev) > _CHUNK_OVERLAP:
                    break
                ov.insert(0, prev)
                ov_len += len(prev)
            cur, cur_len = ov[:], ov_len
        cur.append(line)
        cur_len += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


def _with_extra(prompt: str, extra: str) -> str:
    """Append the user's custom instructions to a prompt, if any."""
    extra = (extra or "").strip()
    if not extra:
        return prompt
    return (prompt + "\n\nДОПОЛНИТЕЛЬНЫЕ ТРЕБОВАНИЯ ПОЛЬЗОВАТЕЛЯ (обязательно учти "
            "их, но сохрани формат JSON и все поля):\n" + extra)


class AnalysisCancelled(RuntimeError):
    """Raised when the user cancels protocol generation mid-way."""


def _stream_complete(backend, prompt, max_tokens, on_progress, stage, force_json=True):
    """Call backend.complete, streaming tokens to on_progress when supported.

    Only Ollama streams; other providers return the full text in one shot (we
    still emit the stage so the UI shows what's happening)."""
    if on_progress:
        on_progress(stage, "")
    if on_progress and isinstance(backend, llm.OllamaProvider):
        return backend.complete(
            prompt, max_tokens=max_tokens, force_json=force_json,
            on_token=lambda full: on_progress(stage, full))
    return backend.complete(prompt, max_tokens=max_tokens, force_json=force_json)


def analyze_transcript(transcript_text: str, provider: str | None = None,
                       extra_instructions: str = "", custom_prompt: str = "",
                       on_progress=None, cancel_check=None) -> dict:
    """Send the transcript to the chosen LLM provider and return structured analysis.

    `provider` is one of "ollama" | "groq" | "gemini" | "yandex" | "gigachat" |
    "anthropic" | "auto" | None.
    `extra_instructions` — optional free-form text appended to the prompt.
    `custom_prompt` — EXPERT MODE: a full replacement for the built-in instruction
    (the transcript / notes are still appended by the app). If it doesn't ask for
    the same JSON fields, the Word export may come out empty — caller's risk.
    `on_progress(stage, text)` — optional callback for the live UI: `stage` is a
    human label, `text` is the growing generated text (Ollama streams it).
    Returns a dict with keys: summary, detailed, key_thoughts, conclusions,
    decisions, done_tasks, tasks, minor_tasks, _provider.
    """
    backend = llm.get_provider(provider)
    text = (transcript_text or "").strip()
    custom = (custom_prompt or "").strip()

    def _ck():
        if cancel_check and cancel_check():
            raise AnalysisCancelled()

    _ck()
    if len(text) <= _MAX_CHARS:
        if custom:
            prompt = custom + "\n\nТранскрипция:\n" + text
        else:
            prompt = _PROMPT_TEMPLATE.format(transcript=text)
        raw = _stream_complete(backend, _with_extra(prompt, extra_instructions),
                               8000, on_progress, "Генерация протокола…")
    else:
        chunks = _split_chunks(text)
        notes_parts = []
        for i, chunk in enumerate(chunks, 1):
            _ck()  # cancel between chunks
            note = _stream_complete(
                backend, _MAP_TEMPLATE.format(i=i, n=len(chunks), chunk=chunk),
                2600, on_progress, f"Читаю встречу: часть {i} из {len(chunks)}…",
                force_json=False)
            notes_parts.append(f"=== Часть {i} ===\n{note.strip()}")
            # Free cloud tiers rate-limit easily; pace the chunk calls a bit.
            if backend.name == "groq" and i < len(chunks):
                time.sleep(2)
        notes = "\n\n".join(notes_parts)
        _ck()  # cancel before the final merge
        if custom:
            prompt = (custom + "\n\nНиже — заметки по последовательным частям "
                      "встречи; объедини их в итог по требованиям выше:\n" + notes)
        else:
            prompt = _REDUCE_TEMPLATE.format(notes=notes)
        raw = _stream_complete(backend, _with_extra(prompt, extra_instructions),
                               8000, on_progress, "Свожу протокол…")

    result = _extract_json(raw)

    # Normalise — guarantee the shape the rest of the app expects.
    result.setdefault("summary", "")
    result.setdefault("detailed", [])
    result.pop("participants", None)  # protocol is speaker-agnostic now
    # Plain string lists.
    for list_key in ("key_thoughts", "conclusions", "decisions"):
        val = result.get(list_key, [])
        if isinstance(val, str):
            val = [val] if val.strip() else []
        result[list_key] = [str(x).strip() for x in val if str(x).strip()]
    # Task lists are plain, general statements (no per-person owner).
    for list_key in ("done_tasks", "tasks", "minor_tasks"):
        result[list_key] = _normalise_tasks(result.get(list_key, []))
    result["detailed"] = _normalise_detailed(result["detailed"])
    result["_provider"] = backend.name
    return result


def _normalise_tasks(tasks) -> list[str]:
    """Coerce a task list into plain strings, tolerating dicts (incl. old data
    that carried an owner — the text is kept, the owner is dropped)."""
    if not tasks:
        return []
    if isinstance(tasks, str):
        tasks = [tasks]
    out = []
    for item in tasks:
        if isinstance(item, dict):
            text = str(item.get("task") or item.get("title") or item.get("text") or "").strip()
        else:
            text = str(item).strip()
        if text:
            out.append(text)
    return out


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
