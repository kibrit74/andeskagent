from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from adapters.desktop_adapter import click_ui
from core.config import load_settings


settings = load_settings()
router = APIRouter(tags=["screen-control"])


class ScreenClickRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    button: str = "left"
    double_click: bool = True


@router.post("/screen/click")
def screen_click(payload: ScreenClickRequest, request: Request) -> dict[str, object]:
    auth_header = request.headers.get("authorization") or ""
    token_param = request.query_params.get("token") or ""
    expected = str(settings.bearer_token or "")
    supplied = ""
    if auth_header.lower().startswith("bearer "):
        supplied = auth_header[7:].strip()
    elif token_param:
        supplied = token_param.strip()
    if not expected or supplied != expected:
        return {"status": "unauthorized", "message": "Missing or invalid bearer token."}
    try:
        result = click_ui(
            x=payload.x,
            y=payload.y,
            button=payload.button,
            double_click=payload.double_click,
        )
        return {"status": "clicked", "result": result}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
