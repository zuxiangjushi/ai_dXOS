"""适配器：基于 sqlite3 的 Worker 心跳存储实现。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from ..application.ports import HeartbeatStore
from ..domain.entities import WorkerHeartbeat

DEFAULT_DB_PATH = "/ai/dxos_pilot/backend/scheduling/data/heartbeats.db"

_HB_DDL = """
CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id        TEXT PRIMARY KEY,
    last_heartbeat_at TEXT NOT NULL,
    gpu_indexes      TEXT NOT NULL DEFAULT '[]',
    online           INTEGER NOT NULL DEFAULT 1
);
"""


class SqliteHeartbeatStore(HeartbeatStore):

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_HB_DDL)
        conn.commit()
        return conn

    def upsert(self, worker_id: str, gpu_indexes: list[int]) -> None:
        import json
        now = datetime.now().isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO worker_heartbeats (worker_id, last_heartbeat_at, gpu_indexes, online) "
                "VALUES (?, ?, ?, 1)",
                (worker_id, now, json.dumps(gpu_indexes)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_all(self) -> dict[str, WorkerHeartbeat]:
        import json
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM worker_heartbeats").fetchall()
            result = {}
            for r in rows:
                result[r["worker_id"]] = WorkerHeartbeat(
                    worker_id=r["worker_id"],
                    last_heartbeat_at=datetime.fromisoformat(r["last_heartbeat_at"]),
                    gpu_indexes=json.loads(r["gpu_indexes"]) if r["gpu_indexes"] else [],
                )
            return result
        finally:
            conn.close()

    def mark_offline(self, worker_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE worker_heartbeats SET online = 0 WHERE worker_id = ?", (worker_id,))
            conn.commit()
        finally:
            conn.close()
