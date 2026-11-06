"""API 路由：GPU 额度预扣 / 释放。

职责：HTTP DTO ↔ 领域对象转换 + 调用应用层用例。
依赖向内：本模块只调用 scheduling 包对外暴露的组合根工厂，不直接依赖仓储实现。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scheduling import build_release_use_case, build_reserve_use_case
from scheduling.domain.entities import InsufficientQuotaError

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


class GpuReserveRequest(BaseModel):
    tenant_id: str
    vram_mb: int


@router.post("/gpu/reserve")
def reserve_gpu(req: GpuReserveRequest) -> dict:
    """为租户预扣显存；额度不足时返回 409。"""
    use_case = build_reserve_use_case()
    try:
        reservation = use_case.run(req.tenant_id, req.vram_mb)
    except InsufficientQuotaError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "reservation_id": reservation.reservation_id,
        "tenant_id": reservation.tenant_id,
        "vram_mb": reservation.vram_mb,
        "created_at": reservation.created_at.isoformat(),
    }


@router.post("/gpu/{reservation_id}/release")
def release_gpu(reservation_id: str) -> dict:
    """释放预扣（幂等）。返回是否实际释放了。"""
    use_case = build_release_use_case()
    actually_released = use_case.execute(reservation_id)
    return {
        "reservation_id": reservation_id,
        "released": actually_released,
    }
