from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from adapters.script_adapter import list_scripts, run_script
from core.auth import bearer_token_dependency
from core.config import load_settings
from db import log_task


settings = load_settings()
router = APIRouter(
    prefix="/scripts",
    tags=["scripts"],
    dependencies=[Depends(bearer_token_dependency(settings.bearer_token))],
)


class RunScriptRequest(BaseModel):
    script_name: str


@router.get("/list")
def scripts_list() -> dict[str, object]:
    items = list_scripts()
    return {"items": items, "count": len(items)}


@router.post("/run")
def scripts_run(request: RunScriptRequest) -> dict[str, object]:
    try:
        result = run_script(request.script_name, allowed_scripts=settings.allowed_scripts)
        log_task(
            settings.sqlite_path,
            task_type="scripts_run",
            status="success",
            input_text=request.script_name,
            output_text=str(result.get("returncode", "")),
        )
        return result
    except ValueError as error:
        log_task(
            settings.sqlite_path,
            task_type="scripts_run",
            status="blocked",
            input_text=request.script_name,
            output_text=str(error),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except RuntimeError as error:
        log_task(
            settings.sqlite_path,
            task_type="scripts_run",
            status="failed",
            input_text=request.script_name,
            output_text=str(error),
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
