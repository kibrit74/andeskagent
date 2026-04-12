from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_PATH = BASE_DIR / "data" / "memory.json"


def _load_all() -> dict[str, dict[str, Any]]:
    if not MEMORY_PATH.exists():
        return {}
    with MEMORY_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_all(payload: dict[str, dict[str, Any]]) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MEMORY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _scope_key(tenant_id: str | None, session_id: str) -> str:
    if tenant_id:
        return f"tenant:{tenant_id}"
    return f"session:{session_id}"


def list_memory(*, tenant_id: str | None, session_id: str) -> dict[str, Any]:
    payload = _load_all()
    return payload.get(_scope_key(tenant_id, session_id), {})


def set_memory(*, tenant_id: str | None, session_id: str, key: str, value: Any) -> dict[str, Any]:
    payload = _load_all()
    scope = _scope_key(tenant_id, session_id)
    scope_data = payload.get(scope, {})
    scope_data[key] = value
    payload[scope] = scope_data
    _save_all(payload)
    return scope_data


def delete_memory(*, tenant_id: str | None, session_id: str, key: str) -> dict[str, Any]:
    payload = _load_all()
    scope = _scope_key(tenant_id, session_id)
    scope_data = payload.get(scope, {})
    if key in scope_data:
        scope_data.pop(key, None)
        payload[scope] = scope_data
        _save_all(payload)
    return scope_data

