from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from adapters.file_adapter import search_files
from core.auth import bearer_token_dependency
from core.config import load_settings
from db import log_task


settings = load_settings()
router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(bearer_token_dependency(settings.bearer_token))],
)


@router.get("/search")
def files_search(
    query: str = Query(..., min_length=2),
    location: str = Query(default="desktop"),
    extension: str | None = Query(default=None),
) -> dict[str, object]:
    results = search_files(
        query=query,
        location=location,
        extension=extension,
        allowed_folders=settings.allowed_folders,
    )
    log_task(
        settings.sqlite_path,
        task_type="files_search",
        status="success",
        input_text=query,
        output_text=f"{len(results)} result(s)",
        metadata={"location": location, "extension": extension},
    )
    return {"items": results, "count": len(results)}
