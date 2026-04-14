from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TaskRecord:
    id: int | None
    task_type: str
    status: str
    input_text: str
    output_text: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class EndpointDeviceRecord:
    id: str
    hostname: str
    os: str
    rustdesk_id: str
    version: str
    status: str
    capabilities: list[str]
    metadata: dict[str, Any]
    last_seen_at: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class EndpointJobRecord:
    id: int | None
    device_id: str
    action: str
    payload: dict[str, Any]
    status: str
    result: dict[str, Any]
    error_text: str
    lease_expires_at: str
    created_at: str
    updated_at: str
    completed_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                input_text TEXT NOT NULL DEFAULT '',
                output_text TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS endpoint_devices (
                id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                hostname TEXT NOT NULL DEFAULT '',
                os TEXT NOT NULL DEFAULT '',
                rustdesk_id TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'registered',
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS endpoint_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                result_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                lease_expires_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(device_id) REFERENCES endpoint_devices(id)
            )
            """
        )
        conn.commit()


def _decode_json_object(raw: str | None) -> dict[str, Any]:
    payload = json.loads(raw or "{}")
    return payload if isinstance(payload, dict) else {}


def _decode_json_list(raw: str | None) -> list[str]:
    payload = json.loads(raw or "[]")
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload]


def _endpoint_device_from_row(row: Any) -> EndpointDeviceRecord:
    return EndpointDeviceRecord(
        id=row[0],
        hostname=row[1],
        os=row[2],
        rustdesk_id=row[3],
        version=row[4],
        status=row[5],
        capabilities=_decode_json_list(row[6]),
        metadata=_decode_json_object(row[7]),
        last_seen_at=row[8],
        created_at=row[9],
        updated_at=row[10],
    )


def _endpoint_job_from_row(row: Any) -> EndpointJobRecord:
    return EndpointJobRecord(
        id=row[0],
        device_id=row[1],
        action=row[2],
        payload=_decode_json_object(row[3]),
        status=row[4],
        result=_decode_json_object(row[5]),
        error_text=row[6],
        lease_expires_at=row[7],
        created_at=row[8],
        updated_at=row[9],
        completed_at=row[10],
    )


def create_endpoint_device(
    db_path: Path,
    *,
    token: str,
    hostname: str = "",
    os_name: str = "",
    rustdesk_id: str = "",
    version: str = "",
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    device_id: str | None = None,
) -> EndpointDeviceRecord:
    init_db(db_path)
    now = _utc_now()
    resolved_device_id = device_id or str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO endpoint_devices (
                id, token, hostname, os, rustdesk_id, version, status,
                capabilities_json, metadata_json, last_seen_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_device_id,
                token,
                hostname,
                os_name,
                rustdesk_id,
                version,
                "registered",
                json.dumps(capabilities or [], ensure_ascii=True),
                json.dumps(metadata or {}, ensure_ascii=True),
                now,
                now,
                now,
            ),
        )
        conn.commit()

    device = get_endpoint_device(db_path, resolved_device_id)
    assert device is not None
    return device


def get_endpoint_device(db_path: Path, device_id: str) -> EndpointDeviceRecord | None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, hostname, os, rustdesk_id, version, status, capabilities_json,
                   metadata_json, last_seen_at, created_at, updated_at
            FROM endpoint_devices
            WHERE id = ?
            """,
            (device_id,),
        ).fetchone()
    return _endpoint_device_from_row(row) if row else None


def get_endpoint_device_token(db_path: Path, device_id: str) -> str | None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT token FROM endpoint_devices WHERE id = ?", (device_id,)).fetchone()
    return str(row[0]) if row else None


def list_endpoint_devices(db_path: Path, limit: int = 100) -> list[EndpointDeviceRecord]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, hostname, os, rustdesk_id, version, status, capabilities_json,
                   metadata_json, last_seen_at, created_at, updated_at
            FROM endpoint_devices
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_endpoint_device_from_row(row) for row in rows]


def update_endpoint_heartbeat(
    db_path: Path,
    device_id: str,
    *,
    status: str = "online",
    metadata: dict[str, Any] | None = None,
) -> EndpointDeviceRecord | None:
    init_db(db_path)
    now = _utc_now()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE endpoint_devices
            SET status = ?, metadata_json = ?, last_seen_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, json.dumps(metadata or {}, ensure_ascii=True), now, now, device_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    return get_endpoint_device(db_path, device_id)


def update_endpoint_device_profile(
    db_path: Path,
    device_id: str,
    *,
    hostname: str | None = None,
    os_name: str | None = None,
    rustdesk_id: str | None = None,
    version: str | None = None,
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> EndpointDeviceRecord | None:
    init_db(db_path)
    fields: list[str] = []
    values: list[Any] = []

    if hostname is not None:
        fields.append("hostname = ?")
        values.append(hostname)
    if os_name is not None:
        fields.append("os = ?")
        values.append(os_name)
    if rustdesk_id is not None:
        fields.append("rustdesk_id = ?")
        values.append(rustdesk_id)
    if version is not None:
        fields.append("version = ?")
        values.append(version)
    if capabilities is not None:
        fields.append("capabilities_json = ?")
        values.append(json.dumps(capabilities, ensure_ascii=True))
    if metadata is not None:
        fields.append("metadata_json = ?")
        values.append(json.dumps(metadata, ensure_ascii=True))

    if not fields:
        return get_endpoint_device(db_path, device_id)

    fields.append("updated_at = ?")
    values.append(_utc_now())
    values.append(device_id)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE endpoint_devices SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    return get_endpoint_device(db_path, device_id)


def enqueue_endpoint_job(
    db_path: Path,
    *,
    device_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> EndpointJobRecord:
    init_db(db_path)
    now = _utc_now()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO endpoint_jobs (
                device_id, action, payload_json, status, result_json, error_text,
                lease_expires_at, created_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                action,
                json.dumps(payload or {}, ensure_ascii=True),
                "queued",
                "{}",
                "",
                "",
                now,
                now,
                "",
            ),
        )
        conn.commit()
        job_id = int(cursor.lastrowid)

    job = get_endpoint_job(db_path, job_id)
    assert job is not None
    return job


def get_endpoint_job(db_path: Path, job_id: int) -> EndpointJobRecord | None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, device_id, action, payload_json, status, result_json, error_text,
                   lease_expires_at, created_at, updated_at, completed_at
            FROM endpoint_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
    return _endpoint_job_from_row(row) if row else None


def list_endpoint_jobs(db_path: Path, *, device_id: str | None = None, limit: int = 100) -> list[EndpointJobRecord]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        if device_id:
            rows = conn.execute(
                """
                SELECT id, device_id, action, payload_json, status, result_json, error_text,
                       lease_expires_at, created_at, updated_at, completed_at
                FROM endpoint_jobs
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, device_id, action, payload_json, status, result_json, error_text,
                       lease_expires_at, created_at, updated_at, completed_at
                FROM endpoint_jobs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_endpoint_job_from_row(row) for row in rows]


def lease_next_endpoint_job(
    db_path: Path,
    *,
    device_id: str,
    lease_seconds: int = 60,
) -> EndpointJobRecord | None:
    init_db(db_path)
    now = _utc_now()
    lease_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id
            FROM endpoint_jobs
            WHERE device_id = ?
              AND (status = 'queued' OR (status = 'leased' AND lease_expires_at < ?))
            ORDER BY id ASC
            LIMIT 1
            """,
            (device_id, now),
        ).fetchone()
        if not row:
            return None
        job_id = int(row[0])
        conn.execute(
            """
            UPDATE endpoint_jobs
            SET status = 'leased', lease_expires_at = ?, updated_at = ?
            WHERE id = ? AND device_id = ?
            """,
            (lease_expires_at, now, job_id, device_id),
        )
        conn.commit()
    return get_endpoint_job(db_path, job_id)


def complete_endpoint_job(
    db_path: Path,
    *,
    device_id: str,
    job_id: int,
    status: str,
    result: dict[str, Any] | None = None,
    error_text: str = "",
) -> EndpointJobRecord | None:
    init_db(db_path)
    now = _utc_now()
    normalized_status = status if status in {"succeeded", "failed", "blocked"} else "failed"
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE endpoint_jobs
            SET status = ?, result_json = ?, error_text = ?, updated_at = ?, completed_at = ?
            WHERE id = ? AND device_id = ?
            """,
            (
                normalized_status,
                json.dumps(result or {}, ensure_ascii=True),
                error_text,
                now,
                now,
                job_id,
                device_id,
            ),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    return get_endpoint_job(db_path, job_id)


def log_task(
    db_path: Path,
    *,
    task_type: str,
    status: str,
    input_text: str = "",
    output_text: str = "",
    metadata: dict[str, Any] | None = None,
) -> int:
    init_db(db_path)
    now = _utc_now()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=True)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks (task_type, status, input_text, output_text, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_type, status, input_text, output_text, metadata_json, now, now),
        )
        conn.commit()
        return int(cursor.lastrowid)


def create_support_ticket(
    db_path: Path,
    *,
    title: str,
    description: str,
    source_text: str = "",
    metadata: dict[str, Any] | None = None,
) -> int:
    ticket_metadata = dict(metadata or {})
    ticket_metadata.update({"title": title, "description": description})
    return log_task(
        db_path,
        task_type="support_ticket",
        status="open",
        input_text=source_text,
        output_text=description,
        metadata=ticket_metadata,
    )


def update_task(
    db_path: Path,
    task_id: int,
    *,
    status: str | None = None,
    output_text: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    init_db(db_path)
    fields: list[str] = []
    values: list[Any] = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if output_text is not None:
        fields.append("output_text = ?")
        values.append(output_text)
    if metadata is not None:
        fields.append("metadata_json = ?")
        values.append(json.dumps(metadata, ensure_ascii=True))

    if not fields:
        return

    fields.append("updated_at = ?")
    values.append(_utc_now())
    values.append(task_id)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()


def list_tasks(db_path: Path, limit: int = 50) -> list[TaskRecord]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, task_type, status, input_text, output_text, metadata_json, created_at, updated_at
            FROM tasks
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    tasks: list[TaskRecord] = []
    for row in rows:
        tasks.append(
            TaskRecord(
                id=row[0],
                task_type=row[1],
                status=row[2],
                input_text=row[3],
                output_text=row[4],
                metadata=json.loads(row[5] or "{}"),
                created_at=row[6],
                updated_at=row[7],
            )
        )
    return tasks


def get_task(db_path: Path, task_id: int) -> TaskRecord | None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, task_type, status, input_text, output_text, metadata_json, created_at, updated_at
            FROM tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()

    if not row:
        return None
    return TaskRecord(
        id=row[0],
        task_type=row[1],
        status=row[2],
        input_text=row[3],
        output_text=row[4],
        metadata=json.loads(row[5] or "{}"),
        created_at=row[6],
        updated_at=row[7],
    )
