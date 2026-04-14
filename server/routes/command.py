"""POST /command dogal dil komutu alip parse edip calistiran endpoint."""
from __future__ import annotations

import time
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from dataclasses import replace
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from adapters.desktop_adapter import click_ui, focus_window, list_windows, read_screen, take_screenshot, wait_for_window, type_ui, verify_ui_state
from adapters.file_adapter import (
    copy_file_to_location,
    create_folder_in_location,
    delete_file_in_place,
    move_file_to_location,
    open_file_path,
    rename_file_in_place,
    search_files,
)
from adapters.mail_adapter import send_email_with_attachment
from adapters.openclaude_adapter import run_openclaude_prompt
from adapters.script_adapter import _mail_session_workflow, generate_and_run_script, run_script
from adapters.script_adapter import _open_application as open_application
from adapters.system_adapter import get_system_status
from adapters.system_adapter import get_system_status
from adapters.agent_browser_adapter import (
    AgentBrowserError,
    close_agent_browser_session,
    extract_pdf_links,
    get_agent_browser_session_info,
    navigate_agent_browser,
    open_agent_browser_session,
    open_document_in_agent_browser,
)
from core.auth import bearer_token_dependency
from core.logger import get_logger
from core.command_parser import ParsedCommand, parse_command
from core.config import AppSettings, add_mail_recipient_to_whitelist, load_settings
from core.errors import BrowserStateError, BrowserAuthError
from core.memory_store import delete_memory, get_memory_value, list_memory, set_memory
from core.session_state import get_session_state, record_history, rewind_last
from db import create_support_ticket, log_task


settings = load_settings()
logger = get_logger("teknikajan.command")
AGENT_REGISTRY = {
    "mail_agent": {
        "name": "mail_agent",
        "description": "Mail gonderme + mail analiz/ozetleme",
        "workflow_profile": "file_chain",
        "skills": [
            "send_file",
            "send_latest",
            "open_application",
            "wait_for_window",
            "focus_window",
            "click_ui",
            "type_ui",
            "read_screen",
            "verify_ui_state",
        ],
    },
    "file_agent": {
        "name": "file_agent",
        "description": "Dosya/klasor/arsiv zinciri",
        "workflow_profile": "file_chain",
        "skills": [
            "search_file",
            "open_file",
            "copy_file",
            "move_file",
            "rename_file",
            "delete_file",
            "create_folder",
            "send_file",
            "send_latest",
        ],
    },
    "browser_agent": {
        "name": "browser_agent",
        "description": "Agent tarayici islemleri",
        "workflow_profile": "agent_browser",
        "skills": [
            "open_agent_browser",
            "navigate_agent_browser",
            "open_document_in_agent_browser",
            "click_pdf_link",
            "list_pdf_links",
            "reuse_agent_browser_session",
            "read_agent_browser_state",
            "close_agent_browser_session",
        ],
    },
    "support_agent": {
        "name": "support_agent",
        "description": "Ariza teshis ve plan",
        "workflow_profile": "system_repair",
        "skills": [
            "system_status",
            "list_scripts",
            "run_script",
            "create_ticket",
        ],
    },
}
_INTERACTIVE_SESSION: dict[str, object] = {
    "retry_text": "",
    "retry_approved": False,
    "active_process_name": "",
    "active_title_contains": "",
    "active_file_path": "",
    "active_file_name": "",
    "browser_session_id": "",
    "browser_mode": "",
    "browser_provider": "",
    "browser_title": "",
    "browser_url": "",
    "browser_origin": "",
    "browser_document_type": "",
    "browser_file_name": "",
    "browser_authenticated": None,
    "browser_interactive_links": None,
    "browser_tab_count": None,
    "browser_active_tab_id": "",
    "browser_reusable": False,
    "browser_pending_user_finish": False,
    "pending_prompt": "",
    "pending_action": "",
    "pending_params": {},
    "pending_field": "",
    "pending_recipient_action": "",
    "pending_recipient_params": {},
    "pending_recipient_prompt": "",
    "pending_recipient_expires_at": 0.0,
    "approval_required": False,
    "approval_action": "",
    "approval_params": {},
    "approval_profile": "",
}


def _normalize_session_text(text: str) -> str:
    normalized = (text or "").lower().strip()
    for source, target in {"ş": "s", "ı": "i", "ç": "c", "ğ": "g", "ö": "o", "ü": "u"}.items():
        normalized = normalized.replace(source, target)
    return " ".join(normalized.split())


def _resolve_session_meta(request: Request | None) -> tuple[str, str | None, str | None]:
    headers = request.headers if request is not None else {}
    session_id = headers.get("x-session-id") or "default"
    operator_id = headers.get("x-operator-id")
    tenant_id = headers.get("x-tenant-id")
    return session_id, operator_id, tenant_id


def _apply_model_override(base: AppSettings, provider: str | None, model: str | None) -> AppSettings:
    effective = replace(base)
    if provider:
        effective.ai_provider = provider
    if effective.ai_provider == "openrouter" and model:
        effective.openrouter_model = model
    if effective.ai_provider == "gemini" and model:
        effective.gemini_model = model
    if effective.ai_provider == "openclaude" and model:
        effective.openclaude_model = model
    return effective


def _parse_model_list(env_value: str, fallback: str | None) -> list[str]:
    items = [item.strip() for item in (env_value or "").split(",") if item.strip()]
    if not items and fallback:
        items = [fallback]
    return items


def _parse_slash_command(text: str) -> tuple[str, list[str]]:
    parts = text.strip().split()
    cmd = parts[0].lstrip("/").lower()
    return cmd, parts[1:]


def _apply_agent_profile(parsed: ParsedCommand | None, session_state) -> None:
    if not parsed:
        return
    agent_profile = str(session_state.current_agent_profile or "").strip()
    if not agent_profile:
        return
    parsed.workflow_profile = agent_profile


def _handle_slash_command(
    *,
    command_text: str,
    session_state,
    session_id: str,
    tenant_id: str | None,
    settings_snapshot: AppSettings,
) -> CommandResponse:
    cmd, args = _parse_slash_command(command_text)
    summary = ""
    next_step = ""
    result: dict | None = None

    if cmd == "init":
        init_path = Path(__file__).resolve().parent.parent / ".teknikajan.md"
        if init_path.exists():
            summary = ".teknikajan.md zaten mevcut."
        else:
            init_path.write_text(
                "# TeknikAjan Proje Baglami\n\n"
                "- Musteri:\n"
                "- Kritik uygulamalar:\n"
                "- Guvenlik notlari:\n"
                "- Uzak baglanti proseduru:\n",
                encoding="utf-8",
            )
            summary = ".teknikajan.md olusturuldu."
        next_step = "Isterseniz dosyayi duzenleyerek kalici baglami ekleyebilirsiniz."
        result = {"path": str(init_path)}

    elif cmd == "memory":
        if not args:
            summary = "Hafiza kayitlari listelendi."
            result = {"memory": list_memory(tenant_id=tenant_id, session_id=session_id)}
            next_step = "Yeni kayit icin /memory key=value yazabilirsiniz."
        else:
            action = args[0].lower()
            payload = " ".join(args[1:]) if len(args) > 1 else " ".join(args)
            if action in {"del", "remove", "unset"}:
                key = payload.strip()
                result = {"memory": delete_memory(tenant_id=tenant_id, session_id=session_id, key=key)}
                summary = "Hafiza kaydi silindi."
            else:
                if "=" in payload:
                    key, value = payload.split("=", 1)
                    result = {"memory": set_memory(tenant_id=tenant_id, session_id=session_id, key=key.strip(), value=value.strip())}
                    summary = "Hafiza kaydi guncellendi."
                else:
                    summary = "Hafiza komutu icin key=value formatini kullanin."
            next_step = "Mevcut kayitlari gormek icin /memory yazabilirsiniz."

    elif cmd == "yardim":
        summary = "Kullanim komutlari."
        result = {
            "commands": [
                "/init",
                "/memory",
                "/model",
                "/plan",
                "/compact",
                "/usage",
                "/rewind",
                "/audit",
                "/durum",
                "/agent",
            ]
        }
        next_step = "Detay icin komutu yazabilirsiniz."

    elif cmd == "durum":
        result = get_system_status()
        summary = "Sistem durumu alindi."
        next_step = ""

    elif cmd == "agent":
        if not args or args[0].lower() in {"list", "liste"}:
            summary = "Mevcut agent profilleri."
            result = {"agents": list(AGENT_REGISTRY.values())}
            next_step = "Secmek icin /agent <isim> yazin."
        elif args[0].lower() in {"clear", "reset", "kapat"}:
            session_state.current_agent = None
            session_state.current_agent_profile = None
            delete_memory(tenant_id=tenant_id, session_id=session_id, key="agent_name")
            delete_memory(tenant_id=tenant_id, session_id=session_id, key="agent_profile")
            summary = "Agent profili temizlendi."
            next_step = "Varsayilan moda donuldu."
        else:
            agent_name = args[0].lower()
            agent = AGENT_REGISTRY.get(agent_name)
            if not agent:
                summary = "Agent bulunamadi."
                next_step = "Mevcut agentleri gormek icin /agent list yazin."
            else:
                session_state.current_agent = agent_name
                session_state.current_agent_profile = agent.get("workflow_profile")
                set_memory(tenant_id=tenant_id, session_id=session_id, key="agent_name", value=agent_name)
                set_memory(tenant_id=tenant_id, session_id=session_id, key="agent_profile", value=agent.get("workflow_profile"))
                summary = f"Agent secildi: {agent_name}"
                next_step = "Komutu yazin, agent profiline gore calisir."
                result = agent

    elif cmd == "model":
        if not args or (args and args[0].lower() in {"list", "liste"}):
            openrouter_models = _parse_model_list(os.environ.get("OPENROUTER_MODELS", ""), settings_snapshot.openrouter_model)
            gemini_models = _parse_model_list(os.environ.get("GEMINI_MODELS", ""), settings_snapshot.gemini_model)
            openclaude_models = _parse_model_list(os.environ.get("OPENCLAUDE_MODELS", ""), settings_snapshot.openclaude_model)
            summary = "Aktif model bilgisi."
            result = {
                "provider": session_state.model_provider or settings_snapshot.ai_provider,
                "model": session_state.model_name or (
                    settings_snapshot.openrouter_model
                    if (session_state.model_provider or settings_snapshot.ai_provider) == "openrouter"
                    else (
                        settings_snapshot.openclaude_model
                        if (session_state.model_provider or settings_snapshot.ai_provider) == "openclaude"
                        else settings_snapshot.gemini_model
                    )
                ),
                "available_models": {
                    "openrouter": openrouter_models,
                    "gemini": gemini_models,
                    "openclaude": openclaude_models,
                },
            }
            next_step = "Degistirmek icin /model openrouter <model>, /model gemini <model> veya /model openclaude <model> yazin."
        elif args[0].lower() == "reset":
            session_state.model_provider = None
            session_state.model_name = None
            delete_memory(tenant_id=tenant_id, session_id=session_id, key="model_provider")
            delete_memory(tenant_id=tenant_id, session_id=session_id, key="model_name")
            summary = "Model override sifirlandi."
            next_step = "Varsayilan model kullaniliyor."
        else:
            provider = args[0].lower()
            model = " ".join(args[1:]).strip() if len(args) > 1 else None
            if provider not in {"openrouter", "gemini", "openclaude"}:
                model = " ".join(args).strip()
                provider = "openrouter"
            session_state.model_provider = provider
            session_state.model_name = model
            set_memory(tenant_id=tenant_id, session_id=session_id, key="model_provider", value=provider)
            if model:
                set_memory(tenant_id=tenant_id, session_id=session_id, key="model_name", value=model)
            summary = "Model override ayarlandi."
            next_step = "Sonraki komutlar yeni modelle calisacak."
            result = {"provider": provider, "model": model}

    elif cmd == "plan":
        if args and args[0].lower() in {"off", "kapat"}:
            session_state.plan_mode = False
            summary = "Plan modu kapatildi."
            next_step = "Komutlar normal sekilde calisir."
        else:
            session_state.plan_mode = True
            summary = "Plan modu acik. Komutlar sadece planlanacak."
            next_step = "Planlamak istediginiz gorevi yazin."

    elif cmd == "compact":
        recent = session_state.history[-25:]
        compact_path = Path(__file__).resolve().parent.parent / "data" / "compact_notes.md"
        lines = ["# Oturum Ozeti\n"]
        for item in recent:
            lines.append(f"- {item.get('ts')} | {item.get('command')} | {item.get('action')} | {item.get('status')}")
        compact_path.parent.mkdir(parents=True, exist_ok=True)
        compact_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary = "Oturum ozeti olusturuldu."
        next_step = "Ozet dosyasini inceleyebilirsiniz."
        result = {"path": str(compact_path)}

    elif cmd in {"usage", "cost"}:
        active_provider = session_state.model_provider or settings_snapshot.ai_provider
        summary = "Oturum kullanim ozetini gosteriyorum."
        result = {
            "requests": int(session_state.usage.get("request_count", 0)),
            "last_duration_ms": float(session_state.usage.get("last_request_ms", 0.0)),
            "model_provider": active_provider,
            "model_name": session_state.model_name or (
                settings_snapshot.openrouter_model
                if active_provider == "openrouter"
                else (
                    settings_snapshot.openclaude_model
                    if active_provider == "openclaude"
                    else settings_snapshot.gemini_model
                )
            ),
        }
        next_step = "Isterseniz /audit ile detayli rapor alabilirsiniz."

    elif cmd == "audit":
        audit_path = Path(__file__).resolve().parent.parent / "data" / f"audit-{session_id}.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_payload = {"session_id": session_id, "tenant_id": tenant_id, "history": session_state.history}
        audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = "Audit raporu olusturuldu."
        next_step = "Dosyayi inceleyebilir veya paylasabilirsiniz."
        result = {"path": str(audit_path)}

    elif cmd == "rewind":
        removed = rewind_last(session_state)
        if removed:
            summary = "Son islem kaydi geri alindi."
            result = {"removed": removed}
        else:
            summary = "Geri alinacak bir islem kaydi yok."
        next_step = ""

    else:
        summary = "Bilinmeyen komut."
        next_step = "Kullanilabilir komutlar: /init, /memory, /model, /plan, /compact, /usage, /rewind, /agent"

    total_ms = 0.0
    return CommandResponse(
        action="slash_command",
        confidence=1.0,
        workflow_profile="system_repair",
        session_context=_build_session_context(),
        browser_context=_build_browser_context(),
        timing={"parse_ms": 0.0, "execute_ms": total_ms, "total_ms": total_ms, "resumed": False},
        summary=summary,
        next_step=next_step,
        approval=ApprovalStatus(required=False, status="not_required"),
        params={},
        result=result,
    )


def _build_plan_response(parsed: ParsedCommand, *, parse_ms: float) -> CommandResponse:
    summary = "Plan olusturuldu. Onay verirseniz uygulanacak."
    next_step = "Uygulamak icin 'uygula' veya 'devam' yazin. Yeniden plan icin 'yeniden planla' yazin."
    return CommandResponse(
        action="plan",
        confidence=parsed.confidence,
        workflow_profile=parsed.workflow_profile,
        session_context=_build_session_context(),
        browser_context=_build_browser_context(),
        timing={"parse_ms": parse_ms, "execute_ms": 0.0, "total_ms": parse_ms, "resumed": False},
        summary=summary,
        next_step=next_step,
        approval=ApprovalStatus(required=False, status="not_required"),
        params=parsed.params,
        result={"action": parsed.action, "params": parsed.params, "workflow": parsed.workflow_profile},
    )


def _clear_interactive_session() -> None:
    _INTERACTIVE_SESSION.update(
        {
            "retry_text": "",
            "retry_approved": False,
            "active_process_name": "",
            "active_title_contains": "",
            "active_file_path": "",
            "active_file_name": "",
            "browser_session_id": "",
            "browser_mode": "",
            "browser_provider": "",
            "browser_title": "",
            "browser_url": "",
            "browser_origin": "",
            "browser_document_type": "",
            "browser_file_name": "",
            "browser_authenticated": None,
            "browser_interactive_links": None,
            "browser_tab_count": None,
            "browser_active_tab_id": "",
            "browser_reusable": False,
            "browser_pending_user_finish": False,
            "pending_prompt": "",
            "pending_action": "",
            "pending_params": {},
            "pending_field": "",
            "pending_recipient_action": "",
            "pending_recipient_params": {},
            "pending_recipient_prompt": "",
            "pending_recipient_expires_at": 0.0,
            "approval_required": False,
            "approval_action": "",
            "approval_params": {},
            "approval_profile": "",
        }
    )


def _clear_retry_context() -> None:
    _INTERACTIVE_SESSION["retry_text"] = ""
    _INTERACTIVE_SESSION["retry_approved"] = False


def _clear_approval_context() -> None:
    _INTERACTIVE_SESSION["pending_action"] = ""
    _INTERACTIVE_SESSION["pending_prompt"] = ""
    _INTERACTIVE_SESSION["pending_params"] = {}
    _INTERACTIVE_SESSION["pending_field"] = ""
    _INTERACTIVE_SESSION["pending_recipient_action"] = ""
    _INTERACTIVE_SESSION["pending_recipient_params"] = {}
    _INTERACTIVE_SESSION["pending_recipient_prompt"] = ""
    _INTERACTIVE_SESSION["pending_recipient_expires_at"] = 0.0
    _INTERACTIVE_SESSION["approval_required"] = False
    _INTERACTIVE_SESSION["approval_action"] = ""
    _INTERACTIVE_SESSION["approval_params"] = {}
    _INTERACTIVE_SESSION["approval_profile"] = ""


def _clear_non_browser_context() -> None:
    _clear_retry_context()
    _clear_approval_context()
    _INTERACTIVE_SESSION["active_process_name"] = ""
    _INTERACTIVE_SESSION["active_title_contains"] = ""
    _INTERACTIVE_SESSION["active_file_path"] = ""
    _INTERACTIVE_SESSION["active_file_name"] = ""


def _clear_browser_context() -> None:
    _INTERACTIVE_SESSION["browser_session_id"] = ""
    _INTERACTIVE_SESSION["browser_mode"] = ""
    _INTERACTIVE_SESSION["browser_provider"] = ""
    _INTERACTIVE_SESSION["browser_title"] = ""
    _INTERACTIVE_SESSION["browser_url"] = ""
    _INTERACTIVE_SESSION["browser_origin"] = ""
    _INTERACTIVE_SESSION["browser_document_type"] = ""
    _INTERACTIVE_SESSION["browser_file_name"] = ""
    _INTERACTIVE_SESSION["browser_authenticated"] = None
    _INTERACTIVE_SESSION["browser_interactive_links"] = None
    _INTERACTIVE_SESSION["browser_tab_count"] = None
    _INTERACTIVE_SESSION["browser_active_tab_id"] = ""
    _INTERACTIVE_SESSION["browser_reusable"] = False
    _INTERACTIVE_SESSION["browser_pending_user_finish"] = False
    _INTERACTIVE_SESSION["approval_required"] = False
    _INTERACTIVE_SESSION["approval_action"] = ""
    _INTERACTIVE_SESSION["approval_params"] = {}
    _INTERACTIVE_SESSION["approval_profile"] = ""


def _remember_pending_approval(action: str, params: dict[str, object], profile: str | None) -> None:
    _INTERACTIVE_SESSION["approval_required"] = True
    _INTERACTIVE_SESSION["approval_action"] = action
    _INTERACTIVE_SESSION["approval_params"] = dict(params or {})
    _INTERACTIVE_SESSION["approval_profile"] = profile or ""


def _consume_pending_approval() -> ParsedCommand | None:
    if not _INTERACTIVE_SESSION.get("approval_required"):
        return None
    action = str(_INTERACTIVE_SESSION.get("approval_action", "") or "").strip()
    params = dict(_INTERACTIVE_SESSION.get("approval_params", {}) or {})
    profile = str(_INTERACTIVE_SESSION.get("approval_profile", "") or "").strip() or None
    _clear_approval_context()
    if not action:
        return None
    return ParsedCommand(action=action, params=params, confidence=0.95, workflow_profile=profile)


def _has_browser_session() -> bool:
    return bool(str(_INTERACTIVE_SESSION.get("browser_session_id", "") or "").strip())


def _preserve_browser_session_only() -> None:
    if not _has_browser_session():
        _clear_interactive_session()
        return

    active_snapshot = {
        "active_process_name": _INTERACTIVE_SESSION.get("active_process_name", ""),
        "active_title_contains": _INTERACTIVE_SESSION.get("active_title_contains", ""),
        "active_file_path": _INTERACTIVE_SESSION.get("active_file_path", ""),
        "active_file_name": _INTERACTIVE_SESSION.get("active_file_name", ""),
    }
    browser_snapshot = {
        "browser_session_id": _INTERACTIVE_SESSION.get("browser_session_id", ""),
        "browser_mode": _INTERACTIVE_SESSION.get("browser_mode", ""),
        "browser_provider": _INTERACTIVE_SESSION.get("browser_provider", ""),
        "browser_title": _INTERACTIVE_SESSION.get("browser_title", ""),
        "browser_url": _INTERACTIVE_SESSION.get("browser_url", ""),
        "browser_origin": _INTERACTIVE_SESSION.get("browser_origin", ""),
        "browser_document_type": _INTERACTIVE_SESSION.get("browser_document_type", ""),
        "browser_file_name": _INTERACTIVE_SESSION.get("browser_file_name", ""),
        "browser_authenticated": _INTERACTIVE_SESSION.get("browser_authenticated"),
        "browser_interactive_links": _INTERACTIVE_SESSION.get("browser_interactive_links"),
        "browser_tab_count": _INTERACTIVE_SESSION.get("browser_tab_count"),
        "browser_active_tab_id": _INTERACTIVE_SESSION.get("browser_active_tab_id", ""),
        "browser_reusable": bool(_INTERACTIVE_SESSION.get("browser_reusable", False)),
        "browser_pending_user_finish": True,
    }
    _clear_non_browser_context()
    _INTERACTIVE_SESSION.update(active_snapshot)
    _INTERACTIVE_SESSION.update(browser_snapshot)


def _infer_document_type(file_path: str) -> str | None:
    suffix = Path(file_path or "").suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".html", ".htm"}:
        return "html"
    return None


def _file_path_to_url(file_path: str) -> str:
    try:
        return Path(file_path).resolve().as_uri()
    except Exception:
        return ""


def _restore_browser_session_from_worker() -> None:
    if _has_browser_session():
        return
    try:
        session = get_agent_browser_session_info()
    except Exception:
        return
    url = session.url or ""
    _remember_browser_session(
        session_id=session.session_id,
        mode=session.mode,
        provider="agent_browser",
        title=session.title or "",
        url=url,
        origin=urlsplit(url).netloc if url else "",
        reusable=True,
        pending_user_finish=True,
        tab_count=session.page_count or 1,
        active_tab_id="tab-1",
    )
    if url.startswith("file://"):
        try:
            path = Path(url.replace("file:///", "")).resolve()
            if path.exists():
                _INTERACTIVE_SESSION["active_file_path"] = str(path)
                _INTERACTIVE_SESSION["active_file_name"] = path.name
        except Exception:
            pass


def _resolve_agent_browser_target(target: str | None) -> str | None:
    if not target:
        return None
    normalized = _normalize_session_text(target)
    if "gmail" in normalized:
        return settings.playwright_mail_url
    if "google" in normalized or "search" in normalized:
        return "https://www.google.com/"
    if "calendar" in normalized or "takvim" in normalized:
        return "https://calendar.google.com/"
    return None


def _looks_like_open_intent(text: str) -> bool:
    normalized = _normalize_session_text(text)
    return any(token in normalized for token in (" ac", " ac ", " acin", " acil", " acilsin", " acilsin", " acilsin"))


def _extract_urls(text: str) -> list[str]:
    return [match.rstrip(").,;") for match in re.findall(r"https?://[^\s)]+", text or "", flags=re.IGNORECASE)]


def _extract_email_address(text: str) -> str | None:
    match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text or "")
    return match.group(0) if match else None


def _extract_domains(text: str) -> list[str]:
    if not text:
        return []
    matches = re.findall(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s\)>\"]*)?\b", text, flags=re.IGNORECASE)
    return [match.rstrip(").,;") for match in matches if match]


def _extract_urls_from_file(file_path: str) -> list[str]:
    try:
        with open(file_path, "rb") as file_handle:
            data = file_handle.read()
    except OSError:
        return []
    urls: list[str] = []
    matches = re.findall(rb"https?://[^\s\)>\"]+", data)
    for match in matches:
        try:
            urls.append(match.decode("utf-8", errors="ignore"))
        except Exception:
            continue

    domain_matches = re.findall(rb"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s\)>\"]*)?", data, flags=re.IGNORECASE)
    for match in domain_matches:
        try:
            domain = match.decode("utf-8", errors="ignore")
        except Exception:
            continue
        if domain and not domain.startswith(("http://", "https://")):
            urls.append(f"https://{domain}")
        elif domain:
            urls.append(domain)

    return [url.rstrip(").,;") for url in urls if url]


def _pick_pdf_link(links: list[object], match_text: str | None) -> object | None:
    if not links:
        return None
    normalized_match = _normalize_session_text(match_text or "")
    if not normalized_match:
        return links[0]

    def _score(link: object) -> int:
        if not hasattr(link, "__dict__"):
            return 0
        payload = link.__dict__
        candidates = [
            payload.get("label"),
            payload.get("contents"),
            payload.get("title"),
            payload.get("url"),
        ]
        score = 0
        for candidate in candidates:
            if not candidate:
                continue
            normalized_candidate = _normalize_session_text(str(candidate))
            if normalized_match == normalized_candidate:
                score += 5
            if normalized_match and normalized_match in normalized_candidate:
                score += 3
        return score

    return max(links, key=_score)


def _attempt_link_discovery(file_path: str, match_text: str | None) -> tuple[str | None, dict[str, object]]:
    """Try multiple strategies to find a link. Returns (url, debug_info)."""
    debug: dict[str, object] = {"strategies": []}

    # Strategy 1: PDF annotations via pdfjs
    try:
        link_info = extract_pdf_links(file_path)
        links = link_info.get("links", []) if link_info else []
        selected = _pick_pdf_link(links, match_text)
        url = getattr(selected, "url", None) if selected else None
        debug["strategies"].append({"name": "pdf_annotations", "count": len(links), "hit": bool(url)})
        if url:
            return url, debug
    except AgentBrowserError as exc:
        debug["strategies"].append({"name": "pdf_annotations", "error": str(exc)})

    # Strategy 2: OCR screen text -> URL/domain
    try:
        screen_result = read_screen(mode="medium")
        ocr_text = str(screen_result.get("ocr_text", "") or "")
        ocr_lines = screen_result.get("ocr_lines") or []
        url_candidates = _extract_urls(ocr_text)
        if not url_candidates and isinstance(ocr_lines, list):
            for line in ocr_lines:
                url_candidates.extend(_extract_urls(str(line)))
        if not url_candidates:
            url_candidates = _extract_domains(ocr_text)
        if not url_candidates and isinstance(ocr_lines, list):
            for line in ocr_lines:
                url_candidates.extend(_extract_domains(str(line)))
        url_candidates = [
            url if url.startswith(("http://", "https://")) else f"https://{url}"
            for url in url_candidates
            if url
        ]
        debug["strategies"].append({"name": "ocr", "count": len(url_candidates), "hit": bool(url_candidates)})
        if url_candidates:
            return url_candidates[0], debug
    except Exception as exc:
        debug["strategies"].append({"name": "ocr", "error": str(exc)})

    # Strategy 3: Raw file content URL/domain scan
    file_candidates = _extract_urls_from_file(file_path)
    debug["strategies"].append({"name": "raw_scan", "count": len(file_candidates), "hit": bool(file_candidates)})
    if file_candidates:
        return file_candidates[0], debug

    return None, debug


def _remember_browser_session(
    *,
    session_id: str,
    mode: str,
    provider: str,
    title: str = "",
    url: str = "",
    origin: str = "",
    document_type: str = "",
    file_name: str = "",
    authenticated: bool | None = None,
    interactive_links: int | None = None,
    tab_count: int | None = None,
    active_tab_id: str = "",
    reusable: bool = True,
    pending_user_finish: bool = True,
) -> None:
    _INTERACTIVE_SESSION["browser_session_id"] = session_id
    _INTERACTIVE_SESSION["browser_mode"] = mode
    _INTERACTIVE_SESSION["browser_provider"] = provider
    _INTERACTIVE_SESSION["browser_title"] = title[:240]
    _INTERACTIVE_SESSION["browser_url"] = url
    _INTERACTIVE_SESSION["browser_origin"] = origin
    _INTERACTIVE_SESSION["browser_document_type"] = document_type
    _INTERACTIVE_SESSION["browser_file_name"] = file_name
    _INTERACTIVE_SESSION["browser_authenticated"] = authenticated
    _INTERACTIVE_SESSION["browser_interactive_links"] = interactive_links
    _INTERACTIVE_SESSION["browser_tab_count"] = tab_count
    _INTERACTIVE_SESSION["browser_active_tab_id"] = active_tab_id
    _INTERACTIVE_SESSION["browser_reusable"] = reusable
    _INTERACTIVE_SESSION["browser_pending_user_finish"] = pending_user_finish


def _is_resume_command(text: str) -> bool:
    normalized = _normalize_session_text(text)
    return normalized in {
        "tekrar dene",
        "yeniden dene",
        "devam et",
        "oturum acik devam et",
        "oturum acik, devam et",
        "devam",
        "ayni sekmede devam et",
        "ayni sayfada devam et",
        "pdfde devam et",
    }


def _is_finish_command(text: str) -> bool:
    normalized = _normalize_session_text(text)
    return normalized in {"tamam", "bitti", "tamam bitti", "islem bitti", "kapat"}


def _is_browser_close_command(text: str) -> bool:
    normalized = _normalize_session_text(text)
    return normalized in {
        "oturumu kapat",
        "tarayiciyi kapat",
        "browseri kapat",
        "tarayici oturumunu kapat",
    }


def _remember_retry(command_text: str, approved: bool) -> None:
    _INTERACTIVE_SESSION["retry_text"] = command_text
    _INTERACTIVE_SESSION["retry_approved"] = approved


def _apply_active_context(parsed) -> None:
    if parsed is None:
        return
    active_process_name = str(_INTERACTIVE_SESSION.get("active_process_name", "") or "").strip()
    active_title = str(_INTERACTIVE_SESSION.get("active_title_contains", "") or "").strip()
    if parsed.action in {"click_ui", "type_ui", "focus_window", "wait_for_window"}:
        if active_process_name and not parsed.params.get("process_name"):
            parsed.params["process_name"] = active_process_name
        if active_title and not parsed.params.get("title_contains") and parsed.action in {"click_ui", "focus_window", "wait_for_window", "type_ui"}:
            parsed.params["title_contains"] = active_title


def _remember_active_context(action: str, result: dict | None, parsed) -> None:
    if not isinstance(result, dict):
        return

    process_name = ""
    title_contains = ""

    if action == "open_application":
        process_name = str(parsed.params.get("app_name", "") or "").strip()
        target = str(parsed.params.get("target", "") or "").strip()
        if target:
            title_contains = target.replace("https://", "").replace("http://", "").split("/")[0]
    elif action == "open_file":
        _INTERACTIVE_SESSION["active_process_name"] = ""
        opened_file = result.get("opened_file") if isinstance(result, dict) else None
        if isinstance(opened_file, dict):
            file_path = str(opened_file.get("path", "") or "")
            file_name = str(opened_file.get("name", "") or "")
        else:
            file_path = str(result.get("path", "") or "")
            file_name = str(result.get("name", "") or "")
        title_contains = str(result.get("title_hint", "") or file_name).strip()
        if file_path:
            _INTERACTIVE_SESSION["active_file_path"] = file_path
        if file_name:
            _INTERACTIVE_SESSION["active_file_name"] = file_name
        if not str(_INTERACTIVE_SESSION.get("browser_provider", "") or "").strip():
            document_type = _infer_document_type(file_path)
            if document_type:
                _remember_browser_session(
                    session_id="browser-main",
                    mode="document",
                    provider="system_document_viewer",
                    title=title_contains or file_name,
                    url=_file_path_to_url(file_path),
                    document_type=document_type,
                    file_name=file_name,
                    reusable=True,
                    pending_user_finish=True,
                )
    elif action in {"wait_for_window", "focus_window", "click_ui", "type_ui"}:
        process_name = str(result.get("process_name", parsed.params.get("process_name", "")) or "").strip()
        title_contains = str(result.get("title", parsed.params.get("title_contains", "")) or "").strip()
    elif action == "read_screen":
        active_window = result.get("active_window_guess")
        if isinstance(active_window, dict):
            process_name = str(active_window.get("process_name", "") or "").strip()
            title_contains = str(active_window.get("title", "") or "").strip()

    if process_name:
        _INTERACTIVE_SESSION["active_process_name"] = process_name
    if title_contains:
        _INTERACTIVE_SESSION["active_title_contains"] = title_contains[:120]

    if action == "open_application":
        app_name = str(parsed.params.get("app_name", "") or "").strip().lower()
        target = str(parsed.params.get("target", "") or "").strip()
        if target.startswith(("http://", "https://")):
            split = urlsplit(target)
            _remember_browser_session(
                session_id="browser-main",
                mode="web",
                provider="system_browser",
                title=title_contains or split.netloc,
                url=target,
                origin=split.netloc,
                file_name="",
                reusable=True,
                pending_user_finish=True,
                tab_count=1,
                active_tab_id="tab-1",
            )
            if app_name:
                _INTERACTIVE_SESSION["active_process_name"] = app_name
    elif action in {"wait_for_window", "focus_window", "click_ui", "type_ui", "read_screen"} and _has_browser_session():
        if title_contains:
            _INTERACTIVE_SESSION["browser_title"] = title_contains[:240]
        if process_name and not str(_INTERACTIVE_SESSION.get("browser_provider", "") or "").strip():
            _INTERACTIVE_SESSION["browser_provider"] = process_name
    elif action == "send_file" and _has_browser_session():
        _INTERACTIVE_SESSION["browser_authenticated"] = True


def _build_session_context() -> dict[str, str] | None:
    process_name = str(_INTERACTIVE_SESSION.get("active_process_name", "") or "").strip()
    title_contains = str(_INTERACTIVE_SESSION.get("active_title_contains", "") or "").strip()
    file_name = str(_INTERACTIVE_SESSION.get("active_file_name", "") or "").strip()
    if not process_name and not title_contains and not file_name:
        return None
    session_context: dict[str, str] = {}
    if process_name:
        session_context["process_name"] = process_name
    if title_contains:
        session_context["title"] = title_contains
    if file_name:
        session_context["file_name"] = file_name
    return session_context


class BrowserContext(BaseModel):
    session_id: str
    mode: str
    provider: str
    title: str | None = None
    url: str | None = None
    origin: str | None = None
    authenticated: bool | None = None
    document_type: str | None = None
    file_name: str | None = None
    interactive_links: int | None = None
    tab_count: int | None = None
    active_tab_id: str | None = None
    reusable: bool = True
    pending_user_finish: bool = False


def _build_browser_context() -> BrowserContext | None:
    session_id = str(_INTERACTIVE_SESSION.get("browser_session_id", "") or "").strip()
    if not session_id:
        return None
    mode = str(_INTERACTIVE_SESSION.get("browser_mode", "") or "").strip() or "web"
    provider = str(_INTERACTIVE_SESSION.get("browser_provider", "") or "").strip() or "agent_browser"
    title = str(_INTERACTIVE_SESSION.get("browser_title", "") or "").strip() or None
    url = str(_INTERACTIVE_SESSION.get("browser_url", "") or "").strip() or None
    origin = str(_INTERACTIVE_SESSION.get("browser_origin", "") or "").strip() or None
    document_type = str(_INTERACTIVE_SESSION.get("browser_document_type", "") or "").strip() or None
    file_name = str(_INTERACTIVE_SESSION.get("browser_file_name", "") or "").strip() or None
    active_tab_id = str(_INTERACTIVE_SESSION.get("browser_active_tab_id", "") or "").strip() or None
    interactive_links = _INTERACTIVE_SESSION.get("browser_interactive_links")
    tab_count = _INTERACTIVE_SESSION.get("browser_tab_count")
    return BrowserContext(
        session_id=session_id,
        mode=mode,
        provider=provider,
        title=title,
        url=url,
        origin=origin,
        authenticated=_INTERACTIVE_SESSION.get("browser_authenticated"),
        document_type=document_type,
        file_name=file_name,
        interactive_links=interactive_links if isinstance(interactive_links, int) else None,
        tab_count=tab_count if isinstance(tab_count, int) else None,
        active_tab_id=active_tab_id,
        reusable=bool(_INTERACTIVE_SESSION.get("browser_reusable", True)),
        pending_user_finish=bool(_INTERACTIVE_SESSION.get("browser_pending_user_finish", False)),
    )


router = APIRouter(
    tags=["command"],
    dependencies=[Depends(bearer_token_dependency(settings.bearer_token))],
)
ui_router = APIRouter(
    tags=["command-ui"],
    dependencies=[Depends(bearer_token_dependency(settings.bearer_token))],
)


class CommandRequest(BaseModel):
    text: str
    approved: bool = False


class ApprovalStatus(BaseModel):
    required: bool
    status: str


class CommandResponse(BaseModel):
    action: str
    confidence: float
    workflow_profile: str | None = None
    session_context: dict[str, str] | None = None
    browser_context: BrowserContext | None = None
    timing: dict[str, float | bool] | None = None
    summary: str
    next_step: str
    approval: ApprovalStatus
    params: dict
    result: dict | None = None
    knowledge_hint: str | None = None
    error: str | None = None
    handoff_recommended: bool = False


def _humanize_error(message: str) -> str:
    normalized = (message or "").lower()
    if "usage limit" in normalized or "upgrade to pro" in normalized or "kullanim limiti" in normalized:
        return "OpenClaude kullanim limiti doldu. Limit acilana kadar bekleyin veya /model ile baska bir saglayici/model secin."
    if "openclaude cli bulunamadi" in normalized:
        return "OpenClaude CLI bulunamadi. `npm install -g @gitlawb/openclaude` kurun veya OPENCLAUDE_COMMAND ayarlayin."
    if "openclaude" in normalized:
        return message or "OpenClaude istegi tamamlanamadi."
    if "agent browser" in normalized:
        return "Agent tarayici isleminde hata olustu. Tarayiciyi yeniden acmayi deneyin."
    if "gemini_ssl_timeout" in normalized:
        return "Yapay zeka servisine baglanirken SSL zaman asimi olustu. Ag baglantinizi kontrol edip tekrar deneyin."
    if "gemini_unavailable" in normalized:
        return "Yapay zeka servisi gecici olarak yogun. Sistem kisa sure sonra tekrar denenebilir."
    if "gemini_timeout" in normalized:
        return "Yapay zeka servisi zaman asimina ugradi. Birkac saniye sonra tekrar deneyin."
    if "gemini_error" in normalized:
        return "Yapay zeka servisi bu istegi su anda tamamlayamadi. Birkac saniye sonra tekrar deneyin."
    if "gmail_login_required" in normalized:
        return "Mail gondermek icin once otomasyonun actigi tarayici profilinde Gmail oturumu acmaniz gerekiyor. Acilan pencerede giris yapip tekrar deneyin."
    if "gmail_compose_not_ready" in normalized:
        return "Gmail yazma ekrani hazir degil. Gmail sekmesinde oturumun acik oldugunu ve sayfanin yuklendiginini kontrol edin."
    if "gmail_send_not_confirmed" in normalized:
        return "Mail gonderimi dogrulanamadi. Gmail penceresini kontrol edip tekrar deneyin."
    if "gemini api anahtari ayarlanmamis" in normalized:
        return "Yapay zeka entegrasyonu hazir degil. Gemini anahtarini ayarlamaniz gerekiyor."
    if "recipient not in whitelist" in normalized:
        return "Bu alici adresine gonderim izni yok. Izinli alici listesini kontrol edin."
    if "at least one recipient is required" in normalized or "alici e-posta adresi gerekli" in normalized:
        return "Gonderim icin alici e-posta adresi eksik."
    if "attachment not found" in normalized or "gonderilecek dosya bulunamadi" in normalized:
        return "Gonderilecek dosya bulunamadi. Dosya adini veya konumunu daha net yazin."
    if "eslesen dosya bulunamadi" in normalized:
        return "Istenen dosya bulunamadi. Dosya adini veya uzantisini daha net yazin."
    if "kopyalanacak dosya bulunamadi" in normalized:
        return "Kopyalanacak dosya bulunamadi. Kaynak dosya adini daha net yazin."
    if "desteklenmeyen uygulama" in normalized:
        return "Bu uygulama su an dogrudan acilamiyor. Daha bilinen bir uygulama adi yazin."
    if "uygulama acilamadi" in normalized:
        return "Uygulama acilamadi. Uygulamanin kurulu oldugunu ve adini dogru yazdigini kontrol edin."
    if "ekran resmi alinamadi" in normalized:
        return "Ekran resmi alinamadi. Masaustu oturumu acik olmayabilir."
    if "script whitelist disinda" in normalized:
        return "Bu scripti calistirma izni yok."
    if "script manifest icinde bulunamadi" in normalized or "script adi gerekli" in normalized:
        return "Istenen script bulunamadi veya script adi anlasilmadi."
    if "browser mail send failed" in normalized or "did not return a result" in normalized or "compose butonu bulunamadi" in normalized:
        return "Mail gonderilemedi. Tarayici oturumu veya mail hesabi hazir olmayabilir."
    if "generated script blocked by safety rule" in normalized:
        return "Istek guvenlik kurallarina takildi. Daha guvenli ve dar bir komut deneyin."
    if "generated script failed" in normalized:
        return "Uretilen otomasyon calismadi. Istegi daha acik ve daha dar kapsamli yazin."
    if "generated script timed out" in normalized:
        return "Uretilen otomasyon zaman asimina ugradi. Uygulama asili kalmis olabilir; daha dar bir komut deneyin."
    if "desteklenmeyen tool" in normalized:
        return "Bu istek su an desteklenmeyen bir arac gerektiriyor."
    return message or "Islem tamamlanamadi."


def _search_with_fallback(*, query: str, location: str, extension: str | None) -> tuple[list[dict], str]:
    preferred = (location or "desktop").strip() or "desktop"
    ordered_locations: list[str] = [preferred]
    for candidate in ("desktop", "documents", "downloads"):
        if candidate != preferred:
            ordered_locations.append(candidate)

    for candidate_location in ordered_locations:
        items = search_files(
            query=query,
            location=candidate_location,
            extension=extension,
            allowed_folders=settings.allowed_folders,
        )
        if items:
            return items, candidate_location
    return [], preferred


@router.post("/command")
def execute_command(request: CommandRequest, http_request: Request = None) -> CommandResponse:
    """Dogal dil komutunu parse et ve ilgili aksiyonu calistir."""
    request_started_at = time.perf_counter()
    global settings
    settings = load_settings()
    try:
        key_len = len(settings.openrouter_api_key or "")
        provider = settings.ai_provider
        logger.debug("AI config loaded: provider=%s openrouter_key_len=%s", provider, key_len)
    except Exception:
        pass
    parsed = None
    result = None
    error = None
    summary = ""
    next_step = ""
    approval_required = False
    approval_status = "not_required"
    handoff_recommended = False
    parse_ms = 0.0
    original_text = request.text
    command_text = request.text
    command_approved = request.approved
    session_id, operator_id, tenant_id = _resolve_session_meta(http_request)
    session_state = get_session_state(session_id, operator_id=operator_id, tenant_id=tenant_id)
    if session_state.model_provider is None:
        session_state.model_provider = get_memory_value(tenant_id=tenant_id, session_id=session_id, key="model_provider")
    if session_state.model_name is None:
        session_state.model_name = get_memory_value(tenant_id=tenant_id, session_id=session_id, key="model_name")
    if session_state.current_agent is None:
        session_state.current_agent = get_memory_value(tenant_id=tenant_id, session_id=session_id, key="agent_name")
    if session_state.current_agent_profile is None:
        session_state.current_agent_profile = get_memory_value(tenant_id=tenant_id, session_id=session_id, key="agent_profile")
    if session_state.current_agent and not session_state.current_agent_profile:
        agent = AGENT_REGISTRY.get(str(session_state.current_agent))
        if agent:
            session_state.current_agent_profile = agent.get("workflow_profile")
    _restore_browser_session_from_worker()

    normalized_cmd = _normalize_session_text(command_text)
    if normalized_cmd in {"plan modundan cik", "plan modu kapat", "plan kapat", "plan off"}:
        command_text = "/plan off"
    elif normalized_cmd in {"plan modu ac", "plan modu acik", "plan ac", "plan"}:
        command_text = "/plan"
    elif normalized_cmd in {"model", "models", "model listesi", "model list"}:
        command_text = "/model"
    elif normalized_cmd in {"yardim", "help", "komutlar", "komut listesi"}:
        command_text = "/yardim"
    elif normalized_cmd in {"durum", "status", "sistem durumu"}:
        command_text = "/durum"
    elif normalized_cmd in {"memory", "hafiza", "hafıza"}:
        command_text = "/memory"
    elif normalized_cmd in {"init", "baslat", "baglam", "proje baglami"}:
        command_text = "/init"
    elif normalized_cmd in {"audit", "rapor", "oturum raporu"}:
        command_text = "/audit"
    elif normalized_cmd in {"usage", "kullanim", "kullanım"}:
        command_text = "/usage"
    elif normalized_cmd in {"compact", "ozet", "özet"}:
        command_text = "/compact"
    elif normalized_cmd in {"rewind", "geri al"}:
        command_text = "/rewind"
    elif normalized_cmd in {"agent", "ajan", "agent list"}:
        command_text = "/agent"

    if command_text.strip().startswith("/"):
        return _handle_slash_command(
            command_text=command_text,
            session_state=session_state,
            session_id=session_id,
            tenant_id=tenant_id,
            settings_snapshot=settings,
        )

    pending_action = str(_INTERACTIVE_SESSION.get("pending_action", "") or "").strip()
    if pending_action:
        pending_field = str(_INTERACTIVE_SESSION.get("pending_field", "") or "").strip()
        pending_params = dict(_INTERACTIVE_SESSION.get("pending_params", {}) or {})
        resolved_value: str | None = None

        if pending_field == "recipient":
            resolved_value = _extract_email_address(command_text)
        elif pending_field == "new_name":
            resolved_value = command_text.strip()
        elif pending_field == "app_name":
            resolved_value = command_text.strip()
        elif pending_field == "destination_location":
            normalized = _normalize_session_text(command_text)
            for location in ("desktop", "documents", "downloads"):
                if location in normalized:
                    resolved_value = location
                    break

        if resolved_value:
            pending_params[pending_field] = resolved_value
            _INTERACTIVE_SESSION["pending_action"] = ""
            _INTERACTIVE_SESSION["pending_prompt"] = ""
            _INTERACTIVE_SESSION["pending_params"] = {}
            _INTERACTIVE_SESSION["pending_field"] = ""
            parsed = ParsedCommand(
                action=pending_action,
                params=pending_params,
                confidence=0.95,
                workflow_profile="file_chain",
            )
            _apply_agent_profile(parsed, session_state)
            command_approved = True
        else:
            summary = str(_INTERACTIVE_SESSION.get("pending_prompt", "") or "Lutfen devam edin.")
            next_step = "Bilgiyi daha net yazin."
            return CommandResponse(
                action="unknown",
                confidence=0.0,
                workflow_profile="file_chain",
                session_context=_build_session_context(),
                browser_context=_build_browser_context(),
                timing={"parse_ms": 0.0, "execute_ms": 0.0, "total_ms": 0.0, "resumed": False},
                summary=summary,
                next_step=next_step,
                approval=ApprovalStatus(required=False, status="not_required"),
                params={},
                result={"status": "awaiting_input", "field": pending_field},
            )

    # Backup resume for recipient input if pending state was lost.
    email_value = _extract_email_address(command_text)
    pending_recipient_action = str(_INTERACTIVE_SESSION.get("pending_recipient_action", "") or "").strip()
    pending_recipient_params = dict(_INTERACTIVE_SESSION.get("pending_recipient_params", {}) or {})
    pending_recipient_expires_at = float(_INTERACTIVE_SESSION.get("pending_recipient_expires_at", 0.0) or 0.0)
    pending_prompt_text = str(_INTERACTIVE_SESSION.get("pending_prompt", "") or "").lower()
    remainder_text = ""
    if email_value:
        remainder_text = (command_text or "").replace(email_value, " ").strip().lower()
    remainder_is_trivial = remainder_text in {"", "eposta", "e-posta", "email", "mail", "alici", "gonder"}
    should_resume_recipient = bool(email_value) and remainder_is_trivial and (
        (pending_recipient_action and time.time() <= pending_recipient_expires_at)
        or ("alici e-posta adresi gerekli" in pending_prompt_text)
    )
    if should_resume_recipient:
        if not pending_recipient_action:
            pending_recipient_action = "send_file"
        pending_recipient_params["recipient"] = email_value
        _INTERACTIVE_SESSION["pending_recipient_action"] = ""
        _INTERACTIVE_SESSION["pending_recipient_params"] = {}
        _INTERACTIVE_SESSION["pending_recipient_prompt"] = ""
        _INTERACTIVE_SESSION["pending_recipient_expires_at"] = 0.0
        parsed = ParsedCommand(
            action=pending_recipient_action,
            params=pending_recipient_params,
            confidence=0.95,
            workflow_profile="file_chain",
        )
        _apply_agent_profile(parsed, session_state)
        command_approved = True

    if request.approved:
        approved_parsed = _consume_pending_approval()
        if approved_parsed:
            parsed = approved_parsed
            command_approved = True

    plan_accept = {"uygula", "devam", "onayla", "evet", "olur", "tamam"}
    plan_reject = {"hayir", "degil", "beğenmedim", "begenmedim", "yeniden planla", "yeniden plan", "planı değiştir", "plani degistir"}
    if session_state.plan_mode:
        if normalized_cmd in plan_accept and session_state.last_plan:
            parsed = ParsedCommand(
                action=session_state.last_plan.get("action", "unknown"),
                params=session_state.last_plan.get("params", {}),
                confidence=float(session_state.last_plan.get("confidence", 0.8)),
                workflow_profile=session_state.last_plan.get("workflow_profile"),
            )
            parse_ms = 0.0
            session_state.plan_mode = False
            _apply_agent_profile(parsed, session_state)
        elif normalized_cmd in plan_reject and session_state.last_plan_text:
            active_settings = _apply_model_override(settings, session_state.model_provider, session_state.model_name)
            parse_started_at = time.perf_counter()
            parsed = parse_command(session_state.last_plan_text, active_settings)
            parse_ms = round((time.perf_counter() - parse_started_at) * 1000, 1)
            _apply_agent_profile(parsed, session_state)
            session_state.last_plan = {
                "action": parsed.action,
                "params": parsed.params,
                "workflow_profile": parsed.workflow_profile,
                "confidence": parsed.confidence,
            }
            return _build_plan_response(parsed, parse_ms=parse_ms)
    _restore_browser_session_from_worker()

    if _is_browser_close_command(request.text):
        _clear_interactive_session()
        total_ms = round((time.perf_counter() - request_started_at) * 1000, 1)
        return CommandResponse(
            action="unknown",
            confidence=1.0,
            workflow_profile="agent_browser",
            browser_context=None,
            timing={"parse_ms": 0.0, "execute_ms": total_ms, "total_ms": total_ms, "resumed": False},
            summary="Tarayici oturumu kapatildi.",
            next_step="Yeni bir komut verebilirsiniz.",
            approval=ApprovalStatus(required=False, status="not_required"),
            params={},
            result={"status": "browser_closed"},
        )

    if _is_finish_command(request.text):
        browser_context = _build_browser_context()
        if browser_context is not None and browser_context.reusable:
            _preserve_browser_session_only()
            browser_context = _build_browser_context()
            summary = "Aktif is akisi kapatildi. Tarayici oturumu acik tutuldu."
            next_step = "Ayni tarayici oturumunda yeni bir komut verebilirsiniz. Tarayiciyi tamamen kapatmak icin 'oturumu kapat' yazin."
            result = {"status": "closed", "browser_session_retained": True}
        else:
            _clear_interactive_session()
            browser_context = None
            summary = "Aktif is akisi kapatildi."
            next_step = "Yeni bir komut verebilirsiniz."
            result = {"status": "closed"}
        total_ms = round((time.perf_counter() - request_started_at) * 1000, 1)
        return CommandResponse(
            action="unknown",
            confidence=1.0,
            workflow_profile="agent_browser" if browser_context is not None else "generic",
            browser_context=browser_context,
            timing={"parse_ms": 0.0, "execute_ms": total_ms, "total_ms": total_ms, "resumed": False},
            summary=summary,
            next_step=next_step,
            approval=ApprovalStatus(required=False, status="not_required"),
            params={},
            result=result,
        )

    if _is_resume_command(request.text):
        retry_text = str(_INTERACTIVE_SESSION.get("retry_text", "") or "").strip()
        if retry_text:
            command_text = retry_text
            command_approved = bool(_INTERACTIVE_SESSION.get("retry_approved", False)) or request.approved
        elif _has_browser_session():
            total_ms = round((time.perf_counter() - request_started_at) * 1000, 1)
            return CommandResponse(
                action="unknown",
                confidence=1.0,
                workflow_profile="agent_browser",
                session_context=_build_session_context(),
                browser_context=_build_browser_context(),
                timing={"parse_ms": 0.0, "execute_ms": total_ms, "total_ms": total_ms, "resumed": True},
                summary="Tarayici oturumu acik ve yeniden kullanima hazir.",
                next_step="Ayni sekmede veya belgede devam etmek icin sonraki komutu yazin.",
                approval=ApprovalStatus(required=False, status="not_required"),
                params={},
                result={"status": "browser_session_ready"},
            )

    try:
        active_settings = _apply_model_override(settings, session_state.model_provider, session_state.model_name)
        if active_settings.ai_provider == "openclaude" and parsed is None:
            parse_started_at = time.perf_counter()
            browser_candidate = parse_command(command_text, AppSettings(ai_provider="gemini"))
            parse_ms = round((time.perf_counter() - parse_started_at) * 1000, 1)
            if browser_candidate.action in {
                "open_agent_browser",
                "navigate_agent_browser",
                "open_document_in_agent_browser",
                "click_pdf_link",
                "list_pdf_links",
                "reuse_agent_browser_session",
                "read_agent_browser_state",
                "close_agent_browser_session",
            }:
                parsed = browser_candidate
                _apply_agent_profile(parsed, session_state)
                _apply_active_context(parsed)

        if active_settings.ai_provider == "openclaude" and parsed is None:
            parsed = ParsedCommand(
                action="openclaude_chat",
                confidence=1.0,
                params={},
                workflow_profile="generic",
            )
            openclaude_response = run_openclaude_prompt(
                command_text,
                settings=active_settings,
                working_directory=Path(__file__).resolve().parents[2],
            )
            tool_calls = getattr(openclaude_response, "tool_calls", []) or []
            tool_names = [tc.get("tool", "") for tc in tool_calls if isinstance(tc, dict)]
            if tool_names:
                tools_used = ", ".join(t.replace("mcp__teknikajan__", "") for t in tool_names)
                summary = f"OpenClaude {len(tool_calls)} tool kullandi ({tools_used}). Islem tamamlandi."
            else:
                summary = "OpenClaude yaniti hazir."
            next_step = "Takip komutu vermek icin yeni bir mesaj yazabilirsiniz."
            result = {
                "provider": "openclaude",
                "mode": "mcp_agent",
                "answer": openclaude_response.result,
                "session_id": openclaude_response.session_id,
                "num_turns": openclaude_response.num_turns,
                "tool_calls": tool_calls,
                "tool_count": len(tool_calls),
                "duration_ms": round(openclaude_response.duration_ms, 1),
                "duration_api_ms": round(openclaude_response.duration_api_ms, 1),
                "total_cost_usd": round(openclaude_response.total_cost_usd, 6),
                "usage": openclaude_response.usage,
                "model_usage": openclaude_response.model_usage,
            }
            total_elapsed = round((time.perf_counter() - request_started_at) * 1000, 1)
            response = CommandResponse(
                action=parsed.action,
                confidence=parsed.confidence,
                workflow_profile=parsed.workflow_profile,
                session_context=_build_session_context(),
                browser_context=_build_browser_context(),
                timing={"parse_ms": 0.0, "execute_ms": total_elapsed, "total_ms": total_elapsed, "resumed": command_text != original_text},
                summary=summary,
                next_step=next_step,
                approval=ApprovalStatus(required=False, status="not_required"),
                params=parsed.params,
                result=result,
            )
            log_task(
                settings.sqlite_path,
                task_type="command",
                status="success",
                input_text=original_text,
                output_text=openclaude_response.result,
                metadata={
                    "action": parsed.action,
                    "confidence": parsed.confidence,
                    "params": parsed.params,
                    "summary": summary,
                    "next_step": next_step,
                    "approval_status": "not_required",
                    "effective_text": command_text,
                    "tool_calls": tool_calls,
                    "timing_ms": {"parse": 0.0, "execute": total_elapsed},
                },
            )
            record_history(
                session_state,
                command_text=command_text,
                action=parsed.action,
                status="success",
                summary=summary,
                elapsed_ms=total_elapsed,
            )
            return response

        if parsed is None:
            parse_started_at = time.perf_counter()
            parsed = parse_command(command_text, active_settings)
            parse_ms = round((time.perf_counter() - parse_started_at) * 1000, 1)
            _apply_agent_profile(parsed, session_state)
            _apply_active_context(parsed)
        else:
            _apply_active_context(parsed)

        if session_state.plan_mode:
            session_state.last_plan = {
                "action": parsed.action,
                "params": parsed.params,
                "workflow_profile": parsed.workflow_profile,
                "confidence": parsed.confidence,
            }
            session_state.last_plan_text = command_text
            return _build_plan_response(parsed, parse_ms=parse_ms)

        if parsed.action == "open_agent_browser":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            target_url = str(parsed.params.get("target_url", "") or "").strip() or None
            if approval_status == "pending":
                summary = "Agent tarayici oturumu acilacak. Onay gerekiyor."
                next_step = "Tarayici oturumunu baslatmak icin islemi onaylayin."
                result = {"status": "pending_approval", "target_url": target_url}
            else:
                session = open_agent_browser_session(target_url=target_url)
                split = urlsplit(session.url or "") if session.url else None
                _remember_browser_session(
                    session_id=session.session_id,
                    mode=session.mode,
                    provider="agent_browser",
                    title=session.title or "",
                    url=session.url or "",
                    origin=split.netloc if split else "",
                    reusable=True,
                    pending_user_finish=True,
                    tab_count=session.page_count or 1,
                    active_tab_id="tab-1",
                )
                summary = "Agent tarayici oturumu acildi."
                next_step = "Tarayicida acmak istediginiz siteyi veya belgeyi yazabilirsiniz."
                result = {
                    "session_id": session.session_id,
                    "mode": session.mode,
                    "url": session.url,
                    "title": session.title,
                    "reused": session.reused,
                }

        elif parsed.action == "navigate_agent_browser":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            raw_url = str(parsed.params.get("url", "") or "").strip()
            target = str(parsed.params.get("target", "") or "").strip()
            resolved_url = raw_url or _resolve_agent_browser_target(target)
            if approval_status == "pending":
                summary = "Agent tarayicida hedef sayfaya gidilecek. Onay gerekiyor."
                next_step = "Tarayiciyi acip hedefe gitmek icin islemi onaylayin."
                result = {"status": "pending_approval", "url": resolved_url, "target": target}
            else:
                if not resolved_url:
                    summary = "Gidilecek URL belirlenemedi."
                    next_step = "Tam URL veya hedef siteyi (gmail, calendar) daha net yazin."
                    result = {"message": "URL bulunamadi."}
                else:
                    if not _has_browser_session():
                        open_agent_browser_session()
                    session = navigate_agent_browser(resolved_url)
                    split = urlsplit(resolved_url)
                    _remember_browser_session(
                        session_id=session.session_id,
                        mode="web",
                        provider="agent_browser",
                        title=session.title or split.netloc,
                        url=resolved_url,
                        origin=split.netloc,
                        reusable=True,
                        pending_user_finish=True,
                        tab_count=session.page_count or 1,
                        active_tab_id="tab-1",
                    )
                    summary = "Agent tarayici hedef sayfaya gitti."
                    next_step = "Sayfada yapilacak islemi yazabilirsiniz."
                    result = {
                        "session_id": session.session_id,
                        "url": resolved_url,
                        "title": session.title,
                        "reused": session.reused,
                    }

        elif parsed.action == "open_document_in_agent_browser":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "Eslesen belge agent tarayicida acilacak. Onay gerekiyor."
                next_step = "Belgeyi agent tarayicida acmak icin islemi onaylayin."
                result = {"status": "pending_approval", **({"candidate": items[0]} if items else {})}
            elif items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                session = open_document_in_agent_browser(selected["path"])
                link_info = None
                if _infer_document_type(selected["path"]) == "pdf":
                    try:
                        link_info = extract_pdf_links(selected["path"])
                    except AgentBrowserError:
                        link_info = None
                _INTERACTIVE_SESSION["active_file_path"] = selected["path"]
                _INTERACTIVE_SESSION["active_file_name"] = selected.get("name", "")
                _remember_browser_session(
                    session_id=session.session_id,
                    mode="document",
                    provider="agent_browser",
                    title=session.title or selected.get("name", ""),
                    url=_file_path_to_url(selected["path"]),
                    document_type=_infer_document_type(selected["path"]) or "",
                    file_name=selected.get("name", ""),
                    interactive_links=link_info.get("link_count") if isinstance(link_info, dict) else None,
                    reusable=True,
                    pending_user_finish=True,
                )
                summary = f"'{selected['name']}' belgesi agent tarayicida acildi."
                next_step = "PDF icindeki linklere tiklamak icin 'linke tikla' diyebilirsiniz."
                result = {
                    "opened_file": selected,
                    "session_id": session.session_id,
                    "link_count": link_info.get("link_count") if isinstance(link_info, dict) else None,
                    "resolved_location": resolved_location,
                }
            else:
                summary = "Acilacak belge bulunamadi."
                next_step = "Dosya adini veya uzantisini daha net yazip tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "click_pdf_link":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "PDF icindeki linke tiklanacak. Onay gerekiyor."
                next_step = "Linke tiklamak icin islemi onaylayin."
                result = {"status": "pending_approval", **parsed.params}
            else:
                active_path = str(_INTERACTIVE_SESSION.get("active_file_path", "") or "").strip()
                if not active_path:
                    summary = "Aktif bir PDF bulunamadi."
                    next_step = "Once PDF dosyasini agent tarayicida acin."
                    result = {"message": "PDF oturumu yok."}
                else:
                    link_url = None
                    debug_info: dict[str, object] = {}
                    for attempt in range(1, 4):
                        link_url, debug_info = _attempt_link_discovery(
                            active_path, str(parsed.params.get("match", "") or "")
                        )
                        if link_url:
                            break
                    if not link_url:
                        summary = "PDF icinde uygun link bulunamadi."
                        next_step = "Daha net bir link hedefi belirtin."
                        result = {"message": "Link bulunamadi.", "debug": debug_info}
                    else:
                        session = navigate_agent_browser(link_url)
                        split = urlsplit(link_url)
                        _remember_browser_session(
                            session_id=session.session_id,
                            mode="web",
                            provider="agent_browser",
                            title=session.title or split.netloc,
                            url=link_url,
                            origin=split.netloc,
                            reusable=True,
                            pending_user_finish=True,
                            tab_count=session.page_count or 1,
                            active_tab_id="tab-1",
                        )
                        summary = "PDF icindeki link acildi."
                        next_step = "Sayfada yapmak istediginiz islemi yazabilirsiniz."
                        result = {"url": link_url, "debug": debug_info}

        elif parsed.action == "list_pdf_links":
            active_path = str(_INTERACTIVE_SESSION.get("active_file_path", "") or "").strip()
            if not active_path:
                summary = "Aktif bir PDF bulunamadi."
                next_step = "Once PDF dosyasini agent tarayicida acin."
                result = {"message": "PDF oturumu yok."}
            else:
                try:
                    link_info = extract_pdf_links(active_path)
                except AgentBrowserError:
                    summary = "PDF linkleri okunamadi."
                    next_step = "PDF acik oldugundan emin olun ve tekrar deneyin."
                    result = {"message": "PDF linkleri okunamadi."}
                    link_info = None
                raw_links = link_info.get("links", []) if link_info else []
                simplified = [
                    {
                        "index": getattr(link, "index", None),
                        "page_number": getattr(link, "page_number", None),
                        "label": getattr(link, "label", None),
                        "contents": getattr(link, "contents", None),
                        "url": getattr(link, "url", None),
                    }
                    for link in raw_links
                ]
                summary = f"PDF icinde {len(raw_links)} adet link bulundu."
                next_step = "Tiklamak istediginiz linki anahtar kelime ile belirtin."
                result = {"links": simplified[:12], "count": len(raw_links)}

        elif parsed.action == "reuse_agent_browser_session":
            session = get_agent_browser_session_info()
            _remember_browser_session(
                session_id=session.session_id,
                mode=session.mode,
                provider="agent_browser",
                title=session.title or "",
                url=session.url or "",
                origin=urlsplit(session.url or "").netloc if session.url else "",
                reusable=True,
                pending_user_finish=True,
                tab_count=session.page_count or 1,
                active_tab_id="tab-1",
            )
            summary = "Mevcut agent tarayici oturumu aktif."
            next_step = "Ayni sekmede devam edeceginiz islemi yazin."
            result = {
                "session_id": session.session_id,
                "url": session.url,
                "title": session.title,
                "mode": session.mode,
            }

        elif parsed.action == "read_agent_browser_state":
            session = get_agent_browser_session_info()
            _remember_browser_session(
                session_id=session.session_id,
                mode=session.mode,
                provider="agent_browser",
                title=session.title or "",
                url=session.url or "",
                origin=urlsplit(session.url or "").netloc if session.url else "",
                reusable=True,
                pending_user_finish=True,
                tab_count=session.page_count or 1,
                active_tab_id="tab-1",
            )
            summary = "Agent tarayici durumu okundu."
            next_step = "Sayfada yapmak istediginiz islemi yazin."
            result = {
                "session_id": session.session_id,
                "url": session.url,
                "title": session.title,
                "mode": session.mode,
            }

        elif parsed.action == "close_agent_browser_session":
            session = close_agent_browser_session()
            _clear_browser_context()
            summary = "Agent tarayici oturumu kapatildi."
            next_step = "Gerekirse yeni bir tarayici oturumu acabilirsiniz."
            result = {
                "session_id": session.session_id,
                "closed": session.closed,
            }

        elif parsed.action == "search_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if _looks_like_open_intent(command_text):
                approval_required = True
                approval_status = "approved" if command_approved else "pending"
                if approval_status == "pending":
                    summary = "Eslesen dosya bulunursa acilacak. Onay gerekiyor."
                    next_step = "Dosyayi acmak icin islemi onaylayin."
                    result = {"status": "pending_approval", **({"candidate": items[0]} if items else {})}
                elif items:
                    selected = max(items, key=lambda x: x.get("modified_at", 0))
                    document_type = _infer_document_type(selected["path"])
                    if parsed.workflow_profile == "agent_browser" or document_type == "pdf":
                        session = open_document_in_agent_browser(selected["path"])
                        link_info = None
                        if document_type == "pdf":
                            try:
                                link_info = extract_pdf_links(selected["path"])
                            except AgentBrowserError:
                                link_info = None
                        _INTERACTIVE_SESSION["active_file_path"] = selected["path"]
                        _INTERACTIVE_SESSION["active_file_name"] = selected.get("name", "")
                        _remember_browser_session(
                            session_id=session.session_id,
                            mode="document",
                            provider="agent_browser",
                            title=session.title or selected.get("name", ""),
                            url=_file_path_to_url(selected["path"]),
                            document_type=document_type or "",
                            file_name=selected.get("name", ""),
                            interactive_links=link_info.get("link_count") if isinstance(link_info, dict) else None,
                            reusable=True,
                            pending_user_finish=True,
                        )
                        summary = f"'{selected['name']}' belgesi agent tarayicida acildi."
                        next_step = "PDF icindeki linklere tiklamak icin 'linke tikla' diyebilirsiniz."
                        result = {
                            "opened_file": selected,
                            "session_id": session.session_id,
                            "link_count": link_info.get("link_count") if isinstance(link_info, dict) else None,
                            "resolved_location": resolved_location,
                        }
                    else:
                        result = open_file_path(selected["path"], allowed_folders=settings.allowed_folders)
                        result["resolved_location"] = resolved_location
                        summary = f"'{selected['name']}' dosyasi acildi."
                        next_step = "Sonraki UI komutunu yazabilirsiniz. Is bitince 'tamam' veya 'bitti' yazin."
                else:
                    summary = "Acilacak dosya bulunamadi."
                    next_step = "Dosya adini veya uzantisini daha net yazip tekrar deneyin."
                    result = {"message": "Eslesen dosya bulunamadi."}
            else:
                summary = f"{len(items)} adet dosya bulundu."
                next_step = "Isterseniz bu dosyalari siralayabilir veya size gonderilmesini isteyebilirsiniz."
                result = {"items": items, "count": len(items), "resolved_location": resolved_location}

        elif parsed.action == "open_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "Eslesen dosya bulunursa acilacak. Onay gerekiyor."
                next_step = "Dosyayi acmak icin islemi onaylayin."
                result = {"status": "pending_approval", **({"candidate": items[0]} if items else {})}
            elif items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                document_type = _infer_document_type(selected["path"])
                if parsed.workflow_profile == "agent_browser" and document_type in {"pdf"}:
                    session = open_document_in_agent_browser(selected["path"])
                    link_info = None
                    if document_type == "pdf":
                        try:
                            link_info = extract_pdf_links(selected["path"])
                        except AgentBrowserError:
                            link_info = None
                    _INTERACTIVE_SESSION["active_file_path"] = selected["path"]
                    _INTERACTIVE_SESSION["active_file_name"] = selected.get("name", "")
                    _remember_browser_session(
                        session_id=session.session_id,
                        mode="document",
                        provider="agent_browser",
                        title=session.title or selected.get("name", ""),
                        url=_file_path_to_url(selected["path"]),
                        document_type=document_type,
                        file_name=selected.get("name", ""),
                        interactive_links=link_info.get("link_count") if isinstance(link_info, dict) else None,
                        reusable=True,
                        pending_user_finish=True,
                    )
                    result = {
                        "opened_file": selected,
                        "session_id": session.session_id,
                        "link_count": link_info.get("link_count") if isinstance(link_info, dict) else None,
                        "resolved_location": resolved_location,
                    }
                    summary = f"'{selected['name']}' belgesi agent tarayicida acildi."
                    next_step = "PDF icindeki linklere tiklamak icin 'linke tikla' diyebilirsiniz."
                else:
                    result = open_file_path(selected["path"], allowed_folders=settings.allowed_folders)
                    result["resolved_location"] = resolved_location
                    summary = f"'{selected['name']}' dosyasi acildi."
                    next_step = "Sonraki UI komutunu yazabilirsiniz. Is bitince 'tamam' veya 'bitti' yazin."
            else:
                summary = "Acilacak dosya bulunamadi."
                next_step = "Dosya adini veya uzantisini daha net yazip tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "copy_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                approval_required = True
                approval_status = "approved" if command_approved else "pending"
                if approval_status == "pending":
                    summary = f"'{selected['name']}' dosyasi bulundu. Kopyalama islemi onay bekliyor."
                    next_step = "Lutfen dosyayi kopyalamak amaciyla isleme onay verin."
                    result = {"source_file": selected, "status": "pending_approval"}
                else:
                    copied = copy_file_to_location(
                        selected["path"],
                        destination_location=parsed.params.get("destination_location", "desktop"),
                        allowed_folders=settings.allowed_folders,
                    )
                    summary = "Dosya kopyalama islemi onaylandi ve gerceklestirildi."
                    next_step = "Baska bir ihtiyaciniz var mi?"
                    result = {
                        "source_file": selected,
                        "copied_file": copied,
                        "status": "copied",
                        "message": "Dosyanin kopyasi olusturuldu.",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Kopyalanacak dosya bulunamadi."
                next_step = "Dosyanin adini veya uzantisini kontrol ederek tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "move_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                destination_location = parsed.params.get("destination_location", "desktop")
                approval_required = True
                approval_status = "approved" if command_approved else "pending"
                if approval_status == "pending":
                    summary = f"'{selected['name']}' dosyasi {destination_location} konumuna tasinacak. Onay gerekiyor."
                    next_step = "Tasima islemini onaylayin."
                    result = {
                        "source_file": selected,
                        "destination_location": destination_location,
                        "resolved_location": resolved_location,
                        "status": "pending_approval",
                    }
                else:
                    moved = move_file_to_location(
                        selected["path"],
                        destination_location=destination_location,
                        allowed_folders=settings.allowed_folders,
                    )
                    summary = "Dosya tasima islemi tamamlandi."
                    next_step = "Baska bir ihtiyaciniz var mi?"
                    result = {
                        "source_file": selected,
                        "moved_file": moved,
                        "status": "moved",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Tasinacak dosya bulunamadi."
                next_step = "Dosya adini veya uzantisini kontrol ederek tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "rename_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                new_name = parsed.params.get("new_name", "")
                approval_required = True
                approval_status = "approved" if command_approved else "pending"
                if approval_status == "pending":
                    summary = f"'{selected['name']}' dosyasi yeniden adlandirilacak. Onay gerekiyor."
                    next_step = "Yeniden adlandirma islemini onaylayin."
                    result = {
                        "source_file": selected,
                        "new_name": new_name,
                        "resolved_location": resolved_location,
                        "status": "pending_approval",
                    }
                else:
                    renamed = rename_file_in_place(
                        selected["path"],
                        new_name=str(new_name),
                        allowed_folders=settings.allowed_folders,
                    )
                    summary = "Dosya yeniden adlandirildi."
                    next_step = "Baska bir ihtiyaciniz var mi?"
                    result = {
                        "source_file": selected,
                        "renamed_file": renamed,
                        "status": "renamed",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Yeniden adlandirilacak dosya bulunamadi."
                next_step = "Dosya adini veya uzantisini kontrol ederek tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "delete_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                approval_required = True
                approval_status = "approved" if command_approved else "pending"
                if approval_status == "pending":
                    summary = f"'{selected['name']}' dosyasi silinecek. Onay gerekiyor."
                    next_step = "Silme islemini onaylayin."
                    result = {
                        "source_file": selected,
                        "resolved_location": resolved_location,
                        "status": "pending_approval",
                    }
                else:
                    deleted = delete_file_in_place(
                        selected["path"],
                        allowed_folders=settings.allowed_folders,
                    )
                    summary = "Dosya silindi."
                    next_step = "Baska bir ihtiyaciniz var mi?"
                    result = {
                        "deleted_file": deleted,
                        "status": "deleted",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Silinecek dosya bulunamadi."
                next_step = "Dosya adini veya uzantisini kontrol ederek tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "send_latest":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                latest = max(items, key=lambda x: x.get("modified_at", 0))
                recipient = parsed.params.get("recipient")
                if recipient:
                    approval_required = True
                    approval_status = "approved" if command_approved else "pending"
                    if approval_status == "pending":
                        summary = f"'{latest['name']}' dosyasi bulundu. Mail gonderimi onay bekliyor."
                        next_step = "Riski onlemek adina gonderimi onaylayin."
                        result = {"latest_file": latest, "recipient": recipient, "status": "pending_approval"}
                    else:
                        settings.mail_recipients_whitelist = add_mail_recipient_to_whitelist(str(recipient))
                        send_email_with_attachment(
                            recipient=recipient,
                            subject="AI Destekli Teknik Destek Ajani",
                            body="Istenen dosya ektedir.",
                            file_path=latest["path"],
                            host=settings.smtp_host,
                            port=settings.smtp_port,
                            username=settings.smtp_username,
                            password=settings.smtp_password,
                            use_tls=settings.smtp_use_tls,
                            sender=settings.default_mail_from,
                            allowed_recipients=settings.mail_recipients_whitelist,
                            mail_transport=settings.mail_transport,
                            browser_channel=settings.playwright_browser_channel,
                            user_data_dir=settings.playwright_user_data_dir,
                            mail_url=settings.playwright_mail_url,
                            headless=settings.playwright_headless,
                        )
                        summary = f"'{latest['name']}' dosyasi {recipient} adresine gonderildi."
                        next_step = "Baska bir ihtiyaciniz varsa iletebilirsiniz."
                        result = {
                            "latest_file": latest,
                            "recipient": recipient,
                            "status": "sent",
                            "message": "En son dosya bulundu ve gonderildi.",
                            "resolved_location": resolved_location,
                        }
                else:
                    _INTERACTIVE_SESSION["pending_prompt"] = "Alici e-posta adresi gerekli."
                    _INTERACTIVE_SESSION["pending_action"] = "send_latest"
                    _INTERACTIVE_SESSION["pending_field"] = "recipient"
                    _INTERACTIVE_SESSION["pending_params"] = {
                        "query": parsed.params.get("query", ""),
                        "location": parsed.params.get("location", "desktop"),
                        "extension": parsed.params.get("extension"),
                    }
                    _INTERACTIVE_SESSION["pending_recipient_prompt"] = "Alici e-posta adresi gerekli."
                    _INTERACTIVE_SESSION["pending_recipient_action"] = "send_latest"
                    _INTERACTIVE_SESSION["pending_recipient_params"] = dict(_INTERACTIVE_SESSION["pending_params"])
                    _INTERACTIVE_SESSION["pending_recipient_expires_at"] = time.time() + 1800
                    summary = f"En son dosya ({latest['name']}) bulundu. Alici e-posta adresini yazin."
                    next_step = "Ornek: ali@example.com"
                    result = {
                        "latest_file": latest,
                        "message": "Dosya bulundu. Gondermek icin alici e-posta adresi gerekli.",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Uzanti veya konuma uygun dosya bulunamadi."
                next_step = "Farkli bir klasor belirtmeyi veya uzantiyi degistirmeyi deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "create_folder":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            folder_name = parsed.params.get("folder_name", "Yeni Klasor")
            destination_location = parsed.params.get("destination_location", "desktop")
            if approval_status == "pending":
                summary = f"'{folder_name}' isimli klasor {destination_location} konumunda olusturulacak. Onay gerekiyor."
                next_step = "Klasor olusturma islemini onaylayin."
                result = {
                    "folder_name": folder_name,
                    "destination_location": destination_location,
                    "status": "pending_approval",
                }
            else:
                created = create_folder_in_location(
                    str(folder_name),
                    destination_location=str(destination_location),
                    allowed_folders=settings.allowed_folders,
                )
                summary = f"'{created['name']}' klasoru olusturuldu."
                next_step = "Baska bir ihtiyaciniz var mi?"
                result = {
                    "created_folder": created,
                    "status": "created",
                }

        elif parsed.action == "open_application":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            app_name = parsed.params.get("app_name", "")
            target = parsed.params.get("target")
            if approval_status == "pending":
                summary = f"'{app_name}' uygulamasi acilacak. Onay gerekiyor."
                next_step = "Uygulamayi acmak icin islemi onaylayin."
                result = {"app_name": app_name, "target": target, "status": "pending_approval"}
            else:
                resolved_target = str(target).strip() if target is not None else ""
                result = open_application(app_name=str(app_name), target=resolved_target or None)
                summary = f"'{app_name}' uygulamasi acildi veya one getirildi."
                next_step = "Gerekirse sonraki adimi yazabilirsiniz."

        elif parsed.action == "list_windows":
            result = list_windows()
            summary = f"{result.get('count', 0)} adet gorunen pencere bulundu."
            next_step = "Odaklanmak istediginiz pencereyi belirtebilirsiniz."

        elif parsed.action == "focus_window":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "Belirtilen pencereye gecilecek. Onay gerekiyor."
                next_step = "Pencere odagini degistirmek icin islemi onaylayin."
                result = {"status": "pending_approval", **parsed.params}
            else:
                result = focus_window(
                    title_contains=str(parsed.params.get("title_contains", "")).strip() or None,
                    process_name=str(parsed.params.get("process_name", "")).strip() or None,
                )
                summary = "Pencere one getirildi."
                next_step = "Gerekirse sonraki komutu yazabilirsiniz."

        elif parsed.action == "wait_for_window":
            result = wait_for_window(
                title_contains=str(parsed.params.get("title_contains", "")).strip() or None,
                process_name=str(parsed.params.get("process_name", "")).strip() or None,
                timeout_seconds=int(parsed.params.get("timeout_seconds", 20) or 20),
            )
            summary = "Beklenen pencere bulundu."
            next_step = "Gerekirse pencereye odaklanabilir veya bir sonraki adimi calistirabilirsiniz."

        elif parsed.action == "click_ui":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "Arayuzde bir hedefe tiklanacak. Onay gerekiyor."
                next_step = "Tiklama islemini onaylayin."
                result = {"status": "pending_approval", **parsed.params}
            else:
                result = click_ui(
                    x=int(parsed.params["x"]) if "x" in parsed.params else None,
                    y=int(parsed.params["y"]) if "y" in parsed.params else None,
                    button=str(parsed.params.get("button", "left")).strip() or "left",
                    text=str(parsed.params.get("text", "")).strip() or None,
                    title_contains=str(parsed.params.get("title_contains", "")).strip() or None,
                    process_name=str(parsed.params.get("process_name", "")).strip() or None,
                )
                summary = "Hedef arayuz ogesi tiklandi."
                next_step = "Gerekirse ekrani tekrar okuyabilir veya bir sonraki adimi yazabilirsiniz."

        elif parsed.action == "type_ui":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "Arayuzde bir alana yazi yazilacak. Onay gerekiyor."
                next_step = "Yazma islemini onaylayin."
                result = {"status": "pending_approval", **parsed.params}
            else:
                result = type_ui(
                    text_to_type=str(parsed.params.get("text_to_type", "")).strip(),
                    text_filter=str(parsed.params.get("text_filter", "")).strip() or None,
                    title_contains=str(parsed.params.get("title_contains", "")).strip() or None,
                    process_name=str(parsed.params.get("process_name", "")).strip() or None,
                )
                summary = "Hedef alana yazi yazildi."
                next_step = "Gerekirse ekranin son halini dogrulayin veya devam edin."

        elif parsed.action == "verify_ui_state":
            result = verify_ui_state(
                expected_text=str(parsed.params.get("expected_text", "")).strip() or None,
                timeout_seconds=5,
            )
            if result.get("status") == "found":
                summary = f"Beklenen yazi ({parsed.params.get('expected_text')}) ekranda bizzat tespit edildi."
                next_step = "Islem basariyla dogrulandi, sonraki adima gecebilirsiniz."
            elif result.get("status") == "timeout":
                summary = f"Beklenen yazi ({parsed.params.get('expected_text')}) tarama suresi icinde ekranda bulunamadi."
                next_step = "Aksiyon basarisiz olmus veya gecikmis olabilir. Lutfen pencereyi kontrol edin."
                error = "UI Dogrulama basarisiz oldu."
            else:
                summary = "Guncel ekran elemanlari okundu."
                next_step = "Ekrandaki verilere bakarak isleme devam edebilirsiniz."

        elif parsed.action == "read_screen":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "Ekran durumu toplanacak. Onay gerekiyor."
                next_step = "Ekran goruntusu almak icin islemi onaylayin."
                result = {"status": "pending_approval"}
            else:
                result = read_screen(mode="medium")
                summary = "Ekran durumu toplandi."
                next_step = "Gerekirse devam komutunu yazabilirsiniz."

        elif parsed.action == "take_screenshot":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "Ekran goruntusu alinacak. Onay gerekiyor."
                next_step = "Ekran goruntusu almak icin islemi onaylayin."
                result = {"status": "pending_approval"}
            else:
                result = take_screenshot()
                summary = "Ekran goruntusu alindi."
                next_step = "Dosya yolunu sonuc ekraninda gorebilirsiniz."

        elif parsed.action == "run_script":
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            script_names = parsed.params.get("script_names")
            if isinstance(script_names, list) and script_names:
                if approval_status == "pending":
                    summary = f"Sistemde {len(script_names)} adet guvenli script calistirilmak isteniyor."
                    next_step = "Sisteme yetkili erisim saglamak icin onayinizi isaretlemeniz gereklidir."
                    result = {"script_names": script_names, "status": "pending_approval"}
                else:
                    steps: list[dict] = []
                    for script_name in script_names:
                        steps.append(
                            {
                                "tool": "run_whitelisted_script",
                                **run_script(str(script_name), allowed_scripts=settings.allowed_scripts),
                            }
                        )
                    summary = f"Secili {len(script_names)} adet script onay sonrasi calistirildi."
                    next_step = "Ciktilari asagidaki ekranda kontrol edebilirsiniz."
                    result = {
                        "summary": "Hazir script zinciri calistirildi.",
                        "steps": steps,
                        "step_count": len(steps),
                    }
            else:
                script_name = parsed.params.get("script_name", "")
                if not script_name:
                    summary = "Calistirilacak spesifik bir script belirlenemedi."
                    next_step = "Hangi script'in calistirilacagini daha net ifade edin (or. 'dns onarim scriptini calistir')."
                    error = "Hangi scriptin calistirilacagi belirlenemedi."
                else:
                    if approval_status == "pending":
                        summary = f"'{script_name}' isimli scripti calistirmak uzeresiniz. Onay gerekiyor."
                        next_step = "Islemi onaylayip devam edin."
                        result = {"script_name": script_name, "status": "pending_approval"}
                    else:
                        result = run_script(script_name, allowed_scripts=settings.allowed_scripts)
                        summary = f"'{script_name}' isimli script basariyla calistirildi."
                        next_step = "Sistem veya ag uzerinde cikan degisiklikleri dogrulayin."

        elif parsed.action == "system_status":
            result = get_system_status()
            summary = "Sistem durumu ve zafiyet analizleri alindi."
            next_step = ""

        elif parsed.action == "list_scripts":
            from adapters.script_adapter import list_scripts

            items = list_scripts()
            summary = f"Toplam {len(items)} adet whitelist scripti bulundu."
            next_step = "Calistirmak istediginiz scriptin ismini yazabilirsiniz."
            result = {"items": items, "count": len(items)}

        elif parsed.action == "send_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                recipient = parsed.params.get("recipient")
                if recipient:
                    approval_required = True
                    approval_status = "approved" if command_approved else "pending"
                    selected = max(items, key=lambda x: x.get("modified_at", 0))
                    if approval_status == "pending":
                        summary = f"'{selected['name']}' dosyasi bulundu. Mail gonderimi yonetici onayi bekliyor."
                        next_step = "Lutfen yapilandirmayi dogrulayarak gonderme onayi verin."
                        result = {"sent_file": selected, "recipient": recipient, "status": "pending_approval"}
                    else:
                        settings.mail_recipients_whitelist = add_mail_recipient_to_whitelist(str(recipient))
                        send_email_with_attachment(
                            recipient=recipient,
                            subject="AI Destekli Teknik Destek Ajani",
                            body="Istenen dosya ektedir.",
                            file_path=selected["path"],
                            host=settings.smtp_host,
                            port=settings.smtp_port,
                            username=settings.smtp_username,
                            password=settings.smtp_password,
                            use_tls=settings.smtp_use_tls,
                            sender=settings.default_mail_from,
                            allowed_recipients=settings.mail_recipients_whitelist,
                            mail_transport=settings.mail_transport,
                            browser_channel=settings.playwright_browser_channel,
                            user_data_dir=settings.playwright_user_data_dir,
                            mail_url=settings.playwright_mail_url,
                            headless=settings.playwright_headless,
                        )
                        summary = f"'{selected['name']}' isimli dosya e-posta olarak {recipient} adresine iletildi."
                        next_step = "Alici kisisinin urun maillerini teyit edin."
                        result = {
                            "sent_file": selected,
                            "recipient": recipient,
                            "count": len(items),
                            "status": "sent",
                            "message": "Dosya bulundu ve gonderildi.",
                            "resolved_location": resolved_location,
                        }
                else:
                    _INTERACTIVE_SESSION["pending_prompt"] = "Alici e-posta adresi gerekli."
                    _INTERACTIVE_SESSION["pending_action"] = "send_file"
                    _INTERACTIVE_SESSION["pending_field"] = "recipient"
                    _INTERACTIVE_SESSION["pending_params"] = {
                        "query": parsed.params.get("query", ""),
                        "location": parsed.params.get("location", "desktop"),
                        "extension": parsed.params.get("extension"),
                    }
                    _INTERACTIVE_SESSION["pending_recipient_prompt"] = "Alici e-posta adresi gerekli."
                    _INTERACTIVE_SESSION["pending_recipient_action"] = "send_file"
                    _INTERACTIVE_SESSION["pending_recipient_params"] = dict(_INTERACTIVE_SESSION["pending_params"])
                    _INTERACTIVE_SESSION["pending_recipient_expires_at"] = time.time() + 1800
                    summary = "Alici e-posta adresi gerekli. Lutfen aliciyi yazin."
                    next_step = "Ornek: ali@example.com"
                    result = {
                        "found_files": items[:5],
                        "count": len(items),
                        "message": "Dosyalar bulundu. Gonderim icin alici e-posta adresi gerekli.",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Iletilmek istenen dosya mevcut degil."
                next_step = "Dosya adini gozden gecirin veya arama limitlerini genisletin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "create_ticket":
            title = str(parsed.params.get("title", "") or "").strip() or "Destek talebi"
            description = str(parsed.params.get("description", "") or "").strip() or original_text
            ticket_id = create_support_ticket(
                settings.sqlite_path,
                title=title,
                description=description,
                source_text=original_text,
                metadata={
                    "workflow_profile": parsed.workflow_profile,
                    "knowledge_hint": parsed.knowledge_hint,
                },
            )
            summary = "Destek bileti olusturuldu."
            next_step = "Bilet numarasini not alip takip edebilirsiniz."
            result = {
                "ticket_id": ticket_id,
                "status": "created",
                "title": title,
                "description": description,
            }

        else:
            approval_required = True
            approval_status = "approved" if command_approved else "pending"
            if approval_status == "pending":
                summary = "Sistemin standart cozum yollari veya yetenekleri disinda olan bir islem algilandi."
                next_step = "Guvenli cercevede isleme devam etmek icin onaylayiniz."
                result = {"status": "pending_approval"}
            else:
                try:
                    active_settings = _apply_model_override(settings, session_state.model_provider, session_state.model_name)
                    if active_settings.ai_provider == "openrouter":
                        active_key = active_settings.openrouter_api_key
                        active_model = active_settings.openrouter_model
                    else:
                        active_key = active_settings.gemini_api_key
                        active_model = active_settings.gemini_model

                    try:
                        result = generate_and_run_script(
                            command_text,
                            api_key=active_key,
                            model=active_model,
                            ai_provider=active_settings.ai_provider,
                            workflow_profile=parsed.workflow_profile if parsed else None,
                            allowed_folders=settings.allowed_folders,
                            forbidden_actions=settings.forbidden_actions,
                        )
                        summary = "Sistemdeki kural tabanli otomasyon islendi."
                        next_step = "Konsol ciktilarina bakabilirsiniz."
                    except Exception as primary_exc:
                        # Fallback to Gemini when OpenRouter fails.
                        if (
                            active_settings.ai_provider == "openrouter"
                            and settings.gemini_api_key
                            and settings.gemini_model
                        ):
                            result = generate_and_run_script(
                                command_text,
                                api_key=settings.gemini_api_key,
                                model=settings.gemini_model,
                                ai_provider="gemini",
                                workflow_profile=parsed.workflow_profile if parsed else None,
                                allowed_folders=settings.allowed_folders,
                                forbidden_actions=settings.forbidden_actions,
                            )
                            summary = "OpenRouter hatasi alindi, Gemini ile tekrar denendi."
                            next_step = "Konsol ciktilarina bakabilirsiniz."
                        else:
                            raise primary_exc
                except Exception as eval_exc:
                    summary = "Sistem bu istegi zekice analiz etti fakat gerceklestirebilecek guvenli bir yol bulamadi."
                    error = _humanize_error(str(eval_exc))
                    handoff_recommended = True
                    next_step = "Isterseniz dogrudan destek bileti olusturabilirim. Ornegin: 'ticket ac outlook mail gondermiyor'."

        log_task(
            settings.sqlite_path,
            task_type="command",
            status="success" if not error else "failed",
            input_text=original_text,
            output_text=str(result) if result else str(error),
            metadata={
                "action": parsed.action,
                "confidence": parsed.confidence,
                "params": parsed.params,
                "summary": summary,
                "next_step": next_step,
                "approval_status": approval_status,
                "effective_text": command_text,
                "timing_ms": {
                    "parse": parse_ms,
                    "execute": round(max(((time.perf_counter() - request_started_at) * 1000) - parse_ms, 0.0), 1),
                    "total": round((time.perf_counter() - request_started_at) * 1000, 1),
                },
            },
        )
        if approval_status != "pending":
            _remember_retry(command_text, command_approved)
            _remember_active_context(parsed.action, result, parsed)

    except BrowserAuthError as exc:
        _remember_retry(command_text, True)
        try:
            result = _mail_session_workflow()
        except Exception as prep_exc:
            result = {
                "summary": "Mail oturumu hazirlama zinciri baslatilamadi.",
                "steps": [
                    {
                        "title": "Mail oturumu hazirligi",
                        "status": "error",
                        "error": str(prep_exc),
                    }
                ],
                "step_count": 1,
            }
        if parsed is not None:
            parsed.workflow_profile = "app_control"
        error = f"Oturum izni gerekiyor: {str(exc)} (Hata Kodu: {exc.code})"
        summary = "Tarayicida islem yapabilmek icin ilgili hesaba giris yapmaniz gerekmektedir. Hazirlik akisi baslatildi."
        next_step = "Acilan tarayici penceresinde oturum acin. Sonra 'oturum acik devam et' veya 'tekrar dene' yazabilirsiniz."
        log_task(
            settings.sqlite_path,
            task_type="command",
            status="error",
            input_text=original_text,
            output_text=str(exc),
            metadata={"action": parsed.action if parsed else "parse_failed", "error_code": exc.code, "effective_text": command_text},
        )
    except BrowserStateError as exc:
        error = f"Sayfa hazir degil veya dogrulanamadi: {str(exc)} (Hata Kodu: {exc.code})"
        summary = "Tarayici islemini gerceklestirirken sayfa yuklenmesi veya durumunda hata olustu."
        next_step = "Sistem yogunlugu veya teknik bir sikinti olabilir. Birkac saniye bekleyip tekrar deneyin."
        log_task(
            settings.sqlite_path,
            task_type="command",
            status="error",
            input_text=original_text,
            output_text=str(exc),
            metadata={"action": parsed.action if parsed else "parse_failed", "error_code": exc.code, "effective_text": command_text},
        )
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = _humanize_error(str(exc))
        handoff_recommended = True
        if not summary:
            summary = "Sistem bu islem sirasinda beklenmeyen bir bloklayici ile karsilasti."
        next_step = "Isterseniz dogrudan destek bileti olusturabilirsiniz."
        log_task(
            settings.sqlite_path,
            task_type="command",
            status="error",
            input_text=original_text,
            output_text=str(exc),
            metadata={"action": parsed.action if parsed else "parse_failed", "effective_text": command_text},
        )
    except Exception as exc:
        error = _humanize_error(f"{type(exc).__name__}: {str(exc)}")
        handoff_recommended = True
        if not summary:
            summary = "Gorev islenirken dis servislere baglanti kurulamadi veya model yogunlugu yasandi."
        next_step = "Isterseniz isleme birkac dakika sonra tekrar baslayabilir veya destek bileti olusturabilirsiniz."
        log_task(
            settings.sqlite_path,
            task_type="command",
            status="error",
            input_text=original_text,
            output_text=str(exc),
            metadata={"action": parsed.action if parsed else "parse_failed", "type": type(exc).__name__, "effective_text": command_text},
        )

    if approval_status == "pending" and parsed is not None:
        _remember_pending_approval(parsed.action, parsed.params, parsed.workflow_profile)
    elif approval_status != "pending":
        _clear_approval_context()

    response = CommandResponse(
        action=parsed.action if parsed else "unknown",
        confidence=parsed.confidence if parsed else 0.0,
        workflow_profile=parsed.workflow_profile if parsed else None,
        session_context=_build_session_context(),
        browser_context=_build_browser_context(),
        timing={
            "parse_ms": parse_ms,
            "execute_ms": round(max(((time.perf_counter() - request_started_at) * 1000) - parse_ms, 0.0), 1),
            "total_ms": round((time.perf_counter() - request_started_at) * 1000, 1),
            "resumed": command_text != original_text,
        },
        summary=summary,
        next_step=next_step,
        approval=ApprovalStatus(required=approval_required, status=approval_status),
        params=parsed.params if parsed else {},
        result=result,
        knowledge_hint=parsed.knowledge_hint if parsed else None,
        error=error,
        handoff_recommended=handoff_recommended,
    )
    total_elapsed = round((time.perf_counter() - request_started_at) * 1000, 1)
    record_history(
        session_state,
        command_text=command_text,
        action=parsed.action if parsed else "unknown",
        status="failed" if error else "success",
        summary=summary,
        elapsed_ms=total_elapsed,
    )
    return response


@ui_router.post("/command-ui", response_model=CommandResponse, include_in_schema=False)
def execute_command_ui(request: CommandRequest, http_request: Request) -> CommandResponse:
    return execute_command(request, http_request)
