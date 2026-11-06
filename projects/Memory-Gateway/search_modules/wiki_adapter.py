"""Wikipedia API（v13.5） - 免费，无需 Key"""
from typing import Dict, List

import httpx

UA = "Memory-Gateway/1.0 (research)"


class WikiAdapter:
    def __init__(self):
        self.timeout = 8.0

    def is_wiki_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["是什么", "什么是", "介绍", "百科", "定义", "who is", "what is"]
        return any(kw in query for kw in keywords)

    def extract_topic(self, query: str) -> str:
        """提取主题词"""
        import re
        # 剥离常见疑问前缀
        q = re.sub(r'^(什么是|是什么|介绍下|请介绍|请解释|what is|who is)\s*', '', query.strip())
        return q.strip("？?。.")

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_wiki_query(query):
            return []

        topic = self.extract_topic(query)
        if not topic or len(topic) < 2:
            return []

        print(f"   [wiki] 查询: {topic}", flush=True)

        results = []
        # 中文 + 英文
        for lang in ["zh", "en"]:
            try:
                async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                    r = await c.get(
                        f"https://{lang}.wikipedia.org/w/api.php",
                        params={
                            "action": "query",
                            "format": "json",
                            "prop": "extracts",
                            "titles": topic,
                            "exintro": 1,
                            "explaintext": 1,
                            "redirects": 1,
                        },
                    )
                    if r.status_code != 200:
                        continue
                    d = r.json()
                    pages = d.get("query", {}).get("pages", {})
                    for pid, page in pages.items():
                        if pid == "-1":
                            continue
                        title = page.get("title", "")
                        extract = page.get("extract", "")[:1500]
                        if not extract:
                            continue
                        results.append({
                            "title": f"[{lang.upper()}] {title}",
                            "url": f"https://{lang}.wikipedia.org/wiki/{title}",
                            "content": f"【维基百科】{title}\n\n{extract}",
                            "engine": f"wikipedia_{lang}",
                            "authority": 0.85,
                        })
            except Exception as e:
                print(f"   [wiki] {lang} 失败: {type(e).__name__}", flush=True)

        print(f"   [wiki] 返回 {len(results)} 条", flush=True)
        return results[:limit]


_instance = None


def get_wiki() -> WikiAdapter:
    global _instance
    if _instance is None:
        _instance = WikiAdapter()
    return _instance
