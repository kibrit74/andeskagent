from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, Field


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PARSE_TIMEOUT_SECONDS = 20
GENERATION_TIMEOUT_SECONDS = 40
HTTP_RETRY_ATTEMPTS = 1
TRANSIENT_RETRY_DELAYS = (1.0, 2.5)


class AgentCommandPayload(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def _is_transient_openrouter_error(message: str) -> bool:
    normalized = (message or "").lower()
    return any(
        token in normalized
        for token in (
            "429",
            "rate limit",
            "too many requests",
            "503",
            "unavailable",
            "overloaded",
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "connection error",
            "gateway",
            "bad gateway",
            "temporarily",
        )
    )


def _raise_humanized_openrouter_error(exc: Exception) -> None:
    message = str(exc)
    normalized = message.lower()
    if "429" in normalized or "rate limit" in normalized or "too many requests" in normalized:
        raise RuntimeError("OPENROUTER_RATE_LIMIT: OpenRouter oran sinirina takildi.") from exc
    if "503" in normalized or "unavailable" in normalized or "overloaded" in normalized:
        raise RuntimeError("OPENROUTER_UNAVAILABLE: OpenRouter gecici olarak yogun.") from exc
    if "timeout" in normalized or "timed out" in normalized:
        raise RuntimeError("OPENROUTER_TIMEOUT: OpenRouter zaman asimina ugradi.") from exc
    raise RuntimeError(f"OPENROUTER_ERROR: {message}") from exc


def _build_messages(prompt: str) -> list[dict[str, str]]:
    system = (
        "Cevabini SADECE gecerli JSON olarak ver. "
        "JSON disinda hicbir ek metin, aciklama, kod blogu veya isaretleyici yazma."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def _parse_json_content(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    if not content:
        raise RuntimeError("OpenRouter bos cevap dondurdu.")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenRouter JSON cikti veremedi: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenRouter yaniti JSON object degil.")
    return parsed


def _generate_with_retry(*, api_key: str, model: str, prompt: str, timeout_seconds: int) -> dict[str, Any]:
    try:
        from openai import OpenAI
        from openai import APIConnectionError, APITimeoutError, APIError, RateLimitError
    except ImportError as exc:
        raise RuntimeError("OpenAI SDK kurulu degil. `pip install openai` calistirin.") from exc

    client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
    last_exc: Exception | None = None

    for attempt_index in range(len(TRANSIENT_RETRY_DELAYS) + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=_build_messages(prompt),
                temperature=0,
                timeout=timeout_seconds,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content if response.choices else ""
            return _parse_json_content(content)
        except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as exc:
            last_exc = exc
            if not _is_transient_openrouter_error(str(exc)) or attempt_index >= len(TRANSIENT_RETRY_DELAYS):
                break
            time.sleep(TRANSIENT_RETRY_DELAYS[attempt_index])
        except Exception as exc:
            last_exc = exc
            if not _is_transient_openrouter_error(str(exc)) or attempt_index >= len(TRANSIENT_RETRY_DELAYS):
                break
            time.sleep(TRANSIENT_RETRY_DELAYS[attempt_index])

    assert last_exc is not None
    _raise_humanized_openrouter_error(last_exc)


def parse_command_with_openrouter(*, api_key: str, model: str, prompt: str) -> AgentCommandPayload:
    if not api_key:
        raise RuntimeError("OpenRouter API anahtari ayarlanmamis. OPENROUTER_API_KEY kullanin.")
    payload = _generate_with_retry(
        api_key=api_key,
        model=model,
        prompt=prompt,
        timeout_seconds=PARSE_TIMEOUT_SECONDS,
    )
    return AgentCommandPayload.model_validate(payload)


def generate_powershell_script_with_openrouter(*, api_key: str, model: str, prompt: str) -> dict[str, Any]:
    if not api_key:
        raise RuntimeError("OpenRouter API anahtari ayarlanmamis. OPENROUTER_API_KEY kullanin.")
    return _generate_with_retry(
        api_key=api_key,
        model=model,
        prompt=prompt,
        timeout_seconds=GENERATION_TIMEOUT_SECONDS,
    )
