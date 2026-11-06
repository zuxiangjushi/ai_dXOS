"""快递100 物流追踪适配器（v14.1） - 3000+ 快递公司"""
import re
from typing import Dict, List

class Kuaidi100Adapter:
    def is_kuaidi_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["快递", "物流", "包裹", "运单", "快递单号", "快递查询"]
        return any(kw in query for kw in keywords)

    def extract_tracking(self, query: str) -> str:
        m = re.search(r'([A-Za-z0-9]{8,20})', query)
        return m.group(1) if m else ""

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_kuaidi_query(query):
            return []
        tracking = self.extract_tracking(query)
        if not tracking:
            return [{
                "title": "[快递100] 快递查询",
                "url": "https://www.kuaidi100.com",
                "content": "[快递100] 请提供快递单号。支持 3000+ 快递公司。",
                "engine": "kuaidi100",
                "authority": 0.70,
            }]
        print(f"   [kuaidi100] 触发: {tracking}", flush=True)
        return [{
            "title": f"[快递100] 单号 {tracking}",
            "url": f"https://www.kuaidi100.com/chaxun?nu={tracking}",
            "content": f"[快递100] 查询单号 {tracking}，请访问链接查看详细物流。",
            "engine": "kuaidi100",
            "authority": 0.75,
        }]

_instance = None
def get_kuaidi100() -> Kuaidi100Adapter:
    global _instance
    if _instance is None:
        _instance = Kuaidi100Adapter()
    return _instance
