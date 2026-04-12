from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, Field


PARSE_TIMEOUT_SECONDS = 8
GENERATION_TIMEOUT_SECONDS = 20
HTTP_RETRY_ATTEMPTS = 1
TRANSIENT_RETRY_DELAYS = (1.0, 2.5)


class GeminiCommandPayload(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def _is_transient_gemini_error(message: str) -> bool:
    normalized = (message or "").lower()
    return any(
        token in normalized
        for token in (
            "503",
            "unavailable",
            "high demand",
            "handshake operation timed out",
            "_ssl.c",
            "ssl",
            "timed out",
            "timeout",
            "connection reset",
            "connection aborted",
            "temporary failure",
        )
    )


def _raise_humanized_gemini_error(exc: Exception) -> None:
    message = str(exc)
    normalized = message.lower()
    if "handshake operation timed out" in normalized or "_ssl.c" in normalized or "ssl" in normalized:
        raise RuntimeError("GEMINI_SSL_TIMEOUT: Yapay zeka servisine baglanirken SSL zaman asimi olustu.") from exc
    if "503" in normalized or "unavailable" in normalized or "high demand" in normalized:
        raise RuntimeError("GEMINI_UNAVAILABLE: Yapay zeka servisi gecici olarak yogun.") from exc
    if "timed out" in normalized or "timeout" in normalized:
        raise RuntimeError("GEMINI_TIMEOUT: Yapay zeka servisi zaman asimina ugradi.") from exc
    raise RuntimeError(f"GEMINI_ERROR: {message}") from exc


def _generate_with_retry(*, api_key: str, model: str, prompt: str, timeout_seconds: int) -> Any:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Gemini SDK kurulu degil. `pip install -r requirements.txt` calistirin.") from exc

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=timeout_seconds,
            retry_options=types.HttpRetryOptions(attempts=HTTP_RETRY_ATTEMPTS),
        ),
    )

    last_exc: Exception | None = None
    for attempt_index in range(len(TRANSIENT_RETRY_DELAYS) + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
        except Exception as exc:
            last_exc = exc
            if not _is_transient_gemini_error(str(exc)) or attempt_index >= len(TRANSIENT_RETRY_DELAYS):
                break
            time.sleep(TRANSIENT_RETRY_DELAYS[attempt_index])

    assert last_exc is not None
    _raise_humanized_gemini_error(last_exc)


def parse_command_with_gemini(
    *,
    api_key: str,
    model: str,
    prompt: str,
) -> GeminiCommandPayload:
    """Gemini ile yapılandırılmış komut ayrıştırma yap."""
    if not api_key:
        raise RuntimeError("Gemini API anahtari ayarlanmamis. config/settings.json veya GEMINI_API_KEY kullanin.")

    response = _generate_with_retry(
        api_key=api_key,
        model=model,
        prompt=prompt,
        timeout_seconds=PARSE_TIMEOUT_SECONDS,
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, GeminiCommandPayload):
        return parsed

    response_text = getattr(response, "text", "") or ""
    try:
        return GeminiCommandPayload.model_validate_json(response_text)
    except Exception as exc:
        raise RuntimeError(f"Gemini yaniti ayristrilamadi: {response_text[:500]}") from exc


def generate_powershell_script_with_gemini(
    *,
    api_key: str,
    model: str,
    prompt: str,
) -> dict[str, Any]:
    """Gemini ile JSON icinde PowerShell script uret."""
    if not api_key:
        raise RuntimeError("Gemini API anahtari ayarlanmamis. config/settings.json veya GEMINI_API_KEY kullanin.")

    response = _generate_with_retry(
        api_key=api_key,
        model=model,
        prompt=prompt,
        timeout_seconds=GENERATION_TIMEOUT_SECONDS,
    )
    response_text = getattr(response, "text", "") or ""
    try:
        payload = json.loads(response_text)
    except Exception as exc:
        raise RuntimeError(f"Gemini script yaniti ayristrilamadi: {response_text[:500]}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Gemini script yaniti JSON object degil.")
    return payload
