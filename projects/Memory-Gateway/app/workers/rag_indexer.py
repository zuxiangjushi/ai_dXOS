"""RAG 文档索引：语义（Qdrant）+ 关键词（Meili）+ 智能分块 + 重排"""
import hashlib
from typing import Optional


class RagIndexer:
    def __init__(self, meili, qdrant_rag=None, index_name: str = "documents"):
        self.meili = meili
        self.qdrant_rag = qdrant_rag
        self.index_name = index_name

    async def index_document(self, user_id: str, title: str, content: str,
                             doc_id: Optional[str] = None,
                             chunk_size: int = 384, overlap: int = 64) -> Optional[str]:
        if not content or not content.strip():
            return None
        if not doc_id:
            doc_id = "doc_" + hashlib.md5(
                f"{user_id}{title}{content[:500]}".encode()).hexdigest()[:16]

        try:
            from adapters.doc_parser import smart_chunk
            chunks = smart_chunk(content, chunk_size, overlap)
        except Exception:
            chunks = [content[:20000]]
        if not chunks:
            chunks = [content[:20000]]

        # ★ 批量处理（默认 50 块一批）
        BATCH = 2
        n_q = n_m = 0

        for i in range(0, len(chunks), BATCH):
            batch = chunks[i:i+BATCH]
            batch_ids = [f"{doc_id}_c{i+j}" for j in range(len(batch))]

            # ① 批量嵌入
            if self.qdrant_rag is not None:
                embeddings = None
                for _retry in range(3):  # ★ 最多重试 3 次
                    try:
                        embeddings = await self.qdrant_rag._embed_batch(
                            [c[:2000] for c in batch])
                        break
                    except Exception as e:
                        _is_502 = "502" in str(e) or "Bad Gateway" in str(e)
                        if _is_502 and _retry < 2:
                            import asyncio as _aio
                            await _aio.sleep(1.0 * (_retry + 1))  # 递增退避
                            print(f"   [rag-index] 502 重试 {_retry+1}/3", flush=True)
                            continue
                        print(f"   [rag-index] 批量嵌入失败: {type(e).__name__}: {str(e)[:100]}", flush=True)
                        break
                if embeddings is None:
                    embeddings = [None] * len(batch)

                # ② 批量 Qdrant
                points = []
                for j, (chunk, emb, cid) in enumerate(zip(batch, embeddings, batch_ids)):
                    if emb is None:
                        continue
                    points.append({
                        "id": self.qdrant_rag._id(cid),
                        "vector": emb,
                        "payload": {
                            "user_id": user_id,
                            "title": title or "",
                            "content": chunk[:20000],
                        }
                    })
                if points:
                    try:
                        n = await self.qdrant_rag.upsert_batch(points)
                        n_q += n
                    except Exception as e:
                        print(f"   [rag-index] 批量 Qdrant 失败: {type(e).__name__}: {e}", flush=True)

            # ③ 批量 Meili
            docs = [{
                "id": batch_ids[j],
                "user_id": user_id,
                "title": title or "",
                "content": batch[j][:20000],
                "doc_id": doc_id,
                "chunk_idx": i + j,
            } for j in range(len(batch))]
            try:
                ok = await self.meili.add_documents(docs, self.index_name)
                if ok:
                    n_m += len(docs)
            except Exception as e:
                print(f"   [rag-index] 批量 Meili 失败: {type(e).__name__}: {e}", flush=True)

        print(f"   [rag-index] {doc_id}: {len(chunks)} 块 → Qdrant={n_q}, Meili={n_m}", flush=True)
        return doc_id if (n_q + n_m) > 0 else None

    async def search(self, query: str, user_id: str, limit: int = 5):
        out = []
        seen = set()
        if self.qdrant_rag is not None:
            try:
                hits = await self.qdrant_rag.search(query, user_id, limit=limit * 2)
                for h in hits:
                    if h.get("score", 0) < 0.4:
                        continue
                    c = (h.get("content") or "").strip()
                    if c and c not in seen:
                        seen.add(c)
                        out.append(h)
            except Exception as e:
                print(f"   [rag] Qdrant 失败: {type(e).__name__}: {e}", flush=True)
        try:
            hits = await self.meili.search(query, user_id=user_id,
                                           limit=limit, index=self.index_name)
            for h in hits:
                c = (h.get("content") or "").strip()
                if c and c not in seen:
                    seen.add(c)
                    out.append({"title": h.get("title", ""), "content": c, "score": 0.5})
        except Exception:
            pass

        if len(out) >= 3:
            try:
                from adapters.reranker import get_reranker
                out = await get_reranker().rerank(query, out, top_k=limit)
            except Exception as e:
                print(f"   [rag] 重排失败: {type(e).__name__}", flush=True)
        return out[:limit]
