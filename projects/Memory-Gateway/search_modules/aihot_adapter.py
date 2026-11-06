"""AIHOT 中文 AI 资讯适配器（v14.0）
- 数据源: https://aihot.virxact.com
- 无需 API Key
"""
import httpx
from typing import Dict, List

class AihotAdapter:
    def __init__(self):
        self.base = "https://aihot.virxact.com"
        self.timeout = 10.0
        self.ua = "Memory-Gateway/1.0 (research)"

    def is_aihot_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["AI资讯", "AI热点", "AI日报", "AI新闻", "今天AI", "AI圈", "人工智能新闻"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 10) -> List[Dict]:
        if not self.is_aihot_query(query):
            return []
        print(f"   [aihot] 触发 AIHOT 特化", flush=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                r = await c.get(f"{self.base}/api/public/items", params={"mode": "selected", "take": limit})
                if r.status_code != 200:
                    return []
                data = r.json()
                items = data.get("items", [])
                results = []
                for item in items[:limit]:
                    title = item.get("title", "")
                    if not title:
                        continue
                    results.append({
                        "title": title,
                        "url": item.get("links", {}).get("aihot", "") or f"{self.base}/item/{item.get('id')}",
                        "content": f"[AIHOT] {title}\n{item.get('summary', '')[:200]}",
                        "engine": "aihot",
                        "authority": 0.85,
                    })
                print(f"   [aihot] 返回 {len(results)} 条", flush=True)
                return results
        except Exception as e:
            print(f"   [aihot] 失败: {type(e).__name__}: {e}", flush=True)
            return []

_instance = None
def get_aihot() -> AihotAdapter:
    global _instance
    if _instance is None:
        _instance = AihotAdapter()
    return _instance
