"""API 路由：计费汇总查询。

职责：HTTP DTO 转换 + 调用 GetBillingSummaryUseCase。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from scheduling import build_billing_use_cases
from scheduling.domain.entities import TenantNotFoundError

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/summary")
def billing_summary(tenant_id: str) -> dict:
    get_summary_uc, _ = build_billing_use_cases()
    try:
        return get_summary_uc.execute(tenant_id)
    except TenantNotFoundError as e:
        raise HTTPException(404, str(e))
