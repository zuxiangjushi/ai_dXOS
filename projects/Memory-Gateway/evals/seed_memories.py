"""把评测集的 sessions 灌入 memories 表 + Qdrant（供 retrieval 档位检索）"""
import asyncio
import json
import sys
import time
import hashlib
import asyncpg
import httpx

sys.path.insert(0, "/ai/Memory-Gateway")

PG_DSN = "postgresql://probe:probe@127.0.0.1:5433/probe"
EMB_URL = "http://192.168.10.132:8003/embeddings"
EMB_MODEL = "models/bge-m3"

# 每个 persona 用独立的 workspace_id 隔离
def ws_for(persona):
    return "eval_" + hashlib.md5(persona.encode()).hexdigest()[:8]

async def embed(text):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(EMB_URL, json={"model": EMB_MODEL, "input": [text]})
        return r.json()["data"][0]["embedding"] if isinstance(r.json().get("data"), list) \
               else r.json()["data"][0]

async def embed_dense(text):
    """Infinity 原生返回格式：[[...]] 或 {data: [...]}"""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(EMB_URL, json={"model": EMB_MODEL, "input": [text]})
        body = r.json()
        if isinstance(body, list) and body and isinstance(body[0], list):
            return body[0]
        if isinstance(body, dict) and "data" in body:
            d = body["data"]
            if isinstance(d, list) and d:
                x = d[0]
                return x.get("embedding") if isinstance(x, dict) else x
        raise RuntimeError(f"无法解析向量: {body}")

async def main():
    samples = [json.loads(l) for l in open("evals/datasets/smoke_20.jsonl")]
    
    # 清空评测数据
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute("DELETE FROM memories WHERE workspace_id LIKE 'eval_%'")
        await conn.execute("DELETE FROM memory_index_outbox WHERE memory_id LIKE 'evalmem_%'")
        print("✅ 已清空旧评测数据")
    finally:
        await conn.close()
    
    # 灌入新数据
    total = 0
    for s in samples:
        ws = ws_for(s["persona"])
        uid = "u_eval"
        for i, sess in enumerate(s["sessions"]):
            content = sess["content"]
            memory_id = f"evalmem_{hashlib.md5((ws+content).encode()).hexdigest()[:16]}"
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            entity_key = f"proj.eval.item{i}"  # 简单策略，实际应按内容抽取
            
            # 写 PG
            conn = await asyncpg.connect(PG_DSN)
            try:
                await conn.execute(
                    """INSERT INTO memories 
                       (memory_id, user_id, workspace_id, content, content_hash,
                        entity_key, memory_class, tier, confidence, importance,
                        trust, origin_type, valid_from, created_at, updated_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                       ON CONFLICT (memory_id) DO NOTHING""",
                    memory_id, uid, ws, content, content_hash,
                    entity_key, "fact", "L3_SEMANTIC", 0.9, 0.7,
                    "trusted", "conversation", sess["ts"], sess["ts"], sess["ts"]
                )
            finally:
                await conn.close()
            
            # 写 Qdrant
            vec = await embed_dense(content)
            async with httpx.AsyncClient(timeout=10) as c:
                point_id = str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_DNS, "dxos:"+memory_id))
                await c.put(
                    f"http://localhost:6333/collections/gateway_memory_vector/points",
                    json={"points": [{
                        "id": point_id,
                        "vector": vec,
                        "payload": {
                            "memory_id": memory_id,
                            "workspace_id": ws,
                            "user_id": uid,
                            "content": content,
                            "is_deleted": False
                        }
                    }]}
                )
            total += 1
    
    print(f"✅ 灌入 {total} 条评测记忆")
    print(f"✅ 涉及 {len(set(ws_for(s['persona']) for s in samples))} 个 workspace")

if __name__ == "__main__":
    asyncio.run(main())
