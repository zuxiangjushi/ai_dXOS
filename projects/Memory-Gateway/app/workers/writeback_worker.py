import asyncio
import os
import json
import time
import hashlib
import asyncpg
from contracts.t0_rules import classify_tier
from contracts.trust_policy import resolve_trust, can_enter_tier, is_trusted_for_longterm
from contracts.trust_policy import resolve_trust, can_enter_tier, get_ttl
from app.metrics import memory_write_total


class WritebackWorker:
    """
    异步写回消费者：
    - T0 规则层即时裁决（零模型调用）
    - 冲突消解通过 entity_key 取代（supersedes）
    - 索引更新异步入队（outbox）
    """
    def __init__(self, dsn, pilot, vector_store, repo, embed_client, max_concurrent=1):
        self.dsn = dsn
        self.pilot = pilot
        self.vector = vector_store
        self.repo = repo
        self.embed = embed_client
        self.max_concurrent = max_concurrent
        self._running = False
        self._tasks = []

    async def _conn(self):
        return await asyncpg.connect(self.dsn)

    async def start(self):
        self._running = True
        for i in range(self.max_concurrent):
            self._tasks.append(asyncio.create_task(self._worker_loop(i)))
        print(f"WritebackWorker 已启动，{self.max_concurrent} 个消费者", flush=True)

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        print("WritebackWorker 已停止", flush=True)

    async def _worker_loop(self, wid):
        while self._running:
            try:
                job = await self._claim_job()
                if not job:
                    await asyncio.sleep(2)
                    continue
                try:
                    await self._process_job(job)
                    await self._mark_done(job["id"])
                except Exception as e:
                    print(f"[Worker {wid}] 处理 job {job['id']} 失败: {type(e).__name__}: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    await self._mark_failed(job["id"], str(e)[:200])
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Worker {wid}] 循环异常: {e}", flush=True)
                await asyncio.sleep(1)

    async def _claim_job(self):
        conn = await self._conn()
        try:
            row = await conn.fetchrow(
                """UPDATE writeback_queue SET status='processing', claimed_at=$1
                   WHERE id = (SELECT id FROM writeback_queue 
                               WHERE status='pending' 
                               ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                   RETURNING *""",
                int(time.time())
            )
            return row
        finally:
            await conn.close()

    async def _process_job(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError(f"payload 格式异常: {type(payload)}")

        user_id = row["user_id"]
        workspace_id = row["workspace_id"]
        text = payload.get("content", "")
        if not text:
            print(f"[Worker] job {row['id']} 无 content，跳过", flush=True)
            return

        rule = classify_tier(text)
        op = rule.rule if rule.tier == "A" else "ADD"
        entity_key = payload.get("entity_key") or \
                     f"user.pref.{hashlib.md5(text[:20].encode()).hexdigest()[:8]}"        # ★ 信任分级
        origin_type = payload.get("origin_type", "conversation")
        trust = resolve_trust(origin_type)
        if not is_trusted_for_longterm(trust):
            print(f"[Worker] 拒绝: trust={trust.value} 不入长期记忆", flush=True)
            return

        # ★ 优先走 Mem0
        backend = os.environ.get("MEMORY_BACKEND", "mem0").lower()
        if backend == "mem0":
            try:
                from adapters.mem0_adapter import get_mem0
                mem0 = get_mem0()
                # 冲突检测：同 entity_key 的有效记忆，Mem0 metadata 带上冲突标记
                meta = {"workspace_id": workspace_id,
                        "origin_type": origin_type,
                        "source": "gateway",
                        "entity_key": entity_key,
                        "op": op}
                result = await mem0.add(
                    content=text,
                    user_id=user_id,
                    metadata=meta)
                if result and result.get("results"):
                    memory_write_total.labels(backend="mem0", status="ok").inc()
                    print(f"[Worker] Mem0 ADD: {len(result['results'])} 条 user={user_id}", flush=True)
                    return
                memory_write_total.labels(backend="mem0", status="empty").inc()
                print(f"[Worker] Mem0 返回空，降级到自研", flush=True)
            except Exception as e:
                print(f"[Worker] Mem0 异常: {type(e).__name__}: {e}", flush=True)
                memory_write_total.labels(backend="mem0", status="error").inc()

        # 降级：自研路径
        tier = payload.get("memory_tier") or "L3_SEMANTIC"
        if not can_enter_tier(trust, tier):
            print(f"[Worker] 自研拒绝: trust={trust.value} 不能进入 {tier}", flush=True)
            return
        print(f"[Worker] 自研写入: op={op} trust={trust.value} tier={tier} text={text[:40]}...", flush=True)
        await self._execute_write(user_id, workspace_id, text, op, entity_key, payload, trust, tier)
        memory_write_total.labels(backend="native", status="ok").inc()

    async def _execute_write(self, user_id, workspace_id, text, op, entity_key, payload, trust, tier):
        now = int(time.time())
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        memory_id = f"mem_{hashlib.md5(f'{workspace_id}{user_id}{text}{now}'.encode()).hexdigest()[:16]}"

        # ★★★ 关键修复：先获取连接，再进入事务上下文
        conn = await self._conn()
        try:
            async with conn.transaction():
                # ★ 幂等检查：完全相同内容的有效记忆已存在 → 直接跳过
                same_content = await conn.fetchval(
                    """SELECT memory_id FROM memories 
                       WHERE workspace_id=$1 AND user_id=$2 AND entity_key=$3 
                       AND content_hash=$4
                       AND superseded_by IS NULL AND is_deleted=FALSE""",
                    workspace_id, user_id, entity_key, content_hash
                )
                if same_content:
                    print(f"[Worker] 幂等跳过（已存在）: {same_content}", flush=True)
                    return

                existing = await conn.fetchrow(
                    """SELECT memory_id FROM memories 
                       WHERE workspace_id=$1 AND user_id=$2 AND entity_key=$3 
                       AND superseded_by IS NULL AND is_deleted=FALSE""",
                    workspace_id, user_id, entity_key
                )

                if op == "DELETE":
                    if existing:
                        await conn.execute(
                            """UPDATE memories SET superseded_by='__deleted__', valid_until=$1
                               WHERE memory_id=$2""",
                            now, existing["memory_id"]
                        )
                        await conn.execute(
                            """INSERT INTO memory_index_outbox (memory_id, op, created_at)
                               VALUES ($1, 'delete', $2)""",
                            existing["memory_id"], now
                        )
                        print(f"[Worker] DELETE: {existing['memory_id']}", flush=True)
                    return

                if existing and op == "UPDATE":
                    old_id = existing["memory_id"]
                    await conn.execute(
                        """UPDATE memories SET superseded_by=$1, valid_until=$2
                           WHERE memory_id=$3""",
                        memory_id, now, old_id
                    )
                    await conn.execute(
                        """INSERT INTO memories (memory_id, user_id, workspace_id, content, content_hash,
                           entity_key, memory_class, tier, confidence, importance, trust, origin_type,
                           valid_from, supersedes, created_at, updated_at)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                        memory_id, user_id, workspace_id, text, content_hash,
                        entity_key, "fact", tier, 0.7, 0.5,
                        trust.value, payload.get("origin_type", "conversation"), now, old_id, now, now
                    )
                    await conn.execute(
                        """INSERT INTO memory_index_outbox (memory_id, op, created_at)
                           VALUES ($1, 'upsert', $2)""",
                        memory_id, now
                    )
                    print(f"[Worker] UPDATE: {old_id} → {memory_id}", flush=True)
                else:
                    await conn.execute(
                        """INSERT INTO memories (memory_id, user_id, workspace_id, content, content_hash,
                           entity_key, memory_class, tier, confidence, importance, trust, origin_type,
                           valid_from, created_at, updated_at)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)""",
                        memory_id, user_id, workspace_id, text, content_hash,
                        entity_key, "fact", tier, 0.7, 0.5,
                        trust.value, payload.get("origin_type", "conversation"), now, now, now
                    )
                    await conn.execute(
                        """INSERT INTO memory_index_outbox (memory_id, op, created_at)
                           VALUES ($1, 'upsert', $2)""",
                        memory_id, now
                    )
                    print(f"[Worker] ADD: {memory_id}", flush=True)
        finally:
            await conn.close()

    async def _mark_done(self, job_id):
        conn = await self._conn()
        try:
            await conn.execute("UPDATE writeback_queue SET status='done' WHERE id=$1", job_id)
        finally:
            await conn.close()

    async def _mark_failed(self, job_id, reason):
        conn = await self._conn()
        try:
            await conn.execute(
                """UPDATE writeback_queue 
                   SET status=CASE WHEN attempts+1 >= 3 THEN 'failed' ELSE 'pending' END,
                       attempts=attempts+1, 
                       last_error=$2
                   WHERE id=$1""",
                job_id, reason[:200]
            )
        finally:
            await conn.close()
