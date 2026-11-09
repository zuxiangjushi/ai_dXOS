import os, requests, asyncio
from typing import List
from urllib.parse import quote

class WeatherAdapter:
    def __init__(self):
        self.api_key = os.getenv("QWEATHER_API_KEY", "4981d9a26173471b9b9fd6852eebc0d4")
        self.api_host = "devapi.qweather.com" 
        self.headers = {"User-Agent": "Mozilla/5.0"}
        self.proxies = {"http": "socks5h://127.0.0.1:12334", "https": "socks5h://127.0.0.1:12334"}
        
        # 省份 -> 省会映射
        self.province_to_city = {
            "湖北": "武汉", "湖南": "长沙", "广东": "广州", "广西": "南宁",
            "云南": "昆明", "贵州": "贵阳", "四川": "成都",
            "黑龙江": "哈尔滨", "吉林": "长春", "辽宁": "沈阳"
        }

    def is_configured(self) -> bool: return True
    def is_weather_query(self, query: str) -> bool: return True

    async def _fetch_single(self, city: str, sem: asyncio.Semaphore) -> str:
        async with sem:
            # 尝试和风
            try:
                geo_url = f"https://{self.api_host}/geo/v2/city/lookup?location={quote(city)}&key={self.api_key}"
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(None, lambda: requests.get(geo_url, headers=self.headers, proxies=self.proxies, timeout=5))
                if resp.status_code == 200 and resp.json().get("code") == "200":
                    loc_id = resp.json()["location"][0]["id"]
                    url = f"https://{self.api_host}/v7/weather/7d?location={loc_id}&key={self.api_key}"
                    resp_w = await loop.run_in_executor(None, lambda: requests.get(url, headers=self.headers, proxies=self.proxies, timeout=5))
                    if resp_w.status_code == 200:
                        w_data = resp_w.json()
                        days = w_data.get("daily", [])[:2]
                        day_strs = [f"{d.get('textDay')} {d.get('tempMin')}~{d.get('tempMax')}℃" for d in days]
                        return f"**{city}**：{'，'.join(day_strs)}"
            except Exception: pass

            # wttr.in 兜底
            try:
                url = f"https://wttr.in/{quote(city)}?format=j1&lang=zh-cn"
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(None, lambda: requests.get(url, timeout=10))
                if resp.status_code == 200:
                    data = resp.json()
                    days = data.get("weather", [])[:2]
                    day_strs = []
                    for d in days:
                        desc = d.get("hourly", [{}])[4].get("lang_zh", [{"value": "多云"}])[0].get("value", "多云")
                        day_strs.append(f"{desc} {d.get('mintempC')}~{d.get('maxtempC')}℃")
                    return f"**{city}**：{'，'.join(day_strs)}"
            except Exception: pass
            return f"**{city}**：天气数据获取失败"

    async def search_by_cities(self, cities: List[str]) -> str:
        if not cities: return ""
        # 省份转省会
        target_cities = [self.province_to_city.get(c, c) for c in cities]
        target_cities = list(dict.fromkeys(target_cities))[:10]
        
        sem = asyncio.Semaphore(5)
        tasks = [self._fetch_single(city, sem) for city in target_cities]
        results = await asyncio.gather(*tasks)
        
        valid = [r for r in results if "失败" not in r]
        return "\n\n".join(valid) if valid else ""

_weather_inst = None
def get_weather():
    global _weather_inst
    if _weather_inst is None: _weather_inst = WeatherAdapter()
    return _weather_inst
