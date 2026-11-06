"""Meilisearch 网页索引：作为"自建中文索引"
- 承接 SearXNG 发现 + 抓取后的内容
- 提供 BM25 检索
"""
import os
import httpx
from typing import List, Dict


class MeiliWebIndex:
    def __init__(self, url: str = None, api_key: str = None,
                 index: str = "web_index", timeout: float = 10.0):
        self.url = (url or os.environ.get(
            "MEILI_URL", "http://127.0.0.1:7700")).rstrip("/")
        self.api_key = api_key or os.environ.get("MEILISEARCH_API_KEY", "")
        # ★ 兜底：从 .env.g0 读取（避免 shell 未 export）
        if not self.api_key:
            try:
                for _l in open("/ai/Memory-Gateway/.env.g0"):
                    if _l.startswith("MEILISEARCH_API_KEY="):
                        self.api_key = _l.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            except Exception:
                pass
        if not self.api_key:
            print("   [meili_web] ⚠️ MEILISEARCH_API_KEY 为空，将无鉴权", flush=True)
        self.index = index
        self.timeout = timeout

    async def _client(self):
        h = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return httpx.AsyncClient(base_url=self.url, headers=h,
                                 timeout=self.timeout)

    async def search(self, query: str, limit: int = 10) -> List[Dict]:
        """BM25 搜索（中文）"""
        if not query:
            return []
        try:
            async with await self._client() as c:
                r = await c.post(
                    f"/indexes/{self.index}/search",
                    json={"q": query, "limit": limit})
                if r.status_code != 200:
                    return []
                hits = r.json().get("hits", [])
            out = []
            for h in hits:
                out.append({
                    "title": h.get("title", ""),
                    "url": h.get("url", ""),
                    "content": h.get("content", "")[:400],
                    "engine": "meili_web",
                })
            return out
        except Exception as e:
            print(f"   [meili_web] 失败: {type(e).__name__}: {e}", flush=True)
            return []

    async def index_document(self, source_id: str, url: str, title: str,
                             content: str, domain: str = "",
                             published_at: int = 0) -> bool:
        """写入网页到索引"""
        if not content:
            return False
        try:
            async with await self._client() as c:
                r = await c.post(
                    f"/indexes/{self.index}/documents",
                    json=[{
                        "source_id": source_id,
                        "url": url,
                        "title": title,
                        "content": content[:50000],
                        "domain": domain,
                        "published_at": published_at,
                        "retrieved_at": int(__import__("time").time()),
                    }])
                if r.status_code not in (200, 202):
                    print(f"   [meili_web] index HTTP {r.status_code}: {r.text[:150]}", flush=True)
                return r.status_code in (200, 202)
        except Exception as e:
            print(f"   [meili_web] index 失败: {type(e).__name__}: {e}", flush=True)
            return False


_client = None


def get_meili_web() -> MeiliWebIndex:
    global _client
    if _client is None:
        _client = MeiliWebIndex()
    return _client


if __name__ == "__main__":
    import asyncio, sys
    sys.path.insert(0, "/ai/Memory-Gateway")

    async def main():
        idx = get_meili_web()
        # 测试写入
        await idx.index_document(
            "src_test_001", "https://example.com", "测试文档",
            "我们的项目使用 Qdrant 作为向量库，Redis 作为缓存",
            domain="example.com")
        await asyncio.sleep(2)
        # 测试查询
        results = await idx.search("向量库", limit=3)
        print(f"结果数: {len(results)}")
        for r in results:
            print(f"  · {r['title']} | {r['content'][:60]}")

    asyncio.run(main())
