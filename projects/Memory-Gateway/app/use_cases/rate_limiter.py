"""简单内存级限流器（按 user_id 滑动窗口）"""
import os
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, qps: int = 10, window: int = 1):
        self.qps = qps
        self.window = window
        self._buckets = defaultdict(deque)
        self._stats = {"allowed": 0, "rejected": 0}

    def allow(self, key: str) -> bool:
        now = time.time()
        q = self._buckets[key]
        # 清理过期
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.qps:
            self._stats["rejected"] += 1
            return False
        q.append(now)
        self._stats["allowed"] += 1
        return True

    def stats(self) -> dict:
        return dict(self._stats)


_limiter = None


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        qps = int(os.environ.get("RATE_QPS", "10"))
        _limiter = RateLimiter(qps=qps)
    return _limiter
