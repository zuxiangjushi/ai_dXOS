"""OpenViking 影子调用适配器

- 异步调用 OpenViking 的 /api/v1/search/find
- 记录对比数据（不注入 prompt）
- 用于评估 OpenViking vs Mem0 的实际价值
"""
import asyncio
import time
import json
import httpx
from datetime import datetime
from pathlib import Path

OV_URL = "http://127.0.0.1:1933"
LOG_FILE = "/ai/Memory-Gateway/logs/shadow_compare.log"
TIMEOUT = 5.0


def _count_mem0(mem0_result) -> int:
    """统计 Mem0 结果条数"""
    if not isinstance(mem0_result, dict):
        return 0
    results = mem0_result.get("results") or mem0_result.get("memories") or []
    return len(results) if isinstance(results, list) else 0


def _count_ov(ov_result) -> int:
    """统计 OpenViking 结果条数"""
    if not isinstance(ov_result, dict):
        return 0
    result = ov_result.get("result", ov_result)
    total = result.get("total")
    if isinstance(total, int):
        return total
    # fallback：分别统计
    count = 0
    for key in ("memories", "resources", "skills"):
        items = result.get(key, [])
        if isinstance(items, list):
            count += len(items)
    return count


def _extract_ov_top_hit(ov_result) -> dict:
    """取 OpenViking 最高分结果的关键字段"""
    if not isinstance(ov_result, dict):
        return {}
    result = ov_result.get("result", ov_result)
    all_hits = []
    for key in ("memories", "resources", "skills"):
        all_hits.extend(result.get(key, []) or [])
    if not all_hits:
        return {}
    top = max(all_hits, key=lambda h: h.get("score", 0))
    return {
        "uri": top.get("uri"),
        "score": round(top.get("score", 0), 4),
        "level": top.get("level"),
        "abstract_snippet": (top.get("abstract") or "")[:120],
    }


async def shadow_query(user_id: str, query: str, mem0_result) -> None:
    """影子调用 OpenViking，记录对比数据（异步，不阻塞主流程）"""
    if not query:
        return

    t0 = time.time()
    ov_result = None
    ov_error = None

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{OV_URL}/api/v1/search/find",
                json={
                    "query": query,
                    "target_uri": f"viking://user/{user_id}",
                    "context_type": "memory",
                    "node_limit": 5,
                },
            )
            if resp.status_code == 200:
                ov_result = resp.json()
            else:
                ov_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        ov_error = f"{type(e).__name__}: {e}"

    latency_ms = round((time.time() - t0) * 1000, 2)

    record = {
        "ts": datetime.now().isoformat(),
        "user_id": user_id,
        "query": query[:200],
        "mem0_count": _count_mem0(mem0_result),
        "ov_count": _count_ov(ov_result),
        "ov_latency_ms": latency_ms,
        "ov_error": ov_error,
        "ov_top_hit": _extract_ov_top_hit(ov_result) if ov_result else None,
    }

    try:
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[shadow] 写日志失败: {e}", flush=True)


def shadow_query_sync(user_id: str, query: str, mem0_result) -> None:
    """同步入口（如调用方不在 async 上下文，可创建 event loop）"""
    try:
        asyncio.create_task(shadow_query(user_id, query, mem0_result))
    except RuntimeError:
        # 无 event loop 时同步执行
        asyncio.run(shadow_query(user_id, query, mem0_result))
