"""应用用例：GPU 资源预扣（ReserveGpuUseCase）。

职责：只做流程编排（取额度 → 校验 → 调仓储预扣），不含任何持久化 / HTTP 细节。
依赖方向向内：仅 import 领域实体与端口抽象，通过构造函数注入 QuotaRepository。
"""
from __future__ import annotations

from ..domain.entities import (
    GpuReservation,
    InsufficientQuotaError,
)
from .ports import QuotaRepository


class ReserveGpuUseCase:
    """GPU 资源预扣用例。

    通过依赖注入持有 QuotaRepository（端口抽象），
    具体仓储由组合根（scheduling/__init__.py）装配。
    """

    def __init__(self, repo: QuotaRepository):
        self._repo = repo

    def run(self, tenant_id: str, vram_mb: int) -> GpuReservation:
        """为租户预扣 vram_mb 显存，返回 GpuReservation。

        - 租户无额度：InsufficientQuotaError
        - 显存额度不足：InsufficientQuotaError
        - 入参非法（vram_mb<=0 / 空 tenant）：ValueError
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if vram_mb <= 0:
            raise ValueError(f"vram_mb 必须 > 0，实际为 {vram_mb}")

        quota = self._repo.get_quota(tenant_id)
        if quota is None:
            raise InsufficientQuotaError(f"租户 {tenant_id} 未配置 GPU 额度")
        if vram_mb > quota.max_vram_mb:
            raise InsufficientQuotaError(
                f"租户 {tenant_id} 显存额度不足：需要 {vram_mb}MB，上限 {quota.max_vram_mb}MB"
            )

        return self._repo.reserve(tenant_id, vram_mb)
