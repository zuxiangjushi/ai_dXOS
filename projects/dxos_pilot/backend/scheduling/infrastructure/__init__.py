"""适配器层（infrastructure）：GPU 额度仓储的具体实现。

本层是唯一允许出现 DB / ORM 代码的地方，依赖向内：
import 应用层端口抽象（QuotaRepository）并实现它，而非反向。
"""

from .sqlite_quota_repository import SqliteQuotaRepository

__all__ = ["SqliteQuotaRepository"]
