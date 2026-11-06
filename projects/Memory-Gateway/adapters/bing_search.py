"""
Bing Direct Search Provider
最小实现：只做 3 件事——接收 query、请求 Bing、提取 title/url/snippet。
不做：Trust、Quality、Citation、Query 改写、RAG、Memory。
这些全部由 v6.1 上层流水线处理。
"""
import os
import time
import logging
from typing import List, Dict, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BING_URL = "https://www.bing.com/search"
DEFAULT_TIMEOUT = 15
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/155.0.0.0 Safari/537.36"
)


class BingSearch:
    """Bing Direct 搜索 Provider"""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": DEFAULT_UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def search(self, query: str, max_results: int = 10) -> Dict:
        """
        返回统一格式：
        {
            "provider": "bing",
            "query": "...",
            "status": "ok" | "degraded" | "error",
            "result_count": N,
            "latency_ms": M,
            "results": [{"title","url","snippet","engine"}]
        }
        """
        t0 = time.time()
        try:
            url = f"{BING_URL}?q={quote(query)}"
            r = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=True,
            )
            latency = int((time.time() - t0) * 1000)

            if r.status_code != 200:
                logger.warning(f"[bing] HTTP {r.status_code}")
                return self._err(query, f"HTTP {r.status_code}", latency)

            soup = BeautifulSoup(r.text, "html.parser")
            results = self._parse(soup, max_results)

            if len(results) < 3:
                logger.warning(f"[bing] 只解析到 {len(results)} 条")
                return {
                    "provider": "bing",
                    "query": query,
                    "status": "degraded",
                    "result_count": len(results),
                    "latency_ms": latency,
                    "results": results,
                }

            return {
                "provider": "bing",
                "query": query,
                "status": "ok",
                "result_count": len(results),
                "latency_ms": latency,
                "results": results,
            }

        except requests.Timeout:
            return self._err(query, "timeout", int((time.time() - t0) * 1000))
        except Exception as e:
            logger.exception(f"[bing] 异常：{e}")
            return self._err(query, str(e), int((time.time() - t0) * 1000))

    def _parse(self, soup: BeautifulSoup, max_results: int) -> List[Dict]:
        """解析 Bing HTML：li.b_algo 容器"""
        out = []
        for item in soup.select("li.b_algo"):
            try:
                a = item.select_one("h2 a")
                if not a:
                    continue
                title = a.get_text(" ", strip=True)
                url = a.get("href", "").strip()
                if not title or not url:
                    continue

                # snippet 可能在不同位置
                p = (item.select_one(".b_caption p")
                     or item.select_one("p")
                     or item.select_one(".b_algoSlug"))
                snippet = p.get_text(" ", strip=True) if p else ""

                out.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet[:500],
                    "engine": "bing",
                })
                if len(out) >= max_results:
                    break
            except Exception:
                continue
        return out

    def _err(self, query: str, msg: str, latency: int) -> Dict:
        return {
            "provider": "bing",
            "query": query,
            "status": "error",
            "error": msg,
            "result_count": 0,
            "latency_ms": latency,
            "results": [],
        }


# 单例
_instance: Optional[BingSearch] = None

def get_bing_search() -> BingSearch:
    global _instance
    if _instance is None:
        _instance = BingSearch()
    return _instance
