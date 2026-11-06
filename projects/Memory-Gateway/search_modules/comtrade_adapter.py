"""UN Comtrade 贸易数据适配器（v14.0）
- 200+ 国家贸易数据
- 需要免费 Key（在 .env.g0 配置 COMTRADE_KEY）
"""
import os
import httpx
from typing import Dict, List

class ComtradeAdapter:
    def __init__(self):
        self.base = "https://comtradeapi.un.org/data/v1/get"
        self.key = os.environ.get("COMTRADE_KEY", "").strip()
        self.timeout = 15.0
        self.ua = "Memory-Gateway/1.0"

    def is_configured(self) -> bool:
        return bool(self.key)

    def is_comtrade_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["贸易数据", "进出口", "外贸", "HS编码", "海关数据", "贸易统计", "双边贸易"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_configured():
            print(f"   [comtrade] 未配置 COMTRADE_KEY，跳过", flush=True)
            return []
        if not self.is_comtrade_query(query):
            return []
        print(f"   [comtrade] 触发 UN Comtrade 特化", flush=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                r = await c.get(f"{self.base}/C/A/HS", params={
                    "cmdCode": "TOTAL", "period": "2023", "reporterCode": "156",
                    "partnerCode": "0", "flowCode": "X", "maxrecords": limit,
                    "subscription-key": self.key
                })
                if r.status_code != 200:
                    print(f"   [comtrade] HTTP {r.status_code}", flush=True)
                    return []
                data = r.json()
                results = []
                for item in data.get("data", [])[:limit]:
                    results.append({
                        "title": f"[Comtrade] {item.get('reporterDesc', '?')} → {item.get('partnerDesc', '?')}",
                        "url": "https://comtradeapi.un.org",
                        "content": f"[UN Comtrade] {item.get('reporterDesc')} 对 {item.get('partnerDesc')} 出口 {item.get('cmdDesc', '')} 贸易额: {item.get('primaryValue', '?')} 美元",
                        "engine": "comtrade",
                        "authority": 0.92,
                    })
                print(f"   [comtrade] 返回 {len(results)} 条", flush=True)
                return results
        except Exception as e:
            print(f"   [comtrade] 失败: {type(e).__name__}: {e}", flush=True)
            return []

_instance = None
def get_comtrade() -> ComtradeAdapter:
    global _instance
    if _instance is None:
        _instance = ComtradeAdapter()
    return _instance
