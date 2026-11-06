"""Meilisearch 客户端：文档检索 + 任务轮询 + filterable 配置"""
import os
import time
import asyncio
import httpx
from typing import List, Dict, Optional, Set


class MeiliClient:
    def __init__(self, url: str = None, api_key: str = None, timeout: float = 10.0):
        self.url = (url or os.environ.get("MEILI_URL", "http://127.0.0.1:7700")).rstrip("/")
        self.api_key = api_key or os.environ.get("MEILISEARCH_API_KEY", "")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._filterable_configured: Set[str] = set()

    async def _get(self):
        if self._client is None:
            h = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            self._client = httpx.AsyncClient(base_url=self.url, headers=h, timeout=self.timeout)
        return self._client

    # ---------- 任务 ----------
    async def _wait_task(self, task_uid: int, timeout_ms: int = 15000,
                         accept_errors: Set[str] = None) -> bool:
        """轮询 GET /tasks/{uid}；accept_errors 里的错误码视为成功"""
        accept_errors = accept_errors or set()
        c = await self._get()
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            try:
                r = await c.get(f"/tasks/{task_uid}")
                if r.status_code != 200:
                    print(f"   [meili] GET task HTTP {r.status_code}: {r.text[:150]}", flush=True)
                    return False
                body = r.json()
            except Exception as e:
                print(f"   [meili] 轮询异常: {type(e).__name__}: {e}", flush=True)
                return False
            status = body.get("status")
            if status == "succeeded":
                return True
            if status == "failed":
                err = body.get("error", {}) or {}
                code = err.get("code", "")
                if code in accept_errors:
                    return True
                print(f"   [meili] task {task_uid} failed: {err}", flush=True)
                return False
            await asyncio.sleep(0.3)
        print(f"   [meili] task {task_uid} 超时", flush=True)
        return False

    # ---------- filterable 配置 ----------
    async def _configure_filterable(self, index: str = "documents") -> bool:
        """配置 user_id 为可过滤字段（幂等）"""
        if index in self._filterable_configured:
            return True
        c = await self._get()
        try:
            r = await c.put(
                f"/indexes/{index}/settings/filterable-attributes",
                json=["user_id", "doc_id"])
            if r.status_code not in (200, 202):
                print(f"   [meili] filterable HTTP {r.status_code}: {r.text[:150]}", flush=True)
                return False
            try:
                body = r.json()
                uid = body.get("taskUid")
                if uid is not None:
                    await self._wait_task(uid)
            except Exception:
                pass
            self._filterable_configured.add(index)
            return True
        except Exception as e:
            print(f"   [meili] filterable 异常: {type(e).__name__}: {e}", flush=True)
            return False

    # ---------- 索引 ----------
    async def ensure_index(self, index: str = "documents") -> bool:
        c = await self._get()
        r = await c.post("/indexes", json={"uid": index, "primaryKey": "id"})
        if r.status_code == 409:
            # 已存在 → 直接配 filterable
            await self._configure_filterable(index)
            return True
        if r.status_code in (200, 201, 202):
            try:
                body = r.json()
            except Exception:
                await self._configure_filterable(index)
                return True
            task_uid = body.get("taskUid")
            if task_uid is not None:
                ok = await self._wait_task(
                    task_uid,
                    accept_errors={"index_already_exists"})
                if not ok:
                    return False
            await self._configure_filterable(index)
            return True
        print(f"   [meili] ensure_index HTTP {r.status_code}: {r.text[:150]}", flush=True)
        return False

    # ---------- 写入 ----------
    async def add_documents(self, docs: List[Dict], index: str = "documents") -> bool:
        if not docs:
            return True
        c = await self._get()
        ok_idx = await self.ensure_index(index)
        if not ok_idx:
            return False
        r = await c.post(f"/indexes/{index}/documents", json=docs)
        if r.status_code not in (200, 202):
            print(f"   [meili] add HTTP {r.status_code}: {r.text[:200]}", flush=True)
            return False
        try:
            task_uid = r.json().get("taskUid")
        except Exception:
            task_uid = None
        if task_uid is not None:
            ok = await self._wait_task(task_uid)
            if not ok:
                print(f"   [meili] add 任务 {task_uid} 未成功", flush=True)
            return ok
        return True

    # ---------- 检索 ----------
    async def search(self, query: str, user_id: str = None,
                     limit: int = 5, index: str = "documents") -> List[Dict]:
        if not query:
            return []
        c = await self._get()
        body = {"q": query, "limit": limit}
        if user_id:
            body["filter"] = f'user_id = "{user_id}"'
        try:
            r = await c.post(f"/indexes/{index}/search", json=body)
            if r.status_code != 200:
                print(f"   [meili] search HTTP {r.status_code}: {r.text[:150]}", flush=True)
                return []
            return r.json().get("hits", [])
        except Exception as e:
            print(f"   [meili] search 异常: {type(e).__name__}: {e}", flush=True)
            return []

    # ---------- 统计 ----------
    async def stats(self, index: str = "documents") -> Dict:
        c = await self._get()
        try:
            r = await c.get(f"/indexes/{index}/stats")
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}


_meili_client: Optional[MeiliClient] = None


def get_meili() -> MeiliClient:
    global _meili_client
    if _meili_client is None:
        _meili_client = MeiliClient()
    return _meili_client
