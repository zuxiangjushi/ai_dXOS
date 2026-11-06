"""Discovery 层：多源聚合（SearXNG + Wukong + External）

设计原则：
- 不改动现有 web_search.py，本模块作为"契约适配器"
- Provider 是可插拔的：新增来源只需注册一个函数
- 返回统一的 Source 契约
"""
import os
import sys
import hashlib
import time

# 独立测试时使用
if __name__ == "__main__" and "/ai/Memory-Gateway" not in sys.path:
    sys.path.insert(0, "/ai/Memory-Gateway")
from typing import Callable, List, Dict
from contracts.research import Source, QueryPlan


class DiscoveryAggregator:
    """多源发现聚合器"""

    def __init__(self):
        # 注册 Providers（可插拔）
        self._providers: list[tuple[str, Callable]] = [
            ("searxng", self._search_searxng),
        ]
        # Meilisearch 网页索引（自建索引，默认为启用）
        if os.environ.get("MEILI_WEB_ENABLED", "true").lower() == "true":
            self._providers.append(("meili_web", self._search_meili_web))
        # 悟空（如已部署，通过环境变量启用）
        if os.environ.get("WUKONG_ENABLED", "false").lower() == "true":
            self._providers.append(("wukong", self._search_wukong))

    async def discover(self, plan: QueryPlan, exclude_providers: list = None) -> dict:
        """执行多源发现

        返回：
        {
            "sources": [Source, ...],
            "raw":     [dict, ...],   # 兼容旧格式（_recall_web 用）
            "distribution": {"searxng": N, "wukong": M},
            "errors": [str, ...],
        }
        """
        import asyncio

        all_sources: List[Source] = []
        all_raw: List[Dict] = []
        distribution: Dict[str, int] = {}
        errors: List[str] = []

        # 用第一个 query 为主（多 query 是 Phase 2 增强）
        # ★ v6.6: 支持多 query 展开
        _queries_to_run = plan.queries if plan.queries else [""]
        _queries_to_run = [q for q in _queries_to_run if q.strip()][:3]
        primary_query = _queries_to_run[0] if _queries_to_run else ""

        # 并行调用所有 provider（可排除指定 provider）
        _exclude = set(exclude_providers or [])
        tasks = []
        for _q in _queries_to_run:
            for name, fn in self._providers:
                if name in _exclude:
                    print(f"   [discovery] 跳过 {name}（freshness 策略）", flush=True)
                    continue
                tasks.append(self._call_provider(name, fn, _q,
                                             plan.max_candidates))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                errors.append(f"{type(r).__name__}: {str(r)[:100]}")
                continue
            name, sources, raw = r
            distribution[name] = distribution.get(name, 0) + len(sources)  # ★ v6.6.5 累加
            all_sources.extend(sources)
            all_raw.extend(raw)

        # 按 URL 去重（保留首个）
        seen = set()
        dedup_sources = []
        dedup_raw = []
        for s, r in zip(all_sources, all_raw):
            if s.url in seen:
                continue
            seen.add(s.url)
            dedup_sources.append(s)
            dedup_raw.append(r)

        # ★ 搜索驱动建索引（同步等待，确保写入；后续可优化为队列）
        if dedup_sources:
            try:
                await self._index_results_async(dedup_sources, dedup_raw)
            except Exception as e:
                print(f"   [discovery] 索引异常: {type(e).__name__}: {e}", flush=True)

        return {
            "sources": dedup_sources,
            "raw": dedup_raw,
            "distribution": distribution,
            "errors": errors,
        }

    async def _call_provider(self, name, fn, query, limit):
        """调用单个 provider，返回 (name, sources, raw)"""
        try:
            raw_list = await fn(query, limit)
            sources = [self._raw_to_source(r, name) for r in raw_list]
            return (name, sources, raw_list)
        except Exception as e:
            raise

    async def _index_results_async(self, sources, raw_list):
        """后台把搜索结果写入 Meili web_index（搜索驱动建索引）"""
        try:
            from adapters.meili_web_index import get_meili_web
            idx = get_meili_web()
            n_ok = 0
            for s, r in zip(sources, raw_list):
                content = r.get("content", "") or r.get("snippet", "")
                if not content:
                    continue
                ok = await idx.index_document(
                    source_id=s.source_id,
                    url=s.url,
                    title=s.title,
                    content=content,
                    domain=s.domain,
                    published_at=s.published_at or 0,
                )
                if ok:
                    n_ok += 1
            if n_ok > 0:
                print(f"   [discovery] 索引 {n_ok} 条到 web_index", flush=True)
        except Exception as e:
            print(f"   [discovery] 索引失败: {type(e).__name__}: {e}", flush=True)

    # ---------- Provider 实现 ----------
    async def _search_searxng(self, query: str, limit: int,
                               freshness: str = "normal") -> List[Dict]:
        """SearXNG provider（v6.3 Phase 2：支持 freshness 传递）"""
        from adapters.web_search import get_web_search
        ws = get_web_search()
        return await ws.search(query, limit=limit, freshness=freshness)

    async def _search_meili_web(self, query: str, limit: int) -> List[Dict]:
        """Meilisearch 网页索引 provider（自建索引）"""
        try:
            from adapters.meili_web_index import get_meili_web
            return await get_meili_web().search(query, limit=limit)
        except Exception:
            return []

    async def _search_wukong(self, query: str, limit: int) -> List[Dict]:
        """悟空 provider（待接入，当前返回空）"""
        try:
            from adapters.wukong_client import get_wukong
            wk = get_wukong()
            return await wk.search(query, limit=limit)
        except Exception:
            return []

    # ---------- 格式转换 ----------
    def _raw_to_source(self, raw: dict, provider: str) -> Source:
        """SearXNG/悟空 raw 格式 → Source 契约"""
        url = raw.get("url", "")
        domain = ""
        if url:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
            except Exception:
                pass

        title = raw.get("title", "")[:200]

        # 稳定 source_id
        seed = f"{provider}:{url}"
        h = hashlib.sha1(seed.encode()).hexdigest()[:12]
        source_id = f"src_{h}"

        return Source(
            source_id=source_id,
            url=url,
            domain=domain,
            title=title,
            retrieved_at=int(time.time()),
            authority_score=self._estimate_authority(domain),
            language="zh-CN",
            content_hash=hashlib.sha1(
                (raw.get("content") or "").encode()).hexdigest()[:16],
            trust_level=self._estimate_trust(domain),
        )

    def _estimate_authority(self, domain: str) -> float:
        """域名权威性评分（v6.3 Phase 2：7 级精细化）"""
        if not domain:
            return 0.30
        d = domain.lower()

        # L1: 政府/教育/学术
        if d.endswith(".gov.cn") or d.endswith(".gov"):
            return 1.00
        if d.endswith(".edu.cn") or d.endswith(".edu") or d.endswith(".ac.cn"):
            return 0.95

        # L2: 官方技术站/学术库
        for k in ("github.com", "stackoverflow.com", "arxiv.org",
                  "python.org", "microsoft.com", "openai.com",
                  "huggingface.co", "pytorch.org", "nvidia.com"):
            if k in d:
                return 0.90

        # L3: 权威媒体
        for k in ("xinhuanet.com", "people.com.cn", "cctv.com",
                  "chinanews.com.cn", "cnr.cn", "gmw.cn"):
            if k in d:
                return 0.92

        # L4: 主流门户
        for k in ("163.com", "qq.com", "sina.com.cn", "sohu.com",
                  "ifeng.com", "thepaper.cn", "yicai.com"):
            if k in d:
                return 0.78

        # L5: 百科
        for k in ("wikipedia.org", "baike.baidu.com", "baike.com"):
            if k in d:
                return 0.72

        # L6: 技术社区
        for k in ("csdn.net", "juejin.cn", "zhihu.com",
                  "segmentfault.com", "cnblogs.com", "oschina.net",
                  "v2ex.com", "reddit.com", "medium.com"):
            if k in d:
                return 0.65

        # L7: 搜索引擎页面（低权威）
        for k in ("so.com", "sogou.com", "bing.com"):
            if k in d:
                return 0.45

        return 0.50

    def _estimate_trust(self, domain: str) -> str:
        """信任级别（v6.3 Phase 2：与 authority 一致）"""
        if not domain:
            return "unknown"
        d = domain.lower()
        if d.endswith(".gov.cn") or d.endswith(".edu.cn") or d.endswith(".ac.cn"):
            return "official"
        for k in ("github.com", "stackoverflow.com", "arxiv.org",
                  "python.org", "microsoft.com", "openai.com", "huggingface.co"):
            if k in d:
                return "official"
        for k in ("xinhuanet.com", "people.com.cn", "cctv.com",
                  "chinanews.com.cn", "163.com", "qq.com", "sina.com.cn"):
            if k in d:
                return "media"
        for k in ("csdn.net", "juejin.cn", "zhihu.com", "segmentfault.com",
                  "cnblogs.com", "github.com", "reddit.com"):
            if k in d:
                return "community"
        for k in ("weibo.com", "xiaohongshu.com", "douyin.com"):
            if k in d:
                return "ugc"
        return "unknown"


# 单例
_aggregator = None


def get_discovery() -> DiscoveryAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = DiscoveryAggregator()
    return _aggregator


if __name__ == "__main__":
    import asyncio
    from contracts.research import QueryPlan

    async def main():
        d = get_discovery()
        plan = QueryPlan(
            plan_id="test",
            need_web_search=True,
            reason="test",
            queries=["重庆今天气温"],
            max_candidates=5,
        )
        result = await d.discover(plan)
        print(f"来源数: {len(result['sources'])}")
        print(f"分布: {result['distribution']}")
        for s in result["sources"][:3]:
            print(f"  · {s.source_id} | {s.domain} | auth={s.authority_score} | {s.title[:40]}")

    asyncio.run(main())
