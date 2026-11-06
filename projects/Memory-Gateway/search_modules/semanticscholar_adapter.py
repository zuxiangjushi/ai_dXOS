"""Semantic Scholar 论文适配器（v14.0）
- 2亿+ 论文引用图谱
- 无需 API Key（100 req/5min）
"""
import httpx
from typing import Dict, List

class SemanticScholarAdapter:
    def __init__(self):
        self.base = "https://api.semanticscholar.org/graph/v1/paper/search"
        self.timeout = 10.0
        self.ua = "Memory-Gateway/1.0"

    def is_semantic_scholar_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["论文引用", "引用图谱", "论文引用", "引用关系", "文献综述", "文献引用"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_semantic_scholar_query(query):
            return []
        print(f"   [semanticscholar] 触发 Semantic Scholar 特化", flush=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                r = await c.get(self.base, params={"query": query, "limit": limit, "fields": "title,abstract,year,citationCount,authors"})
                if r.status_code != 200:
                    return []
                data = r.json()
                results = []
                for item in data.get("data", [])[:limit]:
                    title = item.get("title", "")
                    if not title:
                        continue
                    results.append({
                        "title": f"[Semantic Scholar] {title}",
                        "url": f"https://www.semanticscholar.org/paper/{item.get('paperId', '')}",
                        "content": f"[Semantic Scholar] {title}\n作者: {', '.join(a.get('name', '') for a in item.get('authors', [])[:3])}\n年份: {item.get('year', '?')}\n引用数: {item.get('citationCount', '?')}\n摘要: {(item.get('abstract') or '无摘要')[:300]}",
                        "engine": "semanticscholar",
                        "authority": 0.88,
                    })
                print(f"   [semanticscholar] 返回 {len(results)} 条", flush=True)
                return results
        except Exception as e:
            print(f"   [semanticscholar] 失败: {type(e).__name__}: {e}", flush=True)
            return []

_instance = None
def get_semanticscholar() -> SemanticScholarAdapter:
    global _instance
    if _instance is None:
        _instance = SemanticScholarAdapter()
    return _instance
