from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from starlette import status as http_status

from adapters.system_adapter import get_system_status
from core.auth import bearer_token_dependency
from core.config import load_settings
from db import get_task, list_tasks


settings = load_settings()
auth_dependency = Depends(bearer_token_dependency(settings.bearer_token))
router = APIRouter(tags=["system"])


@router.get("/status", dependencies=[auth_dependency])
def system_status() -> dict[str, object]:
    return get_system_status()


@router.get("/tasks", dependencies=[auth_dependency], tags=["tasks"])
def tasks() -> dict[str, object]:
    items = [asdict(item) for item in list_tasks(settings.sqlite_path)]
    return {"items": items, "count": len(items)}


@router.get("/tasks/{task_id}", dependencies=[auth_dependency], tags=["tasks"])
def task_detail(task_id: int) -> dict[str, object]:
    item = get_task(settings.sqlite_path, task_id)
    if not item:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Task bulunamadi.")
    return {"item": asdict(item)}
