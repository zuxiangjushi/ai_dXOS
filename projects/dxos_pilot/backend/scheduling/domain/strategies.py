"""调度策略：从待调度任务中选取下一个要分配 GPU 的任务。

纯领域逻辑：只依赖 domain 实体，不依赖任何框架或仓储实现。
具体策略实现本接口，由 DispatchLoopUseCase 持有并调用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .entities import GpuStatus, Task


class SchedulingStrategy(ABC):
    """调度策略抽象：给定待调度任务和 GPU 状态，选出下一个任务。"""

    @abstractmethod
    def pick_next(self, tasks: list[Task], gpus: list[GpuStatus]) -> Task | None:
        """返回应被分配 GPU 的下一个任务；无可用任务或无可用 GPU 时返回 None。"""


class FIFOStrategy(SchedulingStrategy):
    """先进先出：按 created_at 升序取第一个能放入某张 GPU 的任务。"""

    def pick_next(self, tasks: list[Task], gpus: list[GpuStatus]) -> Task | None:
        if not tasks or not gpus:
            return None
        sorted_tasks = sorted(tasks, key=lambda t: t.created_at)
        for task in sorted_tasks:
            if self._fits(task, gpus):
                return task
        return None

    @staticmethod
    def _fits(task: Task, gpus: list[GpuStatus]) -> bool:
        return any(g.free_vram_mb >= task.vram_mb for g in gpus)


class PriorityStrategy(SchedulingStrategy):
    """优先级调度：priority 降序，同级按 created_at 升序（FIFO 兜底）。"""

    def pick_next(self, tasks: list[Task], gpus: list[GpuStatus]) -> Task | None:
        if not tasks or not gpus:
            return None
        sorted_tasks = sorted(tasks, key=lambda t: (-t.priority, t.created_at))
        for task in sorted_tasks:
            if self._fits(task, gpus):
                return task
        return None

    @staticmethod
    def _fits(task: Task, gpus: list[GpuStatus]) -> bool:
        return any(g.free_vram_mb >= task.vram_mb for g in gpus)
