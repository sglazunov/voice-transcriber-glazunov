"""AI-powered transcript analysis using the Claude API."""
from __future__ import annotations

import json
import re
from typing import Optional


def analyze_transcript(transcript_text: str) -> dict:
    """Send transcript to Claude and return structured analysis.

    Returns dict with keys: summary, key_thoughts, tasks.
    Raises RuntimeError if API key is not configured or package missing.
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "Пакет anthropic не установлен. Выполните: pip install anthropic"
        )

    from . import config

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "Переменная окружения ANTHROPIC_API_KEY не задана. "
            "Добавьте её в run.bat: set ANTHROPIC_API_KEY=sk-ant-..."
        )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Truncate very long transcripts to stay within token budget
    text = transcript_text[:20000]

    prompt = (
        "Проанализируй транскрипцию встречи/переговоров и верни ответ ТОЛЬКО в виде JSON "
        "(без markdown-блоков, без пояснений).\n\n"
        f"Транскрипция:\n{text}\n\n"
        "Формат ответа:\n"
        "{\n"
        '  "summary": "описание о чём шёл разговор (3-5 предложений)",\n'
        '  "key_thoughts": ["ключевая мысль 1", "ключевая мысль 2", ...],\n'
        '  "tasks": ["задача 1", "задача 2", ...]\n'
        "}\n\n"
        "Правила:\n"
        "- summary: 3-5 предложений, суть разговора своими словами\n"
        "- key_thoughts: 5-10 ключевых тезисов, выводов, договорённостей\n"
        "- tasks: конкретные действия и задачи из разговора (пустой список если задач нет)\n"
        "- Всё на русском языке\n"
        "- Только JSON, никакого другого текста"
    )

    message = client.messages.create(
        model=config.ANALYSIS_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if the model added them anyway
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    result = json.loads(raw)

    # Normalise — ensure all expected keys exist
    result.setdefault("summary", "")
    result.setdefault("key_thoughts", [])
    result.setdefault("tasks", [])
    return result
