"""适配器：基于标准库 sqlite3 的 GPU 额度仓储实现。

依赖向内：实现应用层端口 QuotaRepository（from ..application.ports import ...），
数据库 / 表结构是持久化细节，绝不反向污染领域实体或应用层。
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime

from ..application.ports import QuotaRepository
from ..domain.entities import (
    ComputeQuota,
    GpuReservation,
    InsufficientQuotaError,
)

# 默认数据库文件位置（目录在 open 时按需创建）
DEFAULT_DB_PATH = "/ai/dxos_pilot/backend/scheduling/data/quota.db"

_QUOTA_DDL = """
CREATE TABLE IF NOT EXISTS quota (
    tenant_id      TEXT PRIMARY KEY,
    max_concurrent INTEGER NOT NULL CHECK (max_concurrent >= 0),
    max_vram_mb    INTEGER NOT NULL CHECK (max_vram_mb >= 0)
);
"""

_RESERVATION_DDL = """
CREATE TABLE IF NOT EXISTS reservation (
    reservation_id TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    vram_mb        INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    released       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reservation_tenant
    ON reservation (tenant_id, released);
"""


class SqliteQuotaRepository(QuotaRepository):
    """用 sqlite3 落地的 QuotaRepository。

    表结构与 GpuReservation / ComputeQuota 一一对应，但业务不变量校验仍交给
    领域实体；本类只负责「读写 + 并发 / 显存上限校验」。
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """打开连接并确保目录 / 表存在（首次初始化建表）。"""
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(_QUOTA_DDL)
        conn.executescript(_RESERVATION_DDL)
        conn.commit()
        return conn

    def get_quota(self, tenant_id: str) -> ComputeQuota | None:
        """返回租户 GPU 额度；租户未配置时返回 None。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT max_concurrent, max_vram_mb FROM quota WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            if row is None:
                return None
            return ComputeQuota(
                tenant_id=tenant_id,
                max_concurrent=int(row[0]),
                max_vram_mb=int(row[1]),
            )
        finally:
            conn.close()

    def reserve(self, tenant_id: str, vram_mb: int) -> GpuReservation:
        """为租户预扣 vram_mb 显存；并发或显存超限时抛 InsufficientQuotaError。"""
        if vram_mb <= 0:
            raise ValueError(f"vram_mb 必须 > 0，实际为 {vram_mb}")

        conn = self._connect()
        try:
            quota_row = conn.execute(
                "SELECT max_concurrent, max_vram_mb FROM quota WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            if quota_row is None:
                raise InsufficientQuotaError(f"租户 {tenant_id} 未配置 GPU 额度")
            max_concurrent = int(quota_row[0])
            max_vram_mb = int(quota_row[1])

            stat = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(vram_mb), 0) "
                "FROM reservation WHERE tenant_id = ? AND released = 0",
                (tenant_id,),
            ).fetchone()
            active_count = int(stat[0])
            used_vram = int(stat[1])

            if active_count >= max_concurrent:
                raise InsufficientQuotaError(
                    f"租户 {tenant_id} 并发额度已满：上限 {max_concurrent}，当前已用 {active_count}"
                )
            if used_vram + vram_mb > max_vram_mb:
                raise InsufficientQuotaError(
                    f"租户 {tenant_id} 显存额度不足：需 {vram_mb}MB，已用 {used_vram}MB，上限 {max_vram_mb}MB"
                )

            reservation_id = str(uuid.uuid4())
            created_at = datetime.now()
            conn.execute(
                "INSERT INTO reservation (reservation_id, tenant_id, vram_mb, created_at, released) "
                "VALUES (?, ?, ?, ?, 0)",
                (reservation_id, tenant_id, vram_mb, created_at.isoformat()),
            )
            conn.commit()
            return GpuReservation(
                reservation_id=reservation_id,
                tenant_id=tenant_id,
                vram_mb=vram_mb,
                created_at=created_at,
            )
        finally:
            conn.close()

    def release(self, reservation_id: str) -> bool:
        """释放指定预扣，归还租户额度。幂等：重复释放返回 False。"""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE reservation SET released = 1 WHERE reservation_id = ? AND released = 0",
                (reservation_id,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
