"""OpenAlex 学术论文适配器（v14.4修复）
- 修复：用 display_name 而不是 title
- 修复：正确重建 abstract_inverted_index
"""
import httpx
from typing import Dict, List


class OpenAlexAdapter:
    def __init__(self):
        self.base = "https://api.openalex.org/works"
        self.timeout = 12.0
        self.ua = "Memory-Gateway/1.0 (mailto:research@example.com)"

    def is_openalex_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["学术论文", "论文搜索", "文献", "学术研究", "openalex", "OpenAlex",
                    "论文引用", "DOI", "文献检索", "研究论文"]
        return any(kw in query for kw in keywords)

    def _extract_topic(self, query: str) -> str:
        q = query
        for p in ["OpenAlex", "openalex", "搜索", "查找", "找一篇", "找一篇关于",
                  "关于", "的论文", "论文"]:
            q = q.replace(p, " ")
        return q.strip() or query

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_openalex_query(query):
            return []

        topic = self._extract_topic(query) or query
        print(f"   [openalex] 搜索: {topic}", flush=True)

        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                r = await c.get(self.base, params={"search": topic, "per-page": limit})
                if r.status_code != 200:
                    print(f"   [openalex] HTTP {r.status_code}", flush=True)
                    return []
                data = r.json()
                results = []
                for item in data.get("results", [])[:limit]:
                    # ★ 修复：display_name
                    title = item.get("display_name") or item.get("title") or ""
                    if not title:
                        continue
                    doi = item.get("doi") or ""
                    url = doi if doi.startswith("http") else (
                        f"https://doi.org/{doi}" if doi else item.get("id", ""))

                    authors = []
                    for a in item.get("authorships", [])[:3]:
                        name = a.get("author", {}).get("display_name", "")
                        if name:
                            authors.append(name)

                    # ★ 修复：重建 inverted index
                    abstract = "无摘要"
                    inv = item.get("abstract_inverted_index")
                    if inv:
                        words = {}
                        for word, positions in inv.items():
                            for pos in positions:
                                words[pos] = word
                        abstract = " ".join(words[i] for i in sorted(words.keys()))[:500]

                    results.append({
                        "title": f"[OpenAlex] {title[:100]}",
                        "url": url,
                        "content": (
                            f"[OpenAlex] {title}\n"
                            f"作者: {', '.join(authors) or '?'}\n"
                            f"年份: {item.get('publication_year', '?')}\n"
                            f"引用数: {item.get('cited_by_count', '?')}\n"
                            f"摘要: {abstract[:300]}"
                        ),
                        "engine": "openalex",
                        "authority": 0.90,
                    })
                print(f"   [openalex] 返回 {len(results)} 条", flush=True)
                return results
        except Exception as e:
            print(f"   [openalex] 失败: {type(e).__name__}: {e}", flush=True)
            return []


_instance = None
def get_openalex() -> OpenAlexAdapter:
    global _instance
    if _instance is None:
        _instance = OpenAlexAdapter()
    return _instance
