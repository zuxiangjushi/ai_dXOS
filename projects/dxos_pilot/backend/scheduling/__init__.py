"""scheduling 包组合根：依赖注入装配点。

本模块是系统内唯一允许「同时认识领域 / 应用 / 基础设施」三层的装配代码。
新增用例时，在此处添加对应的 build_* 工厂函数。
"""
from __future__ import annotations

from .application.dispatch_loop_use_case import DispatchLoopUseCase, HeartbeatChecker
from .application.billing_use_case import GetBillingSummaryUseCase, RecordUsageUseCase
from .application.manage_tenant_use_case import CreateTenantUseCase, DeleteTenantUseCase, UpdateTenantStatusUseCase
from .application.release_gpu_use_case import ReleaseGpuUseCase
from .application.reserve_gpu_use_case import ReserveGpuUseCase
from .application.submit_task_use_case import CancelTaskUseCase, SubmitTaskUseCase
from .domain.strategies import FIFOStrategy, PriorityStrategy
from .infrastructure.sqlite_heartbeat_store import SqliteHeartbeatStore
from .infrastructure.sqlite_model_catalog import SqliteModelCatalog
from .infrastructure.sqlite_quota_repository import SqliteQuotaRepository
from .infrastructure.sqlite_task_repository import SqliteTaskRepository
from .infrastructure.sqlite_tenant_repository import SqliteTenantRepository
from .infrastructure.sqlite_usage_repository import SqliteUsageRepository


def build_reserve_use_case() -> ReserveGpuUseCase:
    return ReserveGpuUseCase(SqliteQuotaRepository())


def build_release_use_case() -> ReleaseGpuUseCase:
    return ReleaseGpuUseCase(quota_repo=SqliteQuotaRepository())


def build_tenant_use_cases() -> tuple[CreateTenantUseCase, UpdateTenantStatusUseCase, DeleteTenantUseCase]:
    repo = SqliteTenantRepository()
    return (
        CreateTenantUseCase(repo),
        UpdateTenantStatusUseCase(repo),
        DeleteTenantUseCase(repo),
    )


def build_model_catalog() -> SqliteModelCatalog:
    return SqliteModelCatalog()


def build_submit_use_case() -> SubmitTaskUseCase:
    return SubmitTaskUseCase(
        task_repo=SqliteTaskRepository(),
        tenant_repo=SqliteTenantRepository(),
        model_catalog=SqliteModelCatalog(),
        quota_repo=SqliteQuotaRepository(),
    )


def build_cancel_use_case() -> CancelTaskUseCase:
    return CancelTaskUseCase(
        task_repo=SqliteTaskRepository(),
        quota_repo=SqliteQuotaRepository(),
        usage_repo=SqliteUsageRepository(),
    )


def build_billing_use_cases() -> tuple[GetBillingSummaryUseCase, RecordUsageUseCase]:
    usage = SqliteUsageRepository()
    return (
        GetBillingSummaryUseCase(usage_repo=usage, tenant_repo=SqliteTenantRepository()),
        RecordUsageUseCase(usage_repo=usage),
    )


def build_dispatch_loop(strategy: str = "fifo", num_gpus: int = 4,
                        total_vram_mb: int = 24576) -> DispatchLoopUseCase:
    """构建调度循环。strategy: 'fifo' | 'priority'"""
    task_repo = SqliteTaskRepository()
    hb_store = SqliteHeartbeatStore()
    strategy_impl = FIFOStrategy() if strategy == "fifo" else PriorityStrategy()
    hb_checker = HeartbeatChecker(heartbeat_store=hb_store, task_repo=task_repo)
    return DispatchLoopUseCase(
        task_repo=task_repo,
        strategy=strategy_impl,
        heartbeat_checker=hb_checker,
        usage_repo=SqliteUsageRepository(),
        quota_repo=SqliteQuotaRepository(),
        num_gpus=num_gpus,
        total_vram_mb_per_gpu=total_vram_mb,
    )
