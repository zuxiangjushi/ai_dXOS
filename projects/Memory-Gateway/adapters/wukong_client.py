"""悟空引擎客户端（全文检索内核）

注意：悟空是"索引内核"，不是"互联网搜索引擎"。
它需要配合"搜索驱动建索引"管线使用。
"""
import os
import httpx
from typing import List, Dict


class WukongClient:
    def __init__(self, url: str = None, timeout: float = 10.0):
        self.url = (url or os.environ.get(
            "WUKONG_URL", "http://127.0.0.1:8081")).rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, limit: int = 10) -> List[Dict]:
        """调用悟空搜索"""
        if not query or not query.strip():
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.url}/search",
                    json={"text": query, "output_offset": 0, "max_outputs": limit})
                if r.status_code != 200:
                    return []
                data = r.json()
        except Exception as e:
            print(f"   [wukong] 失败: {type(e).__name__}: {e}", flush=True)
            return []

        # 悟空返回格式 → 统一 raw 格式
        docs = data.get("docs", []) or data.get("results", [])
        out = []
        for d in docs[:limit]:
            out.append({
                "title": d.get("title", ""),
                "url": d.get("url", ""),
                "content": d.get("content", d.get("body", ""))[:400],
                "engine": "wukong",
            })
        return out

    async def index(self, doc_id: str, title: str, content: str,
                    url: str = "", **kwargs) -> bool:
        """写入索引（搜索驱动建索引用）"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.url}/index",
                    json={
                        "id": doc_id,
                        "title": title,
                        "content": content,
                        "url": url,
                        **kwargs,
                    })
                return r.status_code in (200, 201)
        except Exception:
            return False


_wukong = None


def get_wukong() -> WukongClient:
    global _wukong
    if _wukong is None:
        _wukong = WukongClient()
    return _wukong
