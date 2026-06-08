"""Transcript analysis: turn a raw transcript into a structured protocol.

The actual LLM call is delegated to a pluggable provider (see llm.py), so the
same analysis works with a free local model (Ollama), a free cloud model
(Groq) or a paid one (Claude). This module only owns the prompt and the
parsing/validation of the model's JSON answer.
"""
from __future__ import annotations

import json
import re

from . import llm

# Keep transcripts within a sane token budget. Smaller free models also cope
# better with a bounded context.
_MAX_CHARS = 20000

_PROMPT_TEMPLATE = (
    "Проанализируй транскрипцию встречи/переговоров и верни ответ ТОЛЬКО в виде JSON "
    "(без markdown-блоков, без пояснений).\n\n"
    "Транскрипция:\n{transcript}\n\n"
    "Формат ответа:\n"
    "{{\n"
    '  "summary": "описание о чём шёл разговор (3-5 предложений)",\n'
    '  "key_thoughts": ["ключевая мысль 1", "ключевая мысль 2"],\n'
    '  "tasks": ["задача 1", "задача 2"]\n'
    "}}\n\n"
    "Правила:\n"
    "- summary: 3-5 предложений, суть разговора своими словами\n"
    "- key_thoughts: 5-10 ключевых тезисов, выводов, договорённостей\n"
    "- tasks: конкретные действия и задачи из разговора (пустой список если задач нет)\n"
    "- Всё на русском языке\n"
    "- Только JSON, никакого другого текста"
)


def _extract_json(raw: str) -> dict:
    """Parse the model's answer into a dict, tolerating code fences / stray text."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fall back to the first {...} block (free models sometimes add prose).
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def analyze_transcript(transcript_text: str, provider: str | None = None) -> dict:
    """Send the transcript to the chosen LLM provider and return structured analysis.

    `provider` is one of "ollama" | "groq" | "anthropic" | "auto" | None.
    Returns a dict with keys: summary, key_thoughts, tasks, _provider.
    Raises RuntimeError if no provider is configured or the call fails.
    """
    backend = llm.get_provider(provider)
    prompt = _PROMPT_TEMPLATE.format(transcript=transcript_text[:_MAX_CHARS])

    raw = backend.complete(prompt, max_tokens=2000)
    result = _extract_json(raw)

    # Normalise — guarantee the shape the rest of the app expects.
    result.setdefault("summary", "")
    result.setdefault("key_thoughts", [])
    result.setdefault("tasks", [])
    # Coerce to lists in case a model returns a single string.
    if isinstance(result["key_thoughts"], str):
        result["key_thoughts"] = [result["key_thoughts"]]
    if isinstance(result["tasks"], str):
        result["tasks"] = [result["tasks"]]
    result["_provider"] = backend.name
    return result
