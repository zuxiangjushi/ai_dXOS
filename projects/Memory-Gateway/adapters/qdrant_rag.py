"""Qdrant RAG 客户端：文档语义检索"""
import os
import uuid
import hashlib
import httpx
import asyncio
_EMBED_SEM = asyncio.Semaphore(3)  # ★ 最多 3 个并发嵌入
from typing import List, Dict, Optional


class QdrantRagClient:
    def __init__(self, qdrant_url=None, collection=None,
                 embed_url=None, embed_model=None, dim=1024, timeout=15.0):
        self.qdrant_url = (qdrant_url or os.environ.get(
            "QDRANT_URL", "http://127.0.0.1:6333")).rstrip("/")
        self.collection = collection or "rag_documents"
        self.embed_url = (embed_url or os.environ.get(
            "EMBED_URL", "http://127.0.0.1:8003/embeddings")).rstrip("/")
        self.embed_model = embed_model or os.environ.get("EMBED_MODEL", "models/bge-m3")
        self.dim = dim
        self.timeout = timeout

    def _id(self, key: str) -> str:
        """Qdrant 需要 UUID 或 uint64，字符串不行"""
        h = hashlib.md5(key.encode()).hexdigest()
        return str(uuid.UUID(h))

    async def _embed(self, text: str) -> List[float]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(self.embed_url,
                             json={"model": self.embed_model, "input": [text]})
            r.raise_for_status()
            body = r.json()
        if isinstance(body, list) and body and isinstance(body[0], list):
            return body[0]
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, list) and data:
            x = data[0]
            return x.get("embedding") if isinstance(x, dict) else x
        raise ValueError("embed 格式异常")

    async def ensure_collection(self) -> bool:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(f"{self.qdrant_url}/collections/{self.collection}")
            if r.status_code == 200:
                return True
            r = await c.put(
                f"{self.qdrant_url}/collections/{self.collection}",
                json={"vectors": {"size": self.dim, "distance": "Cosine"}})
            if r.status_code not in (200, 201):
                print(f"   [rag-qdrant] ensure_collection HTTP {r.status_code}: {r.text[:200]}", flush=True)
                return False
            return True

    async def _embed_batch(self, texts: list) -> list:
        """批量嵌入：1 次 HTTP 传 N 条（限流 3 并发）"""
        if not texts:
            return []
        async with _EMBED_SEM:
            return await self._embed_batch_inner(texts)

    async def _embed_batch_inner(self, texts: list) -> list:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(self.embed_url,
                             json={"model": self.embed_model, "input": texts})
            r.raise_for_status()
            body = r.json()
        if isinstance(body, list) and body and isinstance(body[0], list):
            return body
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, list):
            return [d.get("embedding") for d in data]
        raise ValueError("embed_batch 格式异常")

    async def upsert_batch(self, points: list) -> int:
        """批量 upsert：1 次 HTTP 传 N 点"""
        if not points:
            return 0
        ok = await self.ensure_collection()
        if not ok:
            return 0
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.put(
                f"{self.qdrant_url}/collections/{self.collection}/points?wait=true",
                json={"points": points})
            if r.status_code != 200:
                print(f"   [rag-qdrant] batch upsert HTTP {r.status_code}: {r.text[:200]}", flush=True)
                return 0
            return len(points)

    async def upsert(self, user_id: str, title: str, content: str,
                     doc_id: Optional[str] = None) -> Optional[str]:
        if not content or not content.strip():
            return None
        if not doc_id:
            key = f"{user_id}|{title}|{content[:500]}"
            doc_id = self._id(key)
        else:
            doc_id = self._id(doc_id)
        try:
            vec = await self._embed(content[:2000])
        except Exception as e:
            print(f"   [rag-qdrant] embed 失败: {type(e).__name__}: {e}", flush=True)
            return None
        ok = await self.ensure_collection()
        if not ok:
            return None
        payload = {
            "points": [{
                "id": doc_id,
                "vector": vec,
                "payload": {
                    "user_id": user_id,
                    "title": title or "",
                    "content": content[:20000],
                }
            }]
        }
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.put(
                f"{self.qdrant_url}/collections/{self.collection}/points",
                params={"wait": "true"}, json=payload)
            if r.status_code not in (200, 201):
                print(f"   [rag-qdrant] upsert HTTP {r.status_code}: {r.text[:200]}", flush=True)
                return None
        return doc_id

    async def search(self, query: str, user_id: str, limit: int = 5) -> List[Dict]:
        if not query:
            return []
        try:
            vec = await self._embed(query[:500])
        except Exception as e:
            print(f"   [rag-qdrant] query embed 失败: {type(e).__name__}: {e}", flush=True)
            return []
        body = {
            "vector": vec,
            "limit": limit,
            "with_payload": True,
            "filter": {
                "must": [{"key": "user_id", "match": {"value": user_id}}]
            }
        }
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(
                f"{self.qdrant_url}/collections/{self.collection}/points/search",
                json=body)
            if r.status_code != 200:
                print(f"   [rag-qdrant] search HTTP {r.status_code}: {r.text[:200]}", flush=True)
                return []
            hits = r.json().get("result", [])
        out = []
        for h in hits:
            p = h.get("payload") or {}
            out.append({
                "id": str(h.get("id", "")),
                "title": p.get("title", ""),
                "content": p.get("content", ""),
                "score": h.get("score", 0),
            })
        return out


_qdrant_rag: Optional[QdrantRagClient] = None


def get_rag() -> QdrantRagClient:
    global _qdrant_rag
    if _qdrant_rag is None:
        _qdrant_rag = QdrantRagClient()
    return _qdrant_rag
