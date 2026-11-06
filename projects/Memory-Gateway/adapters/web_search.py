"""
Web 搜索适配器：SearXNG（主）→ Bing Direct（fallback）→ 网关注入

v6.2 变更：
- 保留 SearXNG 调用逻辑
- 增加 Bing Direct fallback
- 对外接口不变（get_web_search().search()）
- Bing Provider 只负责"召回"，Trust/Quality/Citation 由上层处理
"""
import os
import re
import logging
import datetime
from typing import List, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# SearXNG 成功阈值：少于这个数就 fallback 到 Bing
MIN_SEARXNG_RESULTS = 3


class WebSearchClient:
    def __init__(self, url: str = None, timeout: float = 30.0,
                 enable_bing_fallback: bool = True):
        self.url = (url or os.environ.get("SEARXNG_URL",
                    "http://127.0.0.1:3180")).rstrip("/")
        self.timeout = timeout
        # fallback 开关（可通过环境变量控制）
        env_flag = os.environ.get("BING_FALLBACK_ENABLED", "true").lower()
        self.enable_bing_fallback = enable_bing_fallback and env_flag in ("true", "1", "yes")

        # 延迟加载 Bing Provider
        self._bing = None

    def _get_bing(self):
        if self._bing is None:
            try:
                from adapters.bing_search import get_bing_search
                self._bing = get_bing_search()
            except Exception as e:
                logger.warning(f"[web_search] Bing Provider 加载失败：{e}")
                self._bing = False  # 标记不可用
        return self._bing

    async def search(self, query: str, limit: int = 5,
                     freshness: str = "normal") -> List[Dict]:
        """主入口：SearXNG 优先，失败/结果少时 fallback 到 Bing
        v6.3 Phase 2：新增 freshness 参数（realtime/recent/normal/historical）
        """
        if not query or not query.strip():
            return []

        # ─── v6.4: 先清洗再优化 ───
        query = self._sanitize_query(query)
        query = self._optimize_freshness(query)

        # ─── 尝试 SearXNG ───
        results = await self._try_searxng(query, limit, freshness=freshness)

        # ─── 结果不足，fallback Bing ───
        if len(results) < MIN_SEARXNG_RESULTS and self.enable_bing_fallback:
            print(f"   [web_search] SearXNG 返回 {len(results)} 条 < {MIN_SEARXNG_RESULTS}，fallback Bing", flush=True)
            bing_results = self._try_bing(query, limit)
            if bing_results:
                # 合并去重（Bing 优先，因为更可靠）
                results = self._merge_dedupe(bing_results, results)
                print(f"   [web_search] Bing 返回 {len(bing_results)} 条，合并后 {len(results)} 条", flush=True)

        return results[:limit]

    def _sanitize_query(self, query: str) -> str:
        """v6.4: 清洗查询里的特殊字符，避免 Bing HTTP 400"""
        import re
        if not query:
            return query
        # 去 emoji
        q = re.sub(r'[\U0001F300-\U0001F9FF]', '', query)
        # 去制表符/框线符号
        q = re.sub(r'[\u2500-\u257F]', '', q)
        # 去常见装饰符号
        q = re.sub(r'[●○◆◇■□▲△★☆]', '', q)
        # 去连续空白
        q = re.sub(r'\s+', ' ', q).strip()
        # 限长（Bing 对超长查询返回 400）
        return q[:200]

    def _optimize_freshness(self, query: str) -> str:
        """时间敏感查询优化（保留原逻辑）"""
        today = datetime.date.today()
        if re.search(r"今天|今日|现在|当前|最新|实时|本周|这周", query):
            date_str = f"{today.year}年{today.month}月{today.day}日"
            optimized = re.sub(r"今天|今日", date_str, query)
            if optimized != query:
                print(f"   [web_search] 查询优化: {query} → {optimized}", flush=True)
                return optimized
        return query

    async def _try_searxng(self, query: str, limit: int,
                            freshness: str = "normal") -> List[Dict]:
        """调用 SearXNG JSON API（v6.3 Phase 2：支持 time_range）"""
        params = {
            "q": query,
            "format": "json",
            "language": "zh-CN",
            "safesearch": 0,
        }
        # ★ freshness → time_range 映射
        _tr = {"realtime": "day", "recent": "week",
               "historical": "year"}.get(freshness)
        if _tr:
            params["time_range"] = _tr
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(f"{self.url}/search", params=params)
                if r.status_code != 200:
                    print(f"   [web_search] SearXNG HTTP {r.status_code}", flush=True)
                    return []
                data = r.json()
        except Exception as e:
            print(f"   [web_search] SearXNG 失败: {type(e).__name__}: {e}", flush=True)
            return []

        results = data.get("results", [])
        out = []
        for r in results[:limit]:
            out.append({
                "title": (r.get("title") or "")[:100],
                "url": r.get("url", ""),
                "content": (r.get("content") or "")[:400],
                "engine": r.get("engine", ""),
            })
        return out

    def _try_bing(self, query: str, limit: int) -> List[Dict]:
        """调用 Bing Direct Provider（同步库，转成同样格式）"""
        bing = self._get_bing()
        if not bing:
            return []
        try:
            r = bing.search(query, max_results=limit)
            if r.get("status") != "ok":
                print(f"   [web_search] Bing status={r.get('status')}", flush=True)
                return []
            # 转换为 web_search 的统一格式
            out = []
            for item in r.get("results", []):
                out.append({
                    "title": (item.get("title") or "")[:100],
                    "url": item.get("url", ""),
                    "content": (item.get("snippet") or "")[:400],
                    "engine": "bing",
                })
            return out
        except Exception as e:
            print(f"   [web_search] Bing 异常: {type(e).__name__}: {e}", flush=True)
            return []

    def _merge_dedupe(self, primary: List[Dict], secondary: List[Dict]) -> List[Dict]:
        """合并去重：primary 优先，URL 去重"""
        seen = set()
        out = []
        for r in primary + secondary:
            url = r.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(r)
        return out


_client: Optional[WebSearchClient] = None


def get_web_search() -> WebSearchClient:
    global _client
    if _client is None:
        _client = WebSearchClient()
    return _client


if __name__ == "__main__":
    import asyncio

    async def main():
        ws = get_web_search()
        for q in ["重庆今天天气", "Qdrant 向量库", "SGLang NCCL error"]:
            print(f"\n查询: {q}")
            results = await ws.search(q, limit=5)
            print(f"  结果数: {len(results)}")
            for r in results[:3]:
                print(f"  · [{r['engine']}] {r['title'][:60]}")
                print(f"    {r['url'][:80]}")

    asyncio.run(main())
