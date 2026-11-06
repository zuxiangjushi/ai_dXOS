"""17track 物流追踪适配器（v14.1）
- 2400+ 承运商
- 需要免费 Key（在 .env.g0 配置 TRACK17_KEY）
"""
import os
import httpx
from typing import Dict, List

class Track17Adapter:
    def __init__(self):
        self.base = "https://api.17track.net/track/v2.2"
        self.key = os.environ.get("TRACK17_KEY", "").strip()
        self.timeout = 10.0
        self.ua = "Memory-Gateway/1.0"

    def is_configured(self) -> bool:
        return bool(self.key)

    def is_track_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["快递", "物流", "包裹", "运单", "tracking", "快递单号", "货运"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_configured():
            return []
        if not self.is_track_query(query):
            return []
        print(f"   [track17] 触发 17track 特化", flush=True)
        return [{
            "title": "[17track] 物流追踪",
            "url": "https://www.17track.net",
            "content": "[17track] 请提供快递单号进行追踪。17track 支持 2400+ 承运商。",
            "engine": "track17",
            "authority": 0.75,
        }]

_instance = None
def get_track17() -> Track17Adapter:
    global _instance
    if _instance is None:
        _instance = Track17Adapter()
    return _instance
