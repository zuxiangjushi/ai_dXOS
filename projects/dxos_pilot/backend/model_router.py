"""API 路由：模型目录查询。

职责：HTTP DTO 转换 + 调用 ModelCatalog 端口。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from scheduling import build_model_catalog

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
def list_models() -> list[dict]:
    catalog = build_model_catalog()
    models = catalog.list_models()
    return [
        {
            "model_name": m.model_name,
            "vram_requirement_mb": m.vram_requirement_mb,
            "supported_backends": m.supported_backends,
            "min_gpu_count": m.min_gpu_count,
        }
        for m in models
    ]


@router.get("/{name}")
def get_model(name: str) -> dict:
    catalog = build_model_catalog()
    m = catalog.get_model(name)
    if m is None:
        raise HTTPException(404, f"模型 {name} 不存在")
    return {
        "model_name": m.model_name,
        "vram_requirement_mb": m.vram_requirement_mb,
        "supported_backends": m.supported_backends,
        "min_gpu_count": m.min_gpu_count,
    }
