"""
免费新闻 API 适配器（v13.4）
- 5 源：百度热搜 / 华尔街见闻 / B站 / 今日头条 / 少数派
- 无需 API Key
"""
import asyncio
from typing import Dict, List

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


class NewsAdapter:
    def __init__(self):
        self.timeout = 8.0

    def is_news_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["新闻", "热点", "热搜", "头条", "快讯", "时事",
                    "最新消息", "发生了什么", "有什么新闻", "今天发生"]
        return any(kw in query for kw in keywords)

    async def _fetch_baidu(self) -> List[Dict]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                r = await c.get("https://top.baidu.com/api/board?platform=wise&tab=realtime")
                if r.status_code != 200:
                    return []
                d = r.json()
                # 路径：data.cards[0].content[0].content[]
                cards = d.get("data", {}).get("cards", [])
                items = []
                for card in cards:
                    for outer in card.get("content", []):
                        for item in outer.get("content", []):
                            word = item.get("word") or item.get("query", "")
                            if word:
                                items.append({
                                    "title": word,
                                    "url": item.get("url", "") or f"https://www.baidu.com/s?wd={word}",
                                    "content": f"百度热搜：{word}",
                                    "engine": "baidu_hot",
                                    "authority": 0.85,
                                })
                return items[:8]
        except Exception as e:
            print(f"   [news] 百度失败: {type(e).__name__}", flush=True)
            return []

    async def _fetch_wallstcn(self) -> List[Dict]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                r = await c.get(
                    "https://api-one.wallstcn.com/apiv1/content/lives",
                    params={"channel": "global-channel", "limit": 8},
                )
                if r.status_code != 200:
                    return []
                d = r.json()
                items = d.get("data", {}).get("items", [])
                results = []
                for item in items:
                    title = (item.get("title") or item.get("content_text") or "")[:100]
                    if not title:
                        continue
                    results.append({
                        "title": title,
                        "url": item.get("uri", "") or "https://wallstreetcn.com/live/global",
                        "content": f"财经快讯：{title}",
                        "engine": "wallstcn",
                        "authority": 0.88,
                    })
                return results[:8]
        except Exception as e:
            print(f"   [news] 华尔街见闻失败: {type(e).__name__}", flush=True)
            return []

    async def _fetch_bilibili(self) -> List[Dict]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                r = await c.get("https://api.bilibili.com/x/web-interface/search/square", params={"limit": 10})
                if r.status_code != 200:
                    return []
                d = r.json()
                items = d.get("data", {}).get("trending", {}).get("list", [])
                return [{
                    "title": item.get("keyword", ""),
                    "url": f"https://search.bilibili.com/all?keyword={item.get('keyword', '')}",
                    "content": f"B站热搜：{item.get('keyword', '')}",
                    "engine": "bilibili_hot",
                    "authority": 0.65,
                } for item in items[:8] if item.get("keyword")]
        except Exception as e:
            print(f"   [news] B站失败: {type(e).__name__}", flush=True)
            return []

    async def _fetch_toutiao(self) -> List[Dict]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                r = await c.get("https://www.toutiao.com/hot-event/hot-board/", params={"origin": "toutiao_pc"})
                if r.status_code != 200:
                    return []
                d = r.json()
                items = d.get("data", [])
                return [{
                    "title": item.get("Title", ""),
                    "url": item.get("Url", ""),
                    "content": f"今日头条热榜：{item.get('Title', '')}",
                    "engine": "toutiao_hot",
                    "authority": 0.85,
                } for item in items[:8] if item.get("Title")]
        except Exception as e:
            print(f"   [news] 今日头条失败: {type(e).__name__}", flush=True)
            return []

    async def _fetch_sspai(self) -> List[Dict]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                r = await c.get(
                    "https://sspai.com/api/v1/article/tag/page/get",
                    params={"limit": 5, "offset": 0, "tag": "热门文章"},
                )
                if r.status_code != 200:
                    return []
                d = r.json()
                items = d.get("data", [])
                return [{
                    "title": item.get("title", ""),
                    "url": f"https://sspai.com/post/{item.get('id', '')}",
                    "content": f"少数派：{item.get('title', '')} — {item.get('summary', '')[:80]}",
                    "engine": "sspai",
                    "authority": 0.75,
                } for item in items if item.get("title")]
        except Exception as e:
            print(f"   [news] 少数派失败: {type(e).__name__}", flush=True)
            return []

    async def search(self, query: str, limit: int = 15) -> List[Dict]:
        if not self.is_news_query(query):
            return []
        print(f"   [news] 触发新闻特化（5 源）", flush=True)

        tasks = [
            self._fetch_baidu(),
            self._fetch_wallstcn(),
            self._fetch_bilibili(),
            self._fetch_toutiao(),
            self._fetch_sspai(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_hits = []
        for r in results:
            if isinstance(r, list):
                all_hits.extend(r)

        # 按 title 去重
        seen = set()
        unique = []
        for h in all_hits:
            t = h.get("title", "")
            if t and t not in seen:
                seen.add(t)
                unique.append(h)

        # 统计来源
        from collections import Counter
        dist = Counter(h.get("engine", "?") for h in unique)
        print(f"   [news] 聚合 {len(unique)} 条 | 来源: {dict(dist)}", flush=True)

        return unique[:limit]


_instance = None


def get_news() -> NewsAdapter:
    global _instance
    if _instance is None:
        _instance = NewsAdapter()
    return _instance


if __name__ == "__main__":
    async def main():
        n = get_news()
        hits = await n.search("今天有什么新闻")
        print(f"\n共 {len(hits)} 条：")
        for h in hits[:10]:
            print(f"  [{h['engine']}] {h['title'][:60]}")

    asyncio.run(main())
