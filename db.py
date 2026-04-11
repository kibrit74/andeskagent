from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
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
        conn.commit()


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

