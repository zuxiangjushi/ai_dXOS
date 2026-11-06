"""应用层端口（抽象接口）—— 仓储 / 目录 / 策略的抽象契约。

领域层不依赖任何具体实现；本文件定义应用层需要的抽象端口，
基础设施层（SQLite 等）负责实现这些接口。
依赖向内：本文件只 import 领域层。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.entities import (
    ComputeQuota,
    GpuReservation,
    GpuStatus,
    ModelSpec,
    Task,
    TaskStatus,
    Tenant,
    UsageRecord,
)


# ─── GPU 额度端口（原有，保留） ────────────────────────────────────────

class QuotaRepository(ABC):
    """租户 GPU 额度的读写端口。"""

    @abstractmethod
    def get_quota(self, tenant_id: str) -> ComputeQuota | None: ...

    @abstractmethod
    def reserve(self, tenant_id: str, vram_mb: int) -> GpuReservation: ...

    @abstractmethod
    def release(self, reservation_id: str) -> bool:
        """释放预扣，返回是否实际释放了（幂等：重复调用返回 False）。"""


# ─── 租户端口 ──────────────────────────────────────────────────────────

class TenantRepository(ABC):
    """租户 CRUD 端口。"""

    @abstractmethod
    def create(self, tenant: Tenant) -> None: ...

    @abstractmethod
    def get(self, tenant_id: str) -> Tenant | None: ...

    @abstractmethod
    def list_all(self) -> list[Tenant]: ...

    @abstractmethod
    def update_status(self, tenant_id: str, status: str) -> None: ...

    @abstractmethod
    def delete(self, tenant_id: str) -> bool: ...

    @abstractmethod
    def count_active_tasks(self, tenant_id: str) -> int:
        """统计该租户非终态任务数（用于删除前校验）。"""

    @abstractmethod
    def count_active_reservations(self, tenant_id: str) -> int:
        """统计该租户未释放的预扣数（用于删除前校验）。"""


# ─── 模型目录端口 ──────────────────────────────────────────────────────

class ModelCatalog(ABC):
    """模型规格查询端口。"""

    @abstractmethod
    def get_model(self, model_name: str) -> ModelSpec | None: ...

    @abstractmethod
    def list_models(self) -> list[ModelSpec]: ...

    @abstractmethod
    def upsert(self, spec: ModelSpec) -> None: ...


# ─── 任务端口 ──────────────────────────────────────────────────────────

class TaskRepository(ABC):
    """任务生命周期持久化端口。"""

    @abstractmethod
    def create(self, task: Task) -> None: ...

    @abstractmethod
    def get(self, task_id: str) -> Task | None: ...

    @abstractmethod
    def list_by_tenant(self, tenant_id: str) -> list[Task]: ...

    @abstractmethod
    def list_all(self) -> list[Task]: ...

    @abstractmethod
    def list_by_status(self, status: TaskStatus) -> list[Task]: ...

    @abstractmethod
    def update(self, task: Task) -> None:
        """全量更新任务字段（status / gpu_index / started_at / finished_at）。"""

    @abstractmethod
    def release_gpu_allocation(self, task_id: str) -> None:
        """将任务的 gpu_index 置回 None（worker 离线时回退 queued 用）。"""


# ─── 使用量 / 计费端口 ─────────────────────────────────────────────────

class UsageRepository(ABC):
    """使用量记录与汇总端口。"""

    @abstractmethod
    def record(self, record: UsageRecord) -> None: ...

    @abstractmethod
    def list_by_tenant(self, tenant_id: str) -> list[UsageRecord]: ...

    @abstractmethod
    def summarize(self, tenant_id: str) -> dict:
        """返回 {tenant_id, total_duration_seconds, total_vram_mb_hours, total_cost_points, task_count}"""


# ─── Worker 心跳端口 ──────────────────────────────────────────────────

class HeartbeatStore(ABC):
    """Worker 心跳记录端口。"""

    @abstractmethod
    def upsert(self, worker_id: str, gpu_indexes: list[int]) -> None: ...

    @abstractmethod
    def get_all(self) -> dict[str, "WorkerHeartbeat"]: ...

    @abstractmethod
    def mark_offline(self, worker_id: str) -> None: ...
