"""记忆访问日志：记录每次召回，支持统计"""
import os
import time
import asyncio
from typing import List, Dict, Optional


_pool = None


async def _get_pool():
    global _pool
    if _pool is None:
        import asyncpg
        dsn = os.environ.get("PG_PROBE_DSN", "postgresql://probe:probe@127.0.0.1:5433/probe")
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    return _pool


async def log_hits(user_id: str, query: str, source: str, hits: List[Dict]):
    """异步记录记忆命中（fire and forget）"""
    if not hits or not user_id:
        return
    try:
        pool = await _get_pool()
        ts = int(time.time())
        async with pool.acquire() as conn:
            for h in hits[:10]:
                mid = h.get("id") or h.get("memory_id")
                score = float(h.get("score") or 0)
                await conn.execute(
                    """INSERT INTO memory_access_log
                       (user_id, memory_id, source, query, score, ts)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    user_id, str(mid) if mid else None, source,
                    (query or "")[:500], score, ts)
    except Exception as e:
        print(f"   [access-log] 写入失败: {type(e).__name__}: {e}", flush=True)


async def get_user_stats(user_id: str, days: int = 7) -> Dict:
    """返回用户最近 N 天的记忆访问统计"""
    try:
        pool = await _get_pool()
        since = int(time.time()) - days * 86400
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                """SELECT count(*) FROM memory_access_log
                   WHERE user_id=$1 AND ts >= $2""", user_id, since)
            top = await conn.fetch(
                """SELECT memory_id, count(*) AS hits
                   FROM memory_access_log
                   WHERE user_id=$1 AND ts >= $2 AND memory_id IS NOT NULL
                   GROUP BY memory_id ORDER BY hits DESC LIMIT 10""",
                user_id, since)
            by_source = await conn.fetch(
                """SELECT source, count(*) AS n
                   FROM memory_access_log
                   WHERE user_id=$1 AND ts >= $2
                   GROUP BY source""", user_id, since)
        return {
            "user_id": user_id,
            "days": days,
            "total_hits": total or 0,
            "top_memories": [{"memory_id": r["memory_id"], "hits": r["hits"]} for r in top],
            "by_source": {r["source"]: r["n"] for r in by_source},
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
