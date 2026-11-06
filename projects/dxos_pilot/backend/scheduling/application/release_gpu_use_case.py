"""用例：释放 GPU 预扣（幂等）。"""
from __future__ import annotations

from .ports import QuotaRepository


class ReleaseGpuUseCase:
    """释放指定预扣凭证；重复释放不报错（幂等）。"""

    def __init__(self, quota_repo: QuotaRepository):
        self._quota = quota_repo

    def execute(self, reservation_id: str) -> bool:
        """返回是否实际释放了（False 表示该 ID 已释放过或不存在）。"""
        return self._quota.release(reservation_id)
