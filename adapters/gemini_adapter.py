from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class GeminiCommandPayload(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def parse_command_with_gemini(
    *,
    api_key: str,
    model: str,
    prompt: str,
) -> GeminiCommandPayload:
    """Gemini ile yapılandırılmış komut ayrıştırma yap."""
    if not api_key:
        raise RuntimeError("Gemini API anahtari ayarlanmamis. config/settings.json veya GEMINI_API_KEY kullanin.")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Gemini SDK kurulu degil. `pip install -r requirements.txt` calistirin.") from exc

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
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

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Gemini SDK kurulu degil. `pip install -r requirements.txt` calistirin.") from exc

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )
    response_text = getattr(response, "text", "") or ""
    try:
        payload = json.loads(response_text)
    except Exception as exc:
        raise RuntimeError(f"Gemini script yaniti ayristrilamadi: {response_text[:500]}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Gemini script yaniti JSON object degil.")
    return payload
