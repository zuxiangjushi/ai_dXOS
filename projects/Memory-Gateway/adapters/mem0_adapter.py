"""Mem0 适配器：封装 Mem0 REST API"""
import os
import httpx
from typing import List, Dict, Optional

MEM0_URL = os.environ.get("MEM0_URL", "http://127.0.0.1:8888")
MEM0_ADMIN_KEY = os.environ.get("MEM0_ADMIN_KEY", "")


class Mem0Client:
    def __init__(self, base_url: str = None, api_key: str = None, timeout: float = 60.0):
        self.base = (base_url or MEM0_URL).rstrip("/")
        self.key = api_key or MEM0_ADMIN_KEY
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _new_client(self) -> httpx.AsyncClient:
        """每次请求新建 client，避免 Mem0 容器重建后连接池 stale"""
        return httpx.AsyncClient(
            base_url=self.base,
            headers={"X-API-Key": self.key} if self.key else {},
            timeout=self.timeout,
        )

    async def close(self):
        """兼容旧调用（无实际作用）"""
        pass

    async def health(self) -> bool:
        try:
            async with self._new_client() as c:
                r = await c.get("/docs", timeout=3.0)
                return r.status_code == 200
        except Exception:
            return False

    async def add(self, content: str, user_id: str, metadata: Dict = None) -> Optional[Dict]:
        """添加记忆：Mem0 内部完成 LLM 抽取 + 向量化 + 存储"""
        if not content or not content.strip():
            return None
        try:
            payload = {"messages": [{"role": "user", "content": content}], "user_id": user_id}
            if metadata:
                payload["metadata"] = metadata
            async with self._new_client() as c:
                r = await c.post("/memories", json=payload)
                if r.status_code in (200, 201):
                    return r.json()
                print(f"   [Mem0] add HTTP {r.status_code}: {r.text[:120]}", flush=True)
                return None
        except Exception as e:
            print(f"   [Mem0] add 异常: {type(e).__name__}: {e}", flush=True)
            return None

    async def search(self, query: str, user_id: str, limit: int = 5) -> List[Dict]:
        """检索记忆：Mem0 内部做多信号融合"""
        if not query or not query.strip():
            return []
        try:
            async with self._new_client() as c:
                r = await c.post("/search", json={
                    "query": query, "user_id": user_id, "limit": limit})
                if r.status_code == 200:
                    return r.json().get("results", [])
                print(f"   [Mem0] search HTTP {r.status_code}: {r.text[:120]}", flush=True)
                return []
        except Exception as e:
            print(f"   [Mem0] search 异常: {type(e).__name__}: {e}", flush=True)
            return []


_mem0_client: Optional[Mem0Client] = None

def get_mem0() -> Mem0Client:
    global _mem0_client
    if _mem0_client is None:
        _mem0_client = Mem0Client()
    return _mem0_client
