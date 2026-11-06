"""
URL 正文抓取（v10.5 P0）
- 输入：hits 列表
- 处理：并行抓取 Top N URL 的正文
- 输出：用正文替换 snippet
- 特性：超时、降级、可配置
"""
import asyncio
import os
import time
from typing import Dict, List, Optional

import httpx

try:
    import trafilatura
    TRAFILATURA_OK = True
except ImportError:
    TRAFILATURA_OK = False
    print("[web_fetcher] ⚠️ trafilatura 未安装", flush=True)


# ─── 配置 ───
MAX_CONTENT = int(os.environ.get("WEB_FETCH_MAX_CONTENT", "3000"))
TIMEOUT = float(os.environ.get("WEB_FETCH_TIMEOUT", "5.0"))
MAX_FETCH = int(os.environ.get("WEB_FETCH_MAX_URLS", "5"))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


async def _fetch_one(url: str, client: httpx.AsyncClient) -> Optional[str]:
    """抓取单个 URL 的正文"""
    if not url or not url.startswith("http"):
        return None

    try:
        r = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
        if r.status_code != 200:
            return None

        if not TRAFILATURA_OK:
            return None

        text = trafilatura.extract(
            r.text,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=True,
        )
        if not text:
            return None

        text = text.strip()
        if len(text) > MAX_CONTENT:
            text = text[:MAX_CONTENT] + "...(截断)"
        return text
    except Exception:
        return None


async def fetch_urls(urls: List[str]) -> Dict[str, str]:
    """并行抓取多个 URL，返回 {url: 正文}"""
    if not urls:
        return {}

    urls = urls[:MAX_FETCH]

    kwargs = {
        "headers": {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        "timeout": TIMEOUT,
        "follow_redirects": True,
    }

    result = {}
    t0 = time.time()

    try:
        async with httpx.AsyncClient(**kwargs) as client:
            tasks = [_fetch_one(u, client) for u in urls]
            contents = await asyncio.gather(*tasks, return_exceptions=True)

            for url, content in zip(urls, contents):
                if isinstance(content, str) and content:
                    result[url] = content
    except Exception as e:
        print(f"   [web_fetcher] 整体失败: {type(e).__name__}: {e}", flush=True)

    dt = time.time() - t0
    print(f"   [web_fetcher] {len(result)}/{len(urls)} 成功，耗时 {dt:.1f}s", flush=True)
    return result


async def fetch_and_enrich(hits: List[Dict]) -> List[Dict]:
    """主入口：抓取 Top N hits 的正文并替换"""
    if not hits:
        return hits

    top = hits[:MAX_FETCH]
    urls = [h.get("url", "") for h in top if h.get("url")]
    if not urls:
        return hits

    print(f"   [web_fetcher] 抓取 Top {len(urls)} URL", flush=True)
    contents = await fetch_urls(urls)

    if not contents:
        print(f"   [web_fetcher] ⚠️ 无 URL 抓取成功，保留 snippet", flush=True)
        return hits

    # 替换
    enriched = 0
    for h in hits:
        url = h.get("url", "")
        if url in contents:
            h["content"] = contents[url]
            h["_fetched"] = True
            enriched += 1

    print(f"   [web_fetcher] 已用正文替换 {enriched} 条 snippet", flush=True)
    return hits


# 单测
if __name__ == "__main__":
    async def main():
        test_urls = [
            "https://www.tianqi.com/chongqing/7/",
            "https://docs.python.org/3/whatsnew/3.13.html",
        ]
        contents = await fetch_urls(test_urls)
        for url, text in contents.items():
            print(f"\n=== {url} ===")
            print(text[:500])

    asyncio.run(main())
