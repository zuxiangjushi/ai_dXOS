"""适配器：基于 sqlite3 的租户仓储实现。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from ..application.ports import TenantRepository
from ..domain.entities import Tenant

DEFAULT_DB_PATH = "/ai/dxos_pilot/backend/scheduling/data/tenants.db"

_TENANT_DDL = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at TEXT NOT NULL
);
"""


class SqliteTenantRepository(TenantRepository):

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(_TENANT_DDL)
        conn.commit()
        return conn

    def create(self, tenant: Tenant) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO tenants (tenant_id, name, status, created_at) VALUES (?, ?, ?, ?)",
                (tenant.tenant_id, tenant.name, tenant.status, tenant.created_at.isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"租户 {tenant.tenant_id} 已存在")
        finally:
            conn.close()

    def get(self, tenant_id: str) -> Tenant | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_tenant(row)
        finally:
            conn.close()

    def list_all(self) -> list[Tenant]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM tenants ORDER BY created_at").fetchall()
            return [self._row_to_tenant(r) for r in rows]
        finally:
            conn.close()

    def update_status(self, tenant_id: str, status: str) -> None:
        if status not in ("active", "disabled"):
            raise ValueError(f"status 必须为 active/disabled，实际为 {status}")
        conn = self._connect()
        try:
            cur = conn.execute("UPDATE tenants SET status = ? WHERE tenant_id = ?", (status, tenant_id))
            conn.commit()
            if cur.rowcount == 0:
                raise ValueError(f"租户 {tenant_id} 不存在")
        finally:
            conn.close()

    def delete(self, tenant_id: str) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM tenants WHERE tenant_id = ?", (tenant_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def count_active_tasks(self, tenant_id: str) -> int:
        """跨库查询任务数（任务表在 tasks.db）。"""
        task_db = os.path.join(os.path.dirname(self._db_path), "tasks.db")
        if not os.path.exists(task_db):
            return 0
        conn = sqlite3.connect(task_db)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE tenant_id = ? AND status IN ('pending','queued','starting','running')",
                (tenant_id,),
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()

    def count_active_reservations(self, tenant_id: str) -> int:
        """跨库查询预扣数（预扣表在 quota.db）。"""
        quota_db = os.path.join(os.path.dirname(self._db_path), "quota.db")
        if not os.path.exists(quota_db):
            return 0
        conn = sqlite3.connect(quota_db)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM reservation WHERE tenant_id = ? AND released = 0",
                (tenant_id,),
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()

    @staticmethod
    def _row_to_tenant(row: sqlite3.Row) -> Tenant:
        return Tenant(
            tenant_id=row["tenant_id"],
            name=row["name"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
