"""LLM provider abstraction for protocol generation.

Three providers, one tiny interface (`complete(prompt) -> text`):

  ollama     — fully local, free, offline (needs Ollama running)
  groq       — free cloud tier (OpenAI-compatible API)
  anthropic  — paid, per-token (highest quality)

Ollama and Groq are called over plain HTTP via the stdlib (no extra deps);
Anthropic uses its official SDK. Each provider is asked to return raw JSON —
parsing/validation happens in analyze.py.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol

from . import config


class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str, max_tokens: int = 2000, force_json: bool = True) -> str:
        """Send the prompt to the model and return its text response.

        force_json asks the backend to constrain the answer to valid JSON
        (used for the real analysis). Set False for a plain ping, e.g. when
        validating an API key.
        """
        ...


# ---------------------------------------------------------------------------
def _http_post_json(url: str, payload: dict, headers: dict, timeout: int = 180) -> dict:
    """POST a JSON body and return the parsed JSON response."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code} от {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Не удалось подключиться к {url}: {e.reason}") from e


# ---------------------------------------------------------------------------
class OllamaProvider:
    """Local Ollama server. Free, offline, no API key."""

    name = "ollama"

    def complete(self, prompt: str, max_tokens: int = 2000, force_json: bool = True) -> str:
        url = config.OLLAMA_URL.rstrip("/") + "/api/generate"
        payload = {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        }
        if force_json:
            payload["format"] = "json"  # constrain output to valid JSON
        out = _http_post_json(url, payload, headers={}, timeout=600)
        return (out.get("response") or "").strip()


# ---------------------------------------------------------------------------
class GroqProvider:
    """Groq cloud, OpenAI-compatible. Free tier, needs GROQ_API_KEY."""

    name = "groq"

    def complete(self, prompt: str, max_tokens: int = 2000, force_json: bool = True) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": config.GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if force_json:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}"}
        out = _http_post_json(url, payload, headers, timeout=180)
        return out["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
class AnthropicProvider:
    """Anthropic Claude. Paid per token, highest quality."""

    name = "anthropic"

    def complete(self, prompt: str, max_tokens: int = 2000, force_json: bool = True) -> str:
        # Claude follows the "return only JSON" instruction in the prompt well,
        # so force_json needs no special API flag here.
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "Пакет anthropic не установлен. Выполните: pip install anthropic"
            )
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=config.ANALYSIS_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()


_PROVIDERS = {
    "ollama": OllamaProvider,
    "groq": GroqProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(name: str | None) -> LLMProvider:
    """Resolve 'auto'/None to a concrete configured provider and instantiate it."""
    resolved = config.resolve_provider(name)
    return _PROVIDERS[resolved]()
