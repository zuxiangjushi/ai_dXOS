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
        content_hash=r["content_hash"], trust=r["trust"])

class RecallService:
    def __init__(self, embed, vector, keyword, repo, scorer=None):
        self.e, self.v, self.k, self.repo = embed, vector, keyword, repo
        self.scorer = scorer or RecallScorer()

    async def recall(self, query, scope, top_k=8, now=None):
        now = now or int(time.time())
        flt = {"user_id": scope["user_id"], "workspace_id": scope["workspace_id"]}
        if scope.project_id:
            flt["project_id"] = scope.project_id
        vec_scores, kw_ids = {}, []
        try:
            qv = await self.e.embed(query)
            hits = await self.v.search(qv, top_k * 4, flt)
            vec_scores = {h["id"]: h["score"] for h in hits}
        except (IndexUnavailable, Exception) as ex:
            self.degraded = getattr(self, "degraded", 0) + 1
        try:
            kw_ids = await asyncio.to_thread(self.k.search, query, flt, top_k * 4)
        except Exception:
            self.degraded = getattr(self, "degraded", 0) + 1
        cand = sorted(rrf([list(vec_scores.keys()), kw_ids]).items(),
                      key=lambda x: -x[1])[: top_k * 3]
        ids = [i for i, _ in cand]
        rows = await self.repo.get_by_ids(ids, scope)
        out = []
        for mid, _fuse in cand:
            row = rows.get(mid)
            if not row:
                continue
            sim = vec_scores.get(mid)
            if sim is None:
                sim = self.scorer.w.min_similarity
            s = self.scorer.score(to_record(row), sim, now=now,
                                  access_count=row["access_count"] or 0)
            if s is None:
                continue
            s.parts.update({"origin_type": row["origin_type"], "trust": row["trust"],
                            "entity_key": row["entity_key"], "valid_from": row["valid_from"],
                            "source": row["origin_type"]})
            out.append(s)
        return sorted(out, key=lambda x: -x.score)[:top_k]
