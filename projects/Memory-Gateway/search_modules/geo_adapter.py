"""IP 归属地 / 时区（v13.5） - ipwho.is 免费"""
import re
from typing import Dict, List

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


class GeoAdapter:
    def __init__(self):
        self.timeout = 6.0

    def is_geo_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["IP地址", "IP归属", "ip地址", "我的IP", "IP查询",
                    "时区", "现在是几点", "当地时间", "世界时间"]
        return any(kw in query for kw in keywords)

    def extract_ip(self, query: str) -> str:
        m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', query)
        return m.group(1) if m else ""

    async def _fetch_ipwhois(self, ip: str = "") -> Dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                url = f"https://ipwho.is/{ip}" if ip else "https://ipwho.is/"
                r = await c.get(url)
                if r.status_code != 200:
                    return {}
                return r.json()
        except Exception:
            return {}

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_geo_query(query):
            return []

        print(f"   [geo] 触发地理特化", flush=True)
        results = []

        # IP 归属地
        if any(kw in query for kw in ["IP", "ip"]):
            ip = self.extract_ip(query)
            data = await self._fetch_ipwhois(ip)
            if data and data.get("success"):
                content = (
                    f"【IP 归属地查询】{data.get('ip', '?')}\n"
                    f"  国家/地区：{data.get('country', '?')} {data.get('region', '')} {data.get('city', '')}\n"
                    f"  ISP：{data.get('connection', {}).get('isp', '?')}\n"
                    f"  时区：{data.get('timezone', {}).get('id', '?')}\n"
                    f"  经纬度：{data.get('latitude', '?')}, {data.get('longitude', '?')}"
                )
                results.append({
                    "title": f"IP {data.get('ip')} 归属地",
                    "url": "https://ipwho.is/",
                    "content": content,
                    "engine": "ipwhois",
                    "authority": 0.80,
                })

        # 时区
        if any(kw in query for kw in ["时区", "几点", "时间"]):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                    r = await c.get("http://worldtimeapi.org/api/timezone/Asia/Shanghai")
                    if r.status_code == 200:
                        data = r.json()
                        content = (
                            f"【当前时间】\n"
                            f"  时区：{data.get('timezone', '?')}\n"
                            f"  时间：{data.get('datetime', '?')}\n"
                            f"  星期：{data.get('day_of_week', '?')}"
                        )
                        results.append({
                            "title": "当前世界时间",
                            "url": "http://worldtimeapi.org/",
                            "content": content,
                            "engine": "worldtimeapi",
                            "authority": 0.85,
                        })
            except Exception:
                pass

        print(f"   [geo] 返回 {len(results)} 条", flush=True)
        return results[:limit]


_instance = None


def get_geo() -> GeoAdapter:
    global _instance
    if _instance is None:
        _instance = GeoAdapter()
    return _instance
