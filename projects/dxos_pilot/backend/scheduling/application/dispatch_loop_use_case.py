"""用例：调度循环 —— 每 tick 分配 GPU、处理心跳、回收超时任务。

依赖向内：只 import 领域实体 + 应用层端口。
由 main.py 的 asyncio 后台任务驱动，每 2s 调一次 tick()。
"""
from __future__ import annotations

import logging
from datetime import datetime

from ..domain.entities import (
    GpuStatus,
    Task,
    TaskStatus,
    UsageRecord,
    WorkerHeartbeat,
)
from ..domain.strategies import SchedulingStrategy
from .ports import (
    HeartbeatStore,
    QuotaRepository,
    TaskRepository,
    UsageRepository,
)

logger = logging.getLogger("scheduling.dispatch")

STALE_WORKER_THRESHOLD_SECONDS = 30
STALE_TASK_THRESHOLD_SECONDS = 300  # running 超过 5 分钟视为卡死


class HeartbeatChecker:
    """检测 stale worker：超过阈值无心跳 → 标记离线，释放其 GPU 上的任务回 queued。"""

    def __init__(
        self,
        heartbeat_store: HeartbeatStore,
        task_repo: TaskRepository,
        threshold_seconds: int = STALE_WORKER_THRESHOLD_SECONDS,
    ):
        self._hb = heartbeat_store
        self._tasks = task_repo
        self._threshold = threshold_seconds

    def check(self) -> list[str]:
        """返回本轮被标记离线的 worker_id 列表。"""
        now = datetime.now()
        stale: list[str] = []
        for worker_id, hb in self._hb.get_all().items():
            age = (now - hb.last_heartbeat_at).total_seconds()
            if age > self._threshold:
                if not self._is_gpu_in_use_by_others(hb):
                    self._hb.mark_offline(worker_id)
                    stale.append(worker_id)
                    # 该 worker 独占的 GPU 上的 running 任务回退 queued
                    for gpu_idx in hb.gpu_indexes:
                        self._evict_tasks_on_gpu(gpu_idx)
        return stale

    def _is_gpu_in_use_by_others(self, hb: WorkerHeartbeat) -> bool:
        """判断 worker 持有的 GPU 是否同时被其他在线 worker 持有。

        任一 GPU 与其他 worker 重叠 → 视为共持卡，不自动下线。
        """
        all_hbs = self._hb.get_all()
        for gpu_idx in hb.gpu_indexes:
            for other_id, other_hb in all_hbs.items():
                if other_id == hb.worker_id:
                    continue
                if gpu_idx in other_hb.gpu_indexes:
                    return True
        return False

    def _evict_tasks_on_gpu(self, gpu_index: int) -> None:
        """将指定 GPU 上 running/starting 的任务回退 queued 并释放 GPU 分配。"""
        for status in (TaskStatus.RUNNING, TaskStatus.STARTING):
            for task in self._tasks.list_by_status(status):
                if task.gpu_index == gpu_index:
                    task.gpu_index = None
                    task.status = TaskStatus.QUEUED
                    task.started_at = None
                    self._tasks.update(task)
                    logger.warning(
                        "worker 离线，任务 %s (GPU %d) 回退 queued", task.task_id, gpu_index
                    )


class DispatchLoopUseCase:
    """调度主循环：心跳检查 → 回收超时任务 → 选任务分配 GPU。"""

    def __init__(
        self,
        task_repo: TaskRepository,
        strategy: SchedulingStrategy,
        heartbeat_checker: HeartbeatChecker | None = None,
        usage_repo: UsageRepository | None = None,
        quota_repo: QuotaRepository | None = None,
        num_gpus: int = 4,
        total_vram_mb_per_gpu: int = 24576,  # 3090 = 24GB
    ):
        self._tasks = task_repo
        self._strategy = strategy
        self._hb_checker = heartbeat_checker
        self._usage = usage_repo
        self._quota = quota_repo
        self._num_gpus = num_gpus
        self._total_vram = total_vram_mb_per_gpu

    def _build_gpu_status(self) -> list[GpuStatus]:
        """从心跳注册表推断 GPU 总数，再聚合 running/starting 任务的已用显存。

        规则：
        - 总卡数 = 所有在线 worker 上报 gpu_indexes 的最大值 + 1；
          无任何在线 worker 时回退到构造参数 num_gpus。
        - 单卡容量：当前心跳协议未上报容量字段，统一用构造参数
          total_vram_mb_per_gpu。待协议扩展后改为按卡取 max(上报值)。
        """
        all_hbs = self._hb_checker._hb.get_all() if self._hb_checker else {}
        reported = sum((h.gpu_indexes for h in all_hbs.values()), [])
        total = (max(reported) + 1) if reported else self._num_gpus
        vram_map = {g: self._total_vram for g in range(total)}

        # 聚合已用显存
        used: dict[int, tuple[int, list[str]]] = {}
        for status in (TaskStatus.RUNNING, TaskStatus.STARTING):
            for task in self._tasks.list_by_status(status):
                if task.gpu_index is not None:
                    v, ids = used.get(task.gpu_index, (0, []))
                    used[task.gpu_index] = (v + task.vram_mb, ids + [task.task_id])

        gpus = []
        for i in range(total):
            v, ids = used.get(i, (0, []))
            gpus.append(GpuStatus(gpu_index=i, free_vram_mb=vram_map[i] - v, in_use_by=ids))
        return gpus

    def _reap_stale_tasks(self) -> None:
        """running 超过阈值的任务标记 failed 并释放资源。"""
        now = datetime.now()
        for task in self._tasks.list_by_status(TaskStatus.RUNNING):
            if task.started_at is not None:
                age = (now - task.started_at).total_seconds()
                if age > STALE_TASK_THRESHOLD_SECONDS:
                    task.transition_to(TaskStatus.FAILED)
                    self._tasks.update(task)
                    if task.reservation_id and self._quota:
                        self._quota.release(task.reservation_id)
                    if self._usage:
                        self._usage.record(UsageRecord(
                            task_id=task.task_id,
                            tenant_id=task.tenant_id,
                            gpu_index=task.gpu_index,
                            duration_seconds=age,
                            vram_mb=task.vram_mb,
                            cost_points=age * 0.01,
                        ))
                    logger.warning("任务 %s 超时 (%.0fs)，标记 failed", task.task_id, age)

    def tick(self) -> dict:
        """执行一轮调度，返回本轮动作摘要。"""
        actions = {"dispatched": 0, "reaped": 0, "stale_workers": []}

        # 1. 心跳检查
        if self._hb_checker:
            actions["stale_workers"] = self._hb_checker.check()

        # 2. 回收超时任务
        before_reap = len(self._tasks.list_by_status(TaskStatus.RUNNING))
        self._reap_stale_tasks()
        after_reap = len(self._tasks.list_by_status(TaskStatus.RUNNING))
        actions["reaped"] = before_reap - after_reap

        # 3. 分配 GPU：pending → queued → 选一个分配
        # 先把 pending 转为 queued
        for task in self._tasks.list_by_status(TaskStatus.PENDING):
            task.transition_to(TaskStatus.QUEUED)
            self._tasks.update(task)

        # 选任务分配
        gpus = self._build_gpu_status()
        queued = self._tasks.list_by_status(TaskStatus.QUEUED)
        while queued:
            if not gpus:
                break
            task = self._strategy.pick_next(queued, gpus)
            if task is None:
                break

            # 找一张能放下的 GPU（选剩余显存最少且够用的，best-fit）
            target = min(
                (g for g in gpus if g.free_vram_mb >= task.vram_mb),
                key=lambda g: g.free_vram_mb,
            )
            task.transition_to(TaskStatus.STARTING)
            task.gpu_index = target.gpu_index
            self._tasks.update(task)

            # 更新 GPU 状态
            target.free_vram_mb -= task.vram_mb
            target.in_use_by.append(task.task_id)

            # 从队列移除
            queued.remove(task)
            actions["dispatched"] += 1
            logger.info("调度: 任务 %s → GPU %d (%dMB)", task.task_id, task.gpu_index, task.vram_mb)

        return actions
