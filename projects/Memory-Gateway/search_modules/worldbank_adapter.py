"""World Bank 贸易数据适配器（v14.0）
- 200+ 经济体贸易数据
- 无需 API Key
"""
import httpx
from typing import Dict, List

class WorldBankAdapter:
    def __init__(self):
        self.base = "https://wits.worldbank.org/API/V1/wits/datasource/tradestats-trade"
        self.timeout = 12.0
        self.ua = "Memory-Gateway/1.0"

    def is_worldbank_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["世界银行", "贸易数据", "WTO", "关税", "贸易壁垒", "全球贸易"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_worldbank_query(query):
            return []
        print(f"   [worldbank] 触发 World Bank 特化", flush=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                r = await c.get(self.base, params={"format": "JSON", "limit": limit})
                if r.status_code != 200:
                    return []
                data = r.json()
                results = []
                for item in data.get("data", [])[:limit]:
                    results.append({
                        "title": f"[World Bank] {item.get('reporter', '?')} → {item.get('partner', '?')}",
                        "url": "https://wits.worldbank.org",
                        "content": f"[World Bank WITS] {item.get('reporter')} 对 {item.get('partner')} {item.get('product', '')} 贸易数据",
                        "engine": "worldbank",
                        "authority": 0.90,
                    })
                print(f"   [worldbank] 返回 {len(results)} 条", flush=True)
                return results
        except Exception as e:
            print(f"   [worldbank] 失败: {type(e).__name__}: {e}", flush=True)
            return []

_instance = None
def get_worldbank() -> WorldBankAdapter:
    global _instance
    if _instance is None:
        _instance = WorldBankAdapter()
    return _instance
