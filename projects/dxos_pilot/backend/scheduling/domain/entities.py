"""领域层实体与业务异常 —— 调度 / 租户 / 任务 / 模型 / 计费 / 心跳。

纯领域模型：只依赖 Python 标准库，禁止 import 框架、驱动或仓储实现。
实体用 dataclass 表达业务不变量，在 __post_init__ 中做入参校验；
业务规则（状态迁移、额度检查等）封装为实体方法，异常为业务语义异常。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class InsufficientQuotaError(Exception):
    """租户并发 / 显存额度不足（409）。"""


class IllegalStateTransitionError(Exception):
    """任务状态机非法迁移（409）。"""


class TenantNotFoundError(Exception):
    """租户不存在（404）。"""


class TaskNotFoundError(Exception):
    """任务不存在（404）。"""


class ModelNotFoundError(Exception):
    """模型不在目录中（404）。"""


# ─── 租户 ───────────────────────────────────────────────────────────────

@dataclass
class Tenant:
    """租户：多租户隔离的基本单元。"""
    tenant_id: str
    name: str
    status: str = "active"          # active | disabled
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("tenant_id 不能为空")
        if self.status not in ("active", "disabled"):
            raise ValueError(f"tenant status 必须为 active/disabled，实际为 {self.status}")


# ─── GPU 额度与预扣（原有，保留） ───────────────────────────────────────

@dataclass
class ComputeQuota:
    """租户 GPU 使用额度（并发任务数上限 + 显存 MB 上限）。"""
    tenant_id: str
    max_concurrent: int
    max_vram_mb: int

    def __post_init__(self) -> None:
        if self.max_concurrent < 0 or self.max_vram_mb < 0:
            raise ValueError("额度上限不能为负")


@dataclass
class GpuReservation:
    """GPU 显存预扣凭证：预扣成功后的收据，后续据此释放。"""
    reservation_id: str
    tenant_id: str
    vram_mb: int
    created_at: datetime

    def __post_init__(self) -> None:
        if self.vram_mb <= 0:
            raise ValueError(f"vram_mb 必须 > 0，实际为 {self.vram_mb}")


# ─── 模型目录 ────────────────────────────────────────────────────────────

@dataclass
class ModelSpec:
    """模型规格：显存需求、支持的后端、最少 GPU 数。"""
    model_name: str
    vram_requirement_mb: int
    supported_backends: list[str] = field(default_factory=list)
    min_gpu_count: int = 1

    def __post_init__(self) -> None:
        if not self.model_name or not self.model_name.strip():
            raise ValueError("model_name 不能为空")
        if self.vram_requirement_mb <= 0:
            raise ValueError("vram_requirement_mb 必须 > 0")
        if self.min_gpu_count < 1:
            raise ValueError("min_gpu_count 必须 >= 1")


# ─── 任务 ───────────────────────────────────────────────────────────────

class TaskStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 合法状态迁移表：当前状态 -> 允许迁移到的状态集合
_VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING:   {TaskStatus.QUEUED, TaskStatus.CANCELLED},
    TaskStatus.QUEUED:    {TaskStatus.STARTING, TaskStatus.CANCELLED},
    TaskStatus.STARTING:  {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.QUEUED},
    TaskStatus.RUNNING:   {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED:    set(),
    TaskStatus.CANCELLED: set(),
}


@dataclass
class Task:
    """GPU 推理任务：从提交到完成的完整生命周期。"""
    task_id: str
    tenant_id: str
    model_name: str
    status: TaskStatus = TaskStatus.PENDING
    gpu_index: int | None = None
    vram_mb: int = 0
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reservation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id 不能为空")
        if not self.tenant_id:
            raise ValueError("tenant_id 不能为空")
        if not self.model_name:
            raise ValueError("model_name 不能为空")
        if self.vram_mb < 0:
            raise ValueError("vram_mb 不能为负")

    def transition_to(self, new_status: TaskStatus) -> None:
        """校验并执行状态迁移；非法迁移抛 IllegalStateTransitionError。"""
        allowed = _VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise IllegalStateTransitionError(
                f"任务 {self.task_id} 不允许从 {self.status.value} 迁移到 {new_status.value}"
            )
        self.status = new_status
        if new_status in (TaskStatus.RUNNING,) and self.started_at is None:
            self.started_at = datetime.now()
        if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.finished_at = datetime.now()


# ─── GPU 状态 ───────────────────────────────────────────────────────────

@dataclass
class GpuStatus:
    """单卡 GPU 当前状态。"""
    gpu_index: int
    free_vram_mb: int
    in_use_by: list[str] = field(default_factory=list)  # task_id 列表


# ─── 使用记录 / 计费 ────────────────────────────────────────────────────

@dataclass
class UsageRecord:
    """单次任务完成后的使用量记录。"""
    task_id: str
    tenant_id: str
    gpu_index: int | None
    duration_seconds: float
    vram_mb: int
    cost_points: float = 0.0
    recorded_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds 不能为负")


# ─── Worker 心跳 ────────────────────────────────────────────────────────

@dataclass
class WorkerHeartbeat:
    """Worker 心跳记录。"""
    worker_id: str
    last_heartbeat_at: datetime
    gpu_indexes: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise ValueError("worker_id 不能为空")
