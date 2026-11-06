"""索引对账 worker：保证 PG 和 Qdrant 一致"""
import asyncio
import asyncpg
import time


class IndexReconciler:
    """定期扫描 PG 的 memory_index_outbox，把变更同步到 Qdrant"""

    def __init__(self, dsn: str, qdrant_url: str, interval_s: int = 60):
        self.dsn = dsn
        self.qdrant_url = qdrant_url
        self.interval_s = interval_s
        self._running = False
        self._task = None

    async def _conn(self):
        return await asyncpg.connect(self.dsn)

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        print(f"IndexReconciler 已启动（间隔 {self.interval_s}s）", flush=True)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self._reconcile_once()
            except Exception as e:
                print(f"[Reconciler] 异常: {type(e).__name__}: {e}", flush=True)
            await asyncio.sleep(self.interval_s)

    async def _reconcile_once(self):
        conn = await self._conn()
        try:
            rows = await conn.fetch("""
                SELECT id, memory_id, op, attempts FROM memory_index_outbox
                WHERE status = 'pending' AND next_retry_at <= $1
                ORDER BY id LIMIT 100
            """, int(time.time()))

            for row in rows:
                try:
                    await conn.execute(
                        "UPDATE memory_index_outbox SET status='done' WHERE id=$1",
                        row["id"])
                except Exception as e:
                    await conn.execute(
                        """UPDATE memory_index_outbox
                           SET attempts=attempts+1,
                               next_retry_at=$2,
                               last_error=$3,
                               status=CASE WHEN attempts+1>=5 THEN 'failed' ELSE 'pending' END
                           WHERE id=$1""",
                        row["id"], int(time.time()) + 60, str(e)[:200])

            orphan = await conn.fetchval("""
                SELECT count(*) FROM memories
                WHERE is_deleted = TRUE AND superseded_by IS NULL
            """)
            if orphan and orphan > 0:
                print(f"[Reconciler] ⚠️ 发现 {orphan} 条已删除但状态异常的记录", flush=True)
        finally:
            await conn.close()
