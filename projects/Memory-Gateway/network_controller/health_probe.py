"""网络健康探测（直连 + 代理，30s 缓存）"""
import asyncio
import time
from typing import Dict
import httpx

PROXY = "socks5://127.0.0.1:12334"
CACHE_TTL = 30
_cache: Dict = {"ts": 0, "data": None}


async def _probe_url(url: str, use_proxy: bool = False, timeout: float = 8.0) -> Dict:
    t0 = time.time()
    try:
        kwargs = {"timeout": timeout, "follow_redirects": True}
        if use_proxy:
            kwargs["proxy"] = PROXY
        async with httpx.AsyncClient(**kwargs) as c:
            r = await c.get(url)
            return {"ok": r.status_code < 500,
                    "status": r.status_code,
                    "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "status": 0,
                "latency_ms": int((time.time() - t0) * 1000),
                "error": type(e).__name__}


async def probe_all(force: bool = False) -> Dict:
    now = time.time()
    if not force and _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    tasks = [
        _probe_url("https://www.baidu.com", use_proxy=False),
        _probe_url("https://www.so.com", use_proxy=False),
        _probe_url("https://www.google.com", use_proxy=True),
        _probe_url("https://en.wikipedia.org", use_proxy=True),
        _probe_url("https://duckduckgo.com", use_proxy=True),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    def _r(i):
        r = results[i]
        return r if isinstance(r, dict) else {"ok": False, "error": "exc"}

    baidu, so360, google, wiki, ddg = (_r(0), _r(1), _r(2), _r(3), _r(4))

    direct_ok = baidu["ok"] or so360["ok"]
    proxy_ok = google["ok"] or wiki["ok"] or ddg["ok"]
    proxy_latencies = [g.get("latency_ms", 0) for g in [google, wiki, ddg]
                       if g.get("ok") and g.get("latency_ms")]
    proxy_latency = max(proxy_latencies) if proxy_latencies else 0

    data = {
        "ts": int(now),
        "direct": {"ok": direct_ok, "baidu": baidu, "so360": so360},
        "proxy": {"ok": proxy_ok, "google": google, "wikipedia": wiki,
                  "duckduckgo": ddg, "latency_ms": proxy_latency},
    }
    _cache["ts"] = now
    _cache["data"] = data
    return data
