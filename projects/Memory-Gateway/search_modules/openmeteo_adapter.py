"""Open-Meteo 环境数据适配器（v14.4修复）
- 修复：独立域名 air-quality-api.open-meteo.com
"""
import httpx
from typing import Dict, List


class OpenMeteoAdapter:
    def __init__(self):
        # ★ 修复：独立域名
        self.aq_base = "https://air-quality-api.open-meteo.com/v1/air-quality"
        self.geo_base = "https://geocoding-api.open-meteo.com/v1/search"
        self.timeout = 10.0
        self.ua = "Memory-Gateway/1.0"

    def is_openmeteo_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["空气质量", "AQI", "PM2.5", "PM10", "花粉", "环境数据", "空气污染"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_openmeteo_query(query):
            return []

        # 中文城市 → 英文（geocoding 支持中文，但用英文更稳）
        city = "Beijing"
        for zh, en in [("北京", "Beijing"), ("上海", "Shanghai"), ("广州", "Guangzhou"),
                       ("深圳", "Shenzhen"), ("重庆", "Chongqing"), ("成都", "Chengdu"),
                       ("杭州", "Hangzhou"), ("武汉", "Wuhan")]:
            if zh in query:
                city = en
                break

        print(f"   [openmeteo] 城市: {city}", flush=True)

        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                # 1. Geocoding
                r_geo = await c.get(self.geo_base, params={"name": city, "count": 1, "language": "zh"})
                if r_geo.status_code != 200:
                    print(f"   [openmeteo] geocoding HTTP {r_geo.status_code}", flush=True)
                    return []
                geo = r_geo.json().get("results", [])
                if not geo:
                    return []
                lat = geo[0].get("latitude")
                lon = geo[0].get("longitude")
                name_zh = geo[0].get("name", city)

                # 2. Air Quality（★ 修复：正确域名）
                r_aq = await c.get(self.aq_base, params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "pm10,pm2_5,us_aqi,alder_pollen,birch_pollen,grass_pollen",
                    "timezone": "Asia/Shanghai"
                })
                if r_aq.status_code != 200:
                    print(f"   [openmeteo] air-quality HTTP {r_aq.status_code}, {r_aq.text[:100]}", flush=True)
                    return []
                aq = r_aq.json().get("current", {})

                return [{
                    "title": f"[Open-Meteo] {name_zh} 空气质量",
                    "url": "https://open-meteo.com/en/docs/air-quality-api",
                    "content": (
                        f"[Open-Meteo] {name_zh} 实时环境数据\n"
                        f"  PM2.5：{aq.get('pm2_5', '?')} μg/m³\n"
                        f"  PM10：{aq.get('pm10', '?')} μg/m³\n"
                        f"  AQI (US)：{aq.get('us_aqi', '?')}\n"
                        f"  花粉(桤木)：{aq.get('alder_pollen', '?')}\n"
                        f"  花粉(桦木)：{aq.get('birch_pollen', '?')}\n"
                        f"  花粉(禾本科)：{aq.get('grass_pollen', '?')}\n"
                        f"  更新时间：{aq.get('time', '?')}"
                    ),
                    "engine": "openmeteo",
                    "authority": 0.88,
                }]
        except Exception as e:
            print(f"   [openmeteo] 失败: {type(e).__name__}: {e}", flush=True)
            return []


_instance = None
def get_openmeteo() -> OpenMeteoAdapter:
    global _instance
    if _instance is None:
        _instance = OpenMeteoAdapter()
    return _instance
