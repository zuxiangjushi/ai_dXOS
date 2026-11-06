import asyncio, time
from contracts.scoring import RecallScorer
from contracts.memory import MemoryRecord, MemoryClass
from contracts.scope import MemoryScope
from contracts.errors import IndexUnavailable

def rrf(lists, k=60):
    out = {}
    for ranked in lists:
        for i, mid in enumerate(ranked, start=1):
            out[mid] = out.get(mid, 0.0) + 1.0 / (k + i)
    return out

def to_record(r):
    return MemoryRecord(
        memory_id=r["memory_id"],
        scope=MemoryScope(user_id=r["user_id"], workspace_id=r["workspace_id"],
                          project_id=r.get("project_id")),
        content=r["content"], entity_key=r["entity_key"] or "",
        memory_class=MemoryClass(r["memory_class"] or "episode"), tier=r["tier"],
        confidence=r["confidence"], importance=r["importance"],
        origin_type=r["origin_type"], valid_from=r["valid_from"], valid_until=r["valid_until"],
        supersedes=r["supersedes"], superseded_by=r["superseded_by"],
        content_hash=r["content_hash"], trust=r["trust"]
    )

class RetrievalService:
    """完整检索服务：向量+关键词 RRF 融合 + 加性打分 + 租户条件下推"""
    def __init__(self, embed_client, vector_store, keyword_store, repo, scorer=None):
        self.embed = embed_client
        self.vector = vector_store
        self.keyword = keyword_store
        self.repo = repo
        self.scorer = scorer or RecallScorer()
        self.degraded_count = 0

    async def recall(self, query, scope, top_k=8, now=None):
        now = now or int(time.time())
        flt = {"user_id": scope.user_id, "workspace_id": scope.workspace_id}
        if scope.project_id:
            flt["project_id"] = scope.project_id

        vec_scores = {}
        kw_ids = []
        try:
            qv = await self.embed.embed(query)
            hits = await self.vector.search(qv, top_k * 4, flt)
            vec_scores = {h["id"]: h["score"] for h in hits}
        except Exception as e:
            self.degraded_count += 1
            print(f"向量检索降级: {e}")
        try:
            kw_ids = await asyncio.to_thread(self.keyword.search, query, flt, top_k * 4)
        except Exception as e:
            self.degraded_count += 1
            print(f"关键词检索降级: {e}")

        cand = sorted(rrf([list(vec_scores.keys()), kw_ids]).items(),
                      key=lambda x: -x[1])[: top_k * 3]
        ids = [i for i, _ in cand]
        rows = await self.repo.get_by_ids(ids, scope)

        results = []
        for mid, _ in cand:
            row = rows.get(mid)
            if not row:
                continue
            sim = vec_scores.get(mid, self.scorer.w.min_similarity)
            score_result = self.scorer.score(to_record(row), sim, now=now,
                                             access_count=row.get("access_count") or 0)
            if score_result is None:
                continue
            score_result.parts.update({
                "origin_type": row.get("origin_type", "unknown"),
                "trust": row.get("trust", "trusted"),
                "entity_key": row.get("entity_key", ""),
                "valid_from": row.get("valid_from", 0)
            })
            results.append(score_result)

        return sorted(results, key=lambda x: -x.score)[:top_k]
