"""用例：计费汇总查询。"""
from __future__ import annotations

from ..domain.entities import TenantNotFoundError
from .ports import TenantRepository, UsageRepository


class GetBillingSummaryUseCase:
    """按租户汇总使用量 / 费用。"""

    def __init__(self, usage_repo: UsageRepository, tenant_repo: TenantRepository):
        self._usage = usage_repo
        self._tenants = tenant_repo

    def execute(self, tenant_id: str) -> dict:
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"租户 {tenant_id} 不存在")
        return self._usage.summarize(tenant_id)


class RecordUsageUseCase:
    """任务进入终态（completed/failed）时记录使用量。"""

    def __init__(self, usage_repo: UsageRepository):
        self._usage = usage_repo

    def execute(self, task_id: str, tenant_id: str, gpu_index: int | None,
                duration_seconds: float, vram_mb: int) -> None:
        from ..domain.entities import UsageRecord
        self._usage.record(UsageRecord(
            task_id=task_id,
            tenant_id=tenant_id,
            gpu_index=gpu_index,
            duration_seconds=duration_seconds,
            vram_mb=vram_mb,
            cost_points=duration_seconds * 0.01,  # 简化：每秒 0.01 点
        ))
