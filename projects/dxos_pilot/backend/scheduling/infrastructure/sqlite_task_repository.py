"""适配器：基于 sqlite3 的任务仓储实现。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from ..application.ports import TaskRepository
from ..domain.entities import Task, TaskStatus

DEFAULT_DB_PATH = "/ai/dxos_pilot/backend/scheduling/data/tasks.db"

_TASK_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id        TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    model_name     TEXT NOT NULL,
    status         TEXT NOT NULL,
    gpu_index      INTEGER,
    vram_mb        INTEGER NOT NULL DEFAULT 0,
    priority       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    reservation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_tenant ON tasks (tenant_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
"""


class SqliteTaskRepository(TaskRepository):

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_TASK_DDL)
        conn.commit()
        return conn

    def create(self, task: Task) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO tasks (task_id, tenant_id, model_name, status, gpu_index, "
                "vram_mb, priority, created_at, started_at, finished_at, reservation_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.task_id, task.tenant_id, task.model_name, task.status.value,
                    task.gpu_index, task.vram_mb, task.priority,
                    task.created_at.isoformat(),
                    task.started_at.isoformat() if task.started_at else None,
                    task.finished_at.isoformat() if task.finished_at else None,
                    task.reservation_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get(self, task_id: str) -> Task | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return self._row_to_task(row) if row else None
        finally:
            conn.close()

    def list_by_tenant(self, tenant_id: str) -> list[Task]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE tenant_id = ? ORDER BY created_at DESC", (tenant_id,)
            ).fetchall()
            return [self._row_to_task(r) for r in rows]
        finally:
            conn.close()

    def list_all(self) -> list[Task]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 500").fetchall()
            return [self._row_to_task(r) for r in rows]
        finally:
            conn.close()

    def list_by_status(self, status: TaskStatus) -> list[Task]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at ASC", (status.value,)
            ).fetchall()
            return [self._row_to_task(r) for r in rows]
        finally:
            conn.close()

    def update(self, task: Task) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE tasks SET status = ?, gpu_index = ?, started_at = ?, finished_at = ? "
                "WHERE task_id = ?",
                (
                    task.status.value, task.gpu_index,
                    task.started_at.isoformat() if task.started_at else None,
                    task.finished_at.isoformat() if task.finished_at else None,
                    task.task_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def release_gpu_allocation(self, task_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE tasks SET gpu_index = NULL WHERE task_id = ?", (task_id,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            task_id=row["task_id"],
            tenant_id=row["tenant_id"],
            model_name=row["model_name"],
            status=TaskStatus(row["status"]),
            gpu_index=row["gpu_index"],
            vram_mb=row["vram_mb"],
            priority=row["priority"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            reservation_id=row["reservation_id"],
        )
