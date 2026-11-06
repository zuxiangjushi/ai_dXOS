"""DexPaprika DEX 数据适配器（v14.1） - 无需 Key"""
import httpx
from typing import Dict, List

class DexPaprikaAdapter:
    def __init__(self):
        self.base = "https://api.dexpaprika.com"
        self.timeout = 10.0
        self.ua = "Memory-Gateway/1.0"

    def is_dex_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["DEX", "去中心化交易所", "链上交易", "加密货币价格", "代币价格", "DeFi", "Uniswap"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_dex_query(query):
            return []
        print(f"   [dexpaprika] 触发 DEX 特化", flush=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                r = await c.get(f"{self.base}/search", params={"query": query, "limit": limit})
                if r.status_code != 200:
                    return []
                data = r.json()
                results = []
                for item in data.get("tokens", [])[:limit]:
                    results.append({
                        "title": f"[DexPaprika] {item.get('name', '?')} ({item.get('symbol', '?')})",
                        "url": f"https://dexpaprika.com/token/{item.get('id', '')}",
                        "content": f"[DexPaprika] {item.get('name')} ({item.get('symbol')})\n链: {item.get('chain', '?')}",
                        "engine": "dexpaprika",
                        "authority": 0.80,
                    })
                print(f"   [dexpaprika] 返回 {len(results)} 条", flush=True)
                return results
        except Exception as e:
            print(f"   [dexpaprika] 失败: {type(e).__name__}", flush=True)
            return []

_instance = None
def get_dexpaprika() -> DexPaprikaAdapter:
    global _instance
    if _instance is None:
        _instance = DexPaprikaAdapter()
    return _instance
