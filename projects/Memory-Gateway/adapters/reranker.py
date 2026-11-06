"""bge-reranker 重排客户端：Infinity /rerank"""
import os
import httpx
from typing import List, Dict


class Reranker:
    def __init__(self, url: str = None, model: str = None, timeout: float = 10.0):
        self.url = url or os.environ.get("RERANKER_URL", "http://192.168.10.132:8012/rerank")
        self.model = model or os.environ.get("RERANKER_MODEL", "bge-reranker-v2-m3")
        self.timeout = timeout

    async def rerank(self, query: str, docs: List[Dict], top_k: int = 5) -> List[Dict]:
        if not docs or not query:
            return docs[:top_k]
        texts = [(d.get("content") or "")[:500] for d in docs]
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(self.url, json={
                    "model": self.model,
                    "query": query,
                    "documents": texts,
                })
                if r.status_code != 200:
                    print(f"   [reranker] HTTP {r.status_code}: {r.text[:150]}", flush=True)
                    return docs[:top_k]
                data = r.json()
        except Exception as e:
            print(f"   [reranker] 失败: {type(e).__name__}: {e}", flush=True)
            return docs[:top_k]

        results = data.get("results") or data.get("data") or []
        if not results:
            return docs[:top_k]
        out = []
        for x in results:
            idx = x.get("index")
            if idx is None:
                continue
            if 0 <= idx < len(docs):
                d = dict(docs[idx])
                d["rerank_score"] = float(x.get("relevance_score") or x.get("score") or 0)
                out.append(d)
        out.sort(key=lambda x: -x.get("rerank_score", 0))
        return out[:top_k]


_reranker = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker
