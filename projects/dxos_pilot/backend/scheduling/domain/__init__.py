"""领域层（最内层）：GPU 资源预扣的业务实体与业务异常。

本包只依赖 Python 标准库，禁止 import 任何 ORM / DB / FastAPI / GPU SDK。
"""

from .entities import ComputeQuota, GpuReservation, InsufficientQuotaError

__all__ = ["ComputeQuota", "GpuReservation", "InsufficientQuotaError"]
