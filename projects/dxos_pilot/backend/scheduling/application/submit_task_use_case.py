"""用例：任务提交 / 取消。"""
from __future__ import annotations

import uuid
from datetime import datetime

from ..domain.entities import (
    InsufficientQuotaError,
    ModelNotFoundError,
    Task,
    TaskNotFoundError,
    TaskStatus,
    TenantNotFoundError,
)
from .ports import ModelCatalog, QuotaRepository, TaskRepository, TenantRepository


class SubmitTaskUseCase:
    """提交 GPU 推理任务：校验租户 → 校验模型 → 预扣显存 → 创建任务。"""

    def __init__(
        self,
        task_repo: TaskRepository,
        tenant_repo: TenantRepository,
        model_catalog: ModelCatalog,
        quota_repo: QuotaRepository,
    ):
        self._tasks = task_repo
        self._tenants = tenant_repo
        self._models = model_catalog
        self._quota = quota_repo

    def execute(
        self,
        tenant_id: str,
        model_name: str,
        vram_mb: int | None = None,
        priority: int = 0,
    ) -> Task:
        # 1. 租户必须存在且 active
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"租户 {tenant_id} 不存在")
        if tenant.status != "active":
            raise ValueError(f"租户 {tenant_id} 已禁用，不能提交任务")

        # 2. 模型必须在目录中
        spec = self._models.get_model(model_name)
        if spec is None:
            raise ModelNotFoundError(f"模型 {model_name} 不在目录中")

        # 3. 显存需求：调用方未指定时用模型规格
        if vram_mb is None:
            vram_mb = spec.vram_requirement_mb

        # 4. 预扣显存
        reservation = self._quota.reserve(tenant_id, vram_mb)

        # 5. 创建任务（pending）
        task = Task(
            task_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            model_name=model_name,
            vram_mb=vram_mb,
            priority=priority,
            status=TaskStatus.PENDING,
            reservation_id=reservation.reservation_id,
        )
        self._tasks.create(task)
        return task


class CancelTaskUseCase:
    """取消任务：仅 pending / queued / starting 状态可取消；释放预扣。"""

    def __init__(
        self,
        task_repo: TaskRepository,
        quota_repo: QuotaRepository,
        usage_repo=None,  # 可选：取消时也记录使用量
    ):
        self._tasks = task_repo
        self._quota = quota_repo
        self._usage = usage_repo

    def execute(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"任务 {task_id} 不存在")

        cancellable = (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.STARTING)
        if task.status not in cancellable:
            raise ValueError(
                f"任务 {task_id} 状态为 {task.status.value}，不可取消（仅 pending/queued/starting 可取消）"
            )

        task.transition_to(TaskStatus.CANCELLED)
        self._tasks.update(task)

        # 释放预扣
        if task.reservation_id:
            self._quota.release(task.reservation_id)

        # 记录使用量（如果 running 过）
        if self._usage and task.started_at is not None:
            duration = (datetime.now() - task.started_at).total_seconds()
            self._usage.record(
                __import__("scheduling.domain.entities", fromlist=["UsageRecord"]).UsageRecord(
                    task_id=task.task_id,
                    tenant_id=task.tenant_id,
                    gpu_index=task.gpu_index,
                    duration_seconds=duration,
                    vram_mb=task.vram_mb,
                    cost_points=duration * 0.01,
                )
            )

        return task
