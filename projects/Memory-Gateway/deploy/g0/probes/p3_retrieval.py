import random, time
from .base import ProbeResult, Timer

HARD = ["E1042", "max_context", "resolve_candidates", "embedding_status",
        "superseded_by", "AsyncQdrantClient", "vector_dim", "circuit_breakers"]
TPL = ["网关超时配置在 {} 中，默认 {}", "用户偏好使用 {} 作为向量库",
       "项目采用整洁架构四层：{}", "记忆冲突消解改为 {}", "显卡分时租约由 {} 仲裁"]

async def run(cfg):
    r = ProbeResult("P3", "一万条检索")
    try:
        from qdrant_client import AsyncQdrantClient, models as qm
    except ImportError:
        r.passed, r.reason = None, "qdrant-client 未安装"
        return r
    n = cfg["seed"]["count"]
    dim = cfg["expected_dim"]
    coll = cfg["stores"]["qdrant_collection"]
    qc = AsyncQdrantClient(url=cfg["stores"]["qdrant_url"])
    rnd = random.Random(42)
    try:
        if await qc.collection_exists(coll) and (await qc.count(coll, exact=True)).count < n:
            await qc.delete_collection(coll)
        if not await qc.collection_exists(coll):
            await qc.create_collection(coll,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
                on_disk_payload=True,
                hnsw_config=qm.HnswConfigDiff(m=16, ef_construct=200))
            await qc.create_payload_index(coll, field_name="workspace_id",
                field_schema=qm.PayloadSchemaType.KEYWORD)
            t0, batch = time.perf_counter(), []
            for i in range(n):
                hard = rnd.choice(HARD) if i % 5 == 0 else ""
                body = rnd.choice(TPL).format(hard or "v" + str(rnd.randint(1, 9)),
                                              rnd.randint(100, 8000))
                batch.append(qm.PointStruct(id=i,
                    vector=[rnd.random() for _ in range(dim)],
                    payload={"workspace_id": rnd.choice(["ws_a", "ws_b"]),
                             "user_id": "u" + str(rnd.randint(0, 50)),
                             "text": body + " #" + hard}))
                if len(batch) >= 1000:
                    await qc.upsert(coll, points=batch)
                    batch = []
            if batch:
                await qc.upsert(coll, points=batch)
            r.metrics["灌库秒数"] = round(time.perf_counter() - t0, 1)
        r.metrics["已索引"] = (await qc.count(coll, exact=True)).count
        t = Timer()
        filt = qm.Filter(must=[qm.FieldCondition(key="workspace_id",
                        match=qm.MatchValue(value="ws_a"))])
        for _ in range(200):
            await t.a(qc.query_points, coll,
                      query=[rnd.random() for _ in range(dim)], limit=32,
                      query_filter=filt)
        lim = cfg["budgets"]["retrieval_no_rerank_p95"]
        r.metrics["p50"], r.metrics["p95"] = t.p50, t.p95
        r.passed = t.p95 is not None and t.p95 <= lim
        r.reason = "向量检索 P95={}ms (门禁 {}，不含重排)".format(t.p95, lim)
        if not r.passed:
            r.hint = "查索引是否常驻内存 / 是否恰逢模型加载打满 IO"
    except Exception as e:
        r.passed, r.reason = False, "{}: {}".format(type(e).__name__, str(e)[:110])
        r.hint = "集合可能残留坏数据：删掉集合后重跑"
    return r
