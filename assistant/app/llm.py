"""LLM client: any OpenAI-compatible ``/chat/completions`` endpoint.

Works with OpenAI, Groq, OpenRouter, Together, Azure (via OAI shim) and local
Ollama (``LLM_BASE_URL=http://localhost:11434/v1``, any dummy key). Uses only
``urllib`` from the standard library - no SDK dependency - with timeouts and
one retry on transient failures. Callers must handle :class:`LLMError` and
fall back to the offline brain so the UI never dead-ends.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import config


class LLMError(Exception):
    """Raised when the LLM provider is unreachable or returns an error."""


def chat(messages: list[dict], temperature: float = 0.4, max_tokens: int = 900) -> str:
    if not config.llm_enabled():
        raise LLMError("No LLM API key configured.")
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        f"{config.LLM_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "User-Agent": "CareBridge-Assistant/1.0",
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(2):  # one retry on transient errors
        try:
            with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
            choices = body.get("choices") or []
            if not choices:
                raise LLMError(f"LLM returned no completion: {str(body)[:200]}")
            content = (choices[0].get("message") or {}).get("content", "").strip()
            if not content:
                raise LLMError("LLM returned an empty response.")
            return content
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            last_error = LLMError(f"LLM API error (HTTP {exc.code}): {detail}")
            if exc.code < 500 and exc.code != 429:
                break  # 4xx (bad key/model) won't fix itself on retry
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = LLMError(f"Could not reach the LLM API: {exc}")
        except (ValueError, KeyError) as exc:
            last_error = LLMError(f"Unexpected LLM response format: {exc}")
            break
        if attempt == 0:
            time.sleep(1.0)
    assert last_error is not None
    raise last_error


def status() -> dict:
    return {
        "enabled": config.llm_enabled(),
        "model": config.LLM_MODEL if config.llm_enabled() else None,
        "base_url": config.LLM_BASE_URL if config.llm_enabled() else None,
        "mode": "llm" if config.llm_enabled() else "offline-demo",
        "hint": None if config.llm_enabled() else
        "Set LLM_API_KEY (and optionally LLM_BASE_URL / LLM_MODEL) to enable open-ended AI answers. "
        "Document Q&A, summaries, notes, tasks and reminders already work offline.",
    }
