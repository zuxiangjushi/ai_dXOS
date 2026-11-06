"""适配器：基于 sqlite3 的使用量 / 计费仓储实现。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from ..application.ports import UsageRepository
from ..domain.entities import UsageRecord

DEFAULT_DB_PATH = "/ai/dxos_pilot/backend/scheduling/data/usage.db"

_USAGE_DDL = """
CREATE TABLE IF NOT EXISTS usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id           TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    gpu_index         INTEGER,
    duration_seconds  REAL NOT NULL,
    vram_mb           INTEGER NOT NULL,
    cost_points       REAL NOT NULL DEFAULT 0,
    recorded_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_tenant ON usage (tenant_id);
"""


class SqliteUsageRepository(UsageRepository):

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_USAGE_DDL)
        conn.commit()
        return conn

    def record(self, record: UsageRecord) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO usage (task_id, tenant_id, gpu_index, duration_seconds, vram_mb, cost_points, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.task_id, record.tenant_id, record.gpu_index,
                    record.duration_seconds, record.vram_mb, record.cost_points,
                    record.recorded_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_by_tenant(self, tenant_id: str) -> list[UsageRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM usage WHERE tenant_id = ? ORDER BY recorded_at DESC", (tenant_id,)
            ).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()

    def summarize(self, tenant_id: str) -> dict:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt, "
                "COALESCE(SUM(duration_seconds), 0) as total_dur, "
                "COALESCE(SUM(vram_mb * duration_seconds / 3600.0), 0) as total_vram_hours, "
                "COALESCE(SUM(cost_points), 0) as total_cost "
                "FROM usage WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            return {
                "tenant_id": tenant_id,
                "task_count": int(row["cnt"]),
                "total_duration_seconds": round(float(row["total_dur"]), 2),
                "total_vram_mb_hours": round(float(row["total_vram_hours"]), 4),
                "total_cost_points": round(float(row["total_cost"]), 4),
            }
        finally:
            conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> UsageRecord:
        return UsageRecord(
            task_id=row["task_id"],
            tenant_id=row["tenant_id"],
            gpu_index=row["gpu_index"],
            duration_seconds=row["duration_seconds"],
            vram_mb=row["vram_mb"],
            cost_points=row["cost_points"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
        )
