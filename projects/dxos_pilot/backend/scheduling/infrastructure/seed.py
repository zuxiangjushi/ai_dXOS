"""种子数据初始化：确保 demo-tenant 和 qwen38_27b 存在（幂等）。

在 main.py 启动时调用一次。不覆盖已有数据，只 INSERT OR IGNORE。
"""
from __future__ import annotations

import json
import os
import sqlite3


def seed_all(data_dir: str = "/ai/dxos_pilot/backend/scheduling/data") -> None:
    """初始化所有种子数据（幂等）。"""
    os.makedirs(data_dir, exist_ok=True)

    # 1. 租户
    tenant_db = os.path.join(data_dir, "tenants.db")
    conn = sqlite3.connect(tenant_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id  TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
            created_at TEXT NOT NULL
        )
    """)
    from datetime import datetime
    conn.execute(
        "INSERT OR IGNORE INTO tenants (tenant_id, name, status, created_at) VALUES (?, ?, 'active', ?)",
        ("demo-tenant", "演示租户", datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    # 2. 额度
    quota_db = os.path.join(data_dir, "quota.db")
    conn = sqlite3.connect(quota_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quota (
            tenant_id      TEXT PRIMARY KEY,
            max_concurrent INTEGER NOT NULL CHECK (max_concurrent >= 0),
            max_vram_mb    INTEGER NOT NULL CHECK (max_vram_mb >= 0)
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO quota (tenant_id, max_concurrent, max_vram_mb) VALUES (?, ?, ?)",
        ("demo-tenant", 4, 8192),
    )
    conn.commit()
    conn.close()

    # 3. 模型
    model_db = os.path.join(data_dir, "models.db")
    conn = sqlite3.connect(model_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS models (
            model_name           TEXT PRIMARY KEY,
            vram_requirement_mb  INTEGER NOT NULL,
            supported_backends   TEXT NOT NULL DEFAULT '[]',
            min_gpu_count        INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO models (model_name, vram_requirement_mb, supported_backends, min_gpu_count) "
        "VALUES (?, ?, ?, ?)",
        ("qwen38_27b", 8192, json.dumps(["sglang", "vllm"]), 1),
    )
    conn.commit()
    conn.close()
