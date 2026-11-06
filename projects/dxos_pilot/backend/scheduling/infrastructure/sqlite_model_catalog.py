"""适配器：基于 sqlite3 的模型目录实现。"""
from __future__ import annotations

import os
import sqlite3

from ..application.ports import ModelCatalog
from ..domain.entities import ModelSpec

DEFAULT_DB_PATH = "/ai/dxos_pilot/backend/scheduling/data/models.db"

_MODEL_DDL = """
CREATE TABLE IF NOT EXISTS models (
    model_name           TEXT PRIMARY KEY,
    vram_requirement_mb  INTEGER NOT NULL,
    supported_backends   TEXT NOT NULL DEFAULT '[]',
    min_gpu_count        INTEGER NOT NULL DEFAULT 1
);
"""


class SqliteModelCatalog(ModelCatalog):

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(_MODEL_DDL)
        conn.commit()
        return conn

    def get_model(self, model_name: str) -> ModelSpec | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM models WHERE model_name = ?", (model_name,)).fetchone()
            return self._row_to_spec(row) if row else None
        finally:
            conn.close()

    def list_models(self) -> list[ModelSpec]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM models ORDER BY model_name").fetchall()
            return [self._row_to_spec(r) for r in rows]
        finally:
            conn.close()

    def upsert(self, spec: ModelSpec) -> None:
        import json
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO models (model_name, vram_requirement_mb, supported_backends, min_gpu_count) "
                "VALUES (?, ?, ?, ?)",
                (spec.model_name, spec.vram_requirement_mb, json.dumps(spec.supported_backends), spec.min_gpu_count),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row_to_spec(row: sqlite3.Row) -> ModelSpec:
        import json
        backends = json.loads(row["supported_backends"]) if row["supported_backends"] else []
        return ModelSpec(
            model_name=row["model_name"],
            vram_requirement_mb=row["vram_requirement_mb"],
            supported_backends=backends,
            min_gpu_count=row["min_gpu_count"],
        )
