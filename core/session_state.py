from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SessionState:
    session_id: str
    operator_id: str | None = None
    tenant_id: str | None = None
    plan_mode: bool = False
    model_provider: str | None = None
    model_name: str | None = None
    current_agent: str | None = None
    current_agent_profile: str | None = None
    last_plan: dict[str, Any] | None = None
    last_plan_text: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=lambda: {"request_count": 0, "last_request_ms": 0.0})


_SESSIONS: dict[str, SessionState] = {}


def get_session_state(session_id: str, *, operator_id: str | None = None, tenant_id: str | None = None) -> SessionState:
    session_id = session_id.strip() or "default"
    existing = _SESSIONS.get(session_id)
    if existing:
        if operator_id:
            existing.operator_id = operator_id
        if tenant_id:
            existing.tenant_id = tenant_id
        return existing
    state = SessionState(session_id=session_id, operator_id=operator_id, tenant_id=tenant_id)
    _SESSIONS[session_id] = state
    return state


def record_history(
    state: SessionState,
    *,
    command_text: str,
    action: str,
    status: str,
    summary: str,
    elapsed_ms: float,
) -> None:
    state.history.append(
        {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "command": command_text,
            "action": action,
            "status": status,
            "summary": summary,
            "elapsed_ms": elapsed_ms,
        }
    )
    state.usage["request_count"] = int(state.usage.get("request_count", 0)) + 1
    state.usage["last_request_ms"] = float(elapsed_ms)


def rewind_last(state: SessionState) -> dict[str, Any] | None:
    if not state.history:
        return None
    return state.history.pop()
