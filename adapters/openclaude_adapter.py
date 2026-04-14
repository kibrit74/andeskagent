"""OpenClaude (Claude Code CLI) adapter.

Claude Code CLI'i MCP tool server ile birlikte calistirarak
masaustu otomasyonu, dosya islemleri ve sistem yonetimi yapabilir.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import AppSettings


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OpenClaudeResponse:
    result: str = ""
    session_id: str = ""
    duration_ms: float = 0.0
    duration_api_ms: float = 0.0
    num_turns: int = 0
    total_cost_usd: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    model_usage: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# CLI resolution
# ---------------------------------------------------------------------------

def _resolve_openclaude_command(command: str) -> str:
    candidate = (command or "").strip() or "openclaude"
    resolved = shutil.which(candidate)
    if resolved:
        return resolved

    path = Path(candidate)
    if path.exists():
        return str(path.resolve())

    raise RuntimeError(
        "OpenClaude CLI bulunamadi. `npm install -g @gitlawb/openclaude` kurun "
        "veya OPENCLAUDE_COMMAND ile tam yolu belirtin."
    )


# ---------------------------------------------------------------------------
# Environment builder
# ---------------------------------------------------------------------------

def _build_openclaude_env(settings: AppSettings) -> dict[str, str]:
    env = os.environ.copy()
    api_key = (settings.openclaude_api_key or settings.openrouter_api_key or env.get("OPENAI_API_KEY", "")).strip()
    model = (settings.openclaude_model or env.get("OPENAI_MODEL", "")).strip()
    base_url = (settings.openclaude_base_url or env.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")).strip()

    if not api_key:
        raise RuntimeError(
            "OpenClaude icin API anahtari eksik. OPENCLAUDE_OPENAI_API_KEY "
            "veya OPENROUTER_API_KEY ayarlayin."
        )
    if not model:
        raise RuntimeError(
            "OpenClaude icin model eksik. OPENCLAUDE_OPENAI_MODEL "
            "veya openclaude_model ayarlayin."
        )

    env["CLAUDE_CODE_USE_OPENAI"] = "1"
    env["OPENAI_API_KEY"] = api_key
    env["OPENAI_MODEL"] = model
    env["OPENAI_BASE_URL"] = base_url
    return env


def _is_usage_limit_message(text: str) -> bool:
    normalized = (text or "").lower()
    return "usage limit" in normalized or "upgrade to pro" in normalized


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

_DEFAULT_SYSTEM_PROMPT = """\
Sen TeknikAjan, bir Windows uzaktan teknik destek ajanisin.
Gorevlerin:
- Kullanicinin dogal dil komutlarini anlayip uygun MCP tool'larini cagirmak
- Dosya islemleri (arama, acma, kopyalama, tasima, silme, klasor olusturma)
- Masaustu otomasyonu (uygulama acma, pencere yonetimi, UI tiklama/yazma)
- Agent tarayici ile web aramasi ve site gezintisi
- E-posta gonderimi (dosya ekli)
- Sistem durumu sorgulama ve script calistirma
- PowerShell ile ileri otomasyon

Kurallar:
- Her zaman Turkce yanit ver.
- Oncelikle mevcut MCP tool'larini kullan (search_files, open_application, vb.)
- Kullanici tarayicidan, Google'da, webde veya internette arama istiyorsa search_web tool'unu kullan.
- search_web icin varsayilan engine=duckduckgo kullan; Google otomasyon oturumunu CAPTCHA'ya dusurebilir.
- Kullanici web sitesine gitmek istiyorsa navigate_agent_browser tool'unu kullan.
- Web aramasi icin search_files kullanma; search_files sadece yerel dosya aramasidir.
- Google/web aramasi icin open_application ile normal Chrome acma; agent tarayici tool'larini kullan.
- Tool cagrisinin sonucunu kullaniciya ozet olarak raporla.
- Silme, formatlama, registry degistirme gibi tehlikeli islemlerde dikkatli ol.
- Birden fazla adim gerektiren islemleri sirasyla tool cagrilariyla coz.
- Sonuclari kisa ve net tut.
"""


def _build_system_prompt(settings: AppSettings) -> str:
    custom = getattr(settings, "openclaude_system_prompt", None)
    if custom and str(custom).strip():
        return str(custom).strip()
    return _DEFAULT_SYSTEM_PROMPT.strip()


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------

def _extract_tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Claude CLI JSON ciktisindaki tool kullanim bilgilerini cikarir."""
    tool_calls: list[dict[str, Any]] = []

    # messages icinde tool_use bloklarini ara
    messages = payload.get("messages", [])
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls.append({
                            "tool": block.get("name", ""),
                            "input": block.get("input", {}),
                            "id": block.get("id", ""),
                        })
            elif isinstance(content, str) and "tool_use" in content:
                try:
                    parsed_content = json.loads(content)
                    if isinstance(parsed_content, dict) and parsed_content.get("type") == "tool_use":
                        tool_calls.append({
                            "tool": parsed_content.get("name", ""),
                            "input": parsed_content.get("input", {}),
                        })
                except (json.JSONDecodeError, TypeError):
                    pass

    return tool_calls


def _parse_openclaude_output(stdout: str, stderr: str) -> OpenClaudeResponse:
    payload_text = (stdout or "").strip()
    if not payload_text:
        raise RuntimeError(stderr.strip() or "OpenClaude bos cevap dondurdu.")
    if not payload_text.startswith("{"):
        for line in payload_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("{"):
                payload_text = stripped
                break

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        combined = f"{payload_text}\n{stderr or ''}".strip()
        if _is_usage_limit_message(combined):
            raise RuntimeError(
                "OpenClaude kullanim limiti doldu. Limit acilana kadar bekleyin veya baska bir model/saglayiciya gecin."
            ) from exc
        raise RuntimeError(
            f"OpenClaude JSON cikti veremedi. stdout={payload_text[:500]!r} stderr={stderr[:500]!r}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError("OpenClaude yaniti JSON object degil.")
    if payload.get("type") != "result":
        raise RuntimeError(f"OpenClaude beklenmeyen cikti dondurdu: {payload.get('type')!r}")
    if payload.get("is_error"):
        errors = payload.get("errors") or []
        message = (
            "; ".join(str(item) for item in errors if item)
            or str(payload.get("result", "") or "").strip()
            or str(payload.get("subtype", "") or "").strip()
            or "OpenClaude hata dondurdu."
        )
        raise RuntimeError(message)

    result_text = str(payload.get("result", "") or "").strip()
    if not result_text:
        structured = payload.get("structured_output")
        if structured is not None:
            result_text = json.dumps(structured, ensure_ascii=False, indent=2)

    tool_calls = _extract_tool_calls(payload)

    model_usage = payload.get("modelUsage", payload.get("model_usage", {}))

    return OpenClaudeResponse(
        result=result_text,
        session_id=str(payload.get("session_id", "") or ""),
        duration_ms=float(payload.get("duration_ms", 0.0) or 0.0),
        duration_api_ms=float(payload.get("duration_api_ms", 0.0) or 0.0),
        num_turns=int(payload.get("num_turns", 0) or 0),
        total_cost_usd=float(payload.get("total_cost_usd", 0.0) or 0.0),
        usage=dict(payload.get("usage", {}) or {}),
        model_usage=dict(model_usage or {}),
        tool_calls=tool_calls,
        raw=payload,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_openclaude_prompt(
    prompt: str,
    settings: AppSettings,
    working_directory: str | os.PathLike[str],
    *,
    system_prompt: str | None = None,
) -> OpenClaudeResponse:
    """Claude Code CLI'i MCP tool server ile birlikte calistirir.

    Args:
        prompt: Kullanici komutu
        settings: Uygulama ayarlari
        working_directory: Calisma dizini
        system_prompt: Opsiyonel system prompt override
    """
    cleaned_prompt = (prompt or "").strip()
    if not cleaned_prompt:
        raise RuntimeError("OpenClaude icin bos komut gonderilemez.")

    effective_system_prompt = system_prompt or _build_system_prompt(settings)
    workdir = Path(working_directory).resolve()
    mcp_config_path = workdir / ".mcp.json"

    command = [
        _resolve_openclaude_command(settings.openclaude_command),
        "--print",
        cleaned_prompt,
        "--output-format",
        "json",
        "--provider",
        "openai",
        "--system-prompt",
        effective_system_prompt,
        "--allowedTools",
        "mcp__teknikajan__*",
    ]
    if mcp_config_path.exists():
        command.extend(["--mcp-config", str(mcp_config_path), "--strict-mcp-config"])
    if settings.openclaude_model:
        command.extend(["--model", settings.openclaude_model])

    timeout_seconds = max(int(settings.openclaude_timeout_seconds or 60), 30)
    try:
        completed = subprocess.run(
            command,
            cwd=str(workdir),
            env=_build_openclaude_env(settings),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"OpenClaude {timeout_seconds} saniyede yanit vermedi. "
            "Modeli veya saglayici kredisini kontrol edin."
        ) from exc

    if completed.returncode != 0 and not completed.stdout.strip():
        stderr = completed.stderr.strip()
        if _is_usage_limit_message(stderr):
            raise RuntimeError(
                "OpenClaude kullanim limiti doldu. Limit acilana kadar bekleyin veya baska bir model/saglayiciya gecin."
            )
        raise RuntimeError(stderr or f"OpenClaude {completed.returncode} koduyla cikti.")

    return _parse_openclaude_output(completed.stdout, completed.stderr)
