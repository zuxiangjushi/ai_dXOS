import math, time
from dataclasses import dataclass, field
from .memory import MemoryRecord

@dataclass(frozen=True)
class RecallWeights:
    similarity: float = 0.45; importance: float = 0.20; confidence: float = 0.15
    recency: float = 0.12; access: float = 0.05; tier_prior: float = 0.03
    min_similarity: float = 0.55; halflife_days: float = 30.0; access_saturation: int = 50

@dataclass(frozen=True)
class ScoredMemory:
    memory: MemoryRecord; similarity: float; score: float; parts: dict = field(default_factory=dict)

class RecallScorer:
    """加权和替代连乘，阈值只作用原始相似度，得分不回写实体。"""
    def __init__(self, w: RecallWeights | None = None):
        self.w = w or RecallWeights()
        s = (self.w.similarity + self.w.importance + self.w.confidence +
             self.w.recency + self.w.access + self.w.tier_prior)
        assert abs(s - 1.0) < 1e-6, f"权重之和必须为 1，当前 {s}"

    def _recency(self, m: MemoryRecord, now: int) -> float:
        # 优先用"上次访问时间"，兜底到 valid_from
        last = getattr(m, "last_accessed_at", None) or m.valid_from or now
        age = max(0.0, (now - last) / 86400.0)
        return math.exp(-math.log(2) * age / self.w.halflife_days)

    def _access(self, m: MemoryRecord) -> float:
        return min(1.0, math.log1p(m.last_accessed_at or 0) / math.log1p(self.w.access_saturation))

    def score(self, m: MemoryRecord, similarity: float, now: int | None = None,
              access_count: int = 0) -> ScoredMemory | None:
        now = now or int(time.time())
        if similarity < self.w.min_similarity: return None
        if not m.is_effective(now): return None
        rec = self._recency(m, now)
        acc = min(1.0, math.log1p(access_count) / math.log1p(self.w.access_saturation))
        from .credentials import TIER_PRIOR
        parts = {"similarity": similarity, "importance": m.importance, "confidence": m.confidence,
                 "recency": rec, "access": acc, "tier_prior": TIER_PRIOR.get(m.tier, 0.7)}
        w = self.w
        score = (w.similarity * parts["similarity"] + w.importance * parts["importance"] +
                 w.confidence * parts["confidence"] + w.recency * parts["recency"] +
                 w.access * parts["access"] + w.tier_prior * parts["tier_prior"])
        return ScoredMemory(memory=m, similarity=similarity, score=float(score), parts=parts)
