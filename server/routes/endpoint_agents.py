from __future__ import annotations

import secrets
import hashlib
from dataclasses import asdict
from hmac import compare_digest
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from core.auth import bearer_token_dependency
from core.config import load_settings
from db import (
    complete_endpoint_job,
    create_endpoint_device,
    enqueue_endpoint_job,
    get_endpoint_device,
    get_endpoint_device_token,
    lease_next_endpoint_job,
    list_endpoint_devices,
    list_endpoint_jobs,
    update_endpoint_device_profile,
    update_endpoint_heartbeat,
)


settings = load_settings()
operator_auth_dependency = Depends(bearer_token_dependency(settings.bearer_token))
router = APIRouter(prefix="/endpoint-agents", tags=["endpoint-agents"])


class RegisterEndpointDeviceRequest(BaseModel):
    hostname: str = ""
    os: str = ""
    rustdesk_id: str = ""
    version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    status: str = "online"
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateEndpointDeviceProfileRequest(BaseModel):
    hostname: str | None = None
    os: str | None = None
    rustdesk_id: str | None = None
    version: str | None = None
    capabilities: list[str] | None = None
    metadata: dict[str, Any] | None = None


class CreateEndpointJobRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CompleteEndpointJobRequest(BaseModel):
    status: Literal["succeeded", "failed", "blocked"]
    result: dict[str, Any] = Field(default_factory=dict)
    error_text: str = ""


def _require_device_token(device_id: str, token: str | None) -> None:
    stored_token = get_endpoint_device_token(settings.sqlite_path, device_id)
    token_hash = hashlib.sha256((token or "").encode("utf-8")).hexdigest()
    if not stored_token or not token or not compare_digest(stored_token, token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing device token",
            headers={"WWW-Authenticate": "DeviceToken"},
        )


@router.post("/devices/register", dependencies=[operator_auth_dependency])
def register_endpoint_device(request: RegisterEndpointDeviceRequest) -> dict[str, object]:
    device_token = secrets.token_urlsafe(32)
    device_token_hash = hashlib.sha256(device_token.encode("utf-8")).hexdigest()
    device = create_endpoint_device(
        settings.sqlite_path,
        token=device_token_hash,
        hostname=request.hostname,
        os_name=request.os,
        rustdesk_id=request.rustdesk_id,
        version=request.version,
        capabilities=request.capabilities,
        metadata=request.metadata,
    )
    return {"device": asdict(device), "device_token": device_token}


@router.get("/devices", dependencies=[operator_auth_dependency])
def endpoint_devices() -> dict[str, object]:
    items = [asdict(item) for item in list_endpoint_devices(settings.sqlite_path)]
    return {"items": items, "count": len(items)}


@router.post("/devices/{device_id}/heartbeat")
def endpoint_heartbeat(
    device_id: str,
    request: HeartbeatRequest,
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> dict[str, object]:
    _require_device_token(device_id, x_device_token)
    device = update_endpoint_heartbeat(
        settings.sqlite_path,
        device_id,
        status=request.status,
        metadata=request.metadata,
    )
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device bulunamadi.")
    return {"device": asdict(device)}


@router.post("/devices/{device_id}/profile")
def update_endpoint_profile(
    device_id: str,
    request: UpdateEndpointDeviceProfileRequest,
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> dict[str, object]:
    _require_device_token(device_id, x_device_token)
    device = update_endpoint_device_profile(
        settings.sqlite_path,
        device_id,
        hostname=request.hostname,
        os_name=request.os,
        rustdesk_id=request.rustdesk_id,
        version=request.version,
        capabilities=request.capabilities,
        metadata=request.metadata,
    )
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device bulunamadi.")
    return {"device": asdict(device)}


@router.post("/devices/{device_id}/jobs", dependencies=[operator_auth_dependency])
def create_endpoint_job(device_id: str, request: CreateEndpointJobRequest) -> dict[str, object]:
    if not get_endpoint_device(settings.sqlite_path, device_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device bulunamadi.")
    if not request.action.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action gerekli.")
    job = enqueue_endpoint_job(
        settings.sqlite_path,
        device_id=device_id,
        action=request.action.strip(),
        payload=request.payload,
    )
    return {"job": asdict(job)}


@router.get("/devices/{device_id}/jobs", dependencies=[operator_auth_dependency])
def endpoint_jobs(device_id: str) -> dict[str, object]:
    if not get_endpoint_device(settings.sqlite_path, device_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device bulunamadi.")
    items = [asdict(item) for item in list_endpoint_jobs(settings.sqlite_path, device_id=device_id)]
    return {"items": items, "count": len(items)}


@router.get("/devices/{device_id}/jobs/next")
def next_endpoint_job(
    device_id: str,
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> dict[str, object]:
    _require_device_token(device_id, x_device_token)
    job = lease_next_endpoint_job(settings.sqlite_path, device_id=device_id)
    return {"job": asdict(job) if job else None}


@router.post("/devices/{device_id}/jobs/{job_id}/result")
def complete_job(
    device_id: str,
    job_id: int,
    request: CompleteEndpointJobRequest,
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> dict[str, object]:
    _require_device_token(device_id, x_device_token)
    job = complete_endpoint_job(
        settings.sqlite_path,
        device_id=device_id,
        job_id=job_id,
        status=request.status,
        result=request.result,
        error_text=request.error_text,
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job bulunamadi.")
    return {"job": asdict(job)}
