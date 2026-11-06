"""把 20 角色 × 25 会话全部灌入 PG + Qdrant"""
import asyncio
import json
import hashlib
import uuid
import asyncpg
import httpx

PG_DSN = "postgresql://probe:probe@127.0.0.1:5433/probe"
QDRANT = "http://localhost:6333"
COLL = "gateway_memory_vector"
EMB_URL = "http://192.168.10.132:8003/embeddings"
EMB_MODEL = "models/bge-m3"
DIM = 1024

def ws_for(persona):
    return "eval_" + hashlib.md5(persona.encode()).hexdigest()[:8]

async def embed(text):
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
        raise RuntimeError("embed 格式异常")

async def main():
    personas = json.load(open("evals/datasets/personas_20.json"))

    # 清空
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute("DELETE FROM memories WHERE workspace_id LIKE 'eval_%'")
        await conn.execute("DELETE FROM memory_index_outbox WHERE memory_id LIKE 'evalmem_%'")
    finally:
        await conn.close()

    # 重建 collection
    async with httpx.AsyncClient(timeout=30) as c:
        await c.delete(f"{QDRANT}/collections/{COLL}")
        r = await c.put(f"{QDRANT}/collections/{COLL}",
                       json={"vectors": {"size": DIM, "distance": "Cosine"}})
        assert r.status_code == 200, r.text
        await c.put(f"{QDRANT}/collections/{COLL}/index",
                   json={"field_name": "workspace_id", "field_schema": "keyword"})
    print(f"✅ collection {COLL} 已重建")

    # 灌数据
    total_pg, total_qd, failed = 0, 0, 0
    async with httpx.AsyncClient(timeout=30) as c:
        for p in personas:
            persona = p["persona"]
            ws = ws_for(persona)
            for sess in p["sessions"]:
                content = sess["content"]
                # ★★★ 修复：memory_id 加入 ts，防止同 persona 内重复内容覆盖
                memory_id = f"evalmem_{hashlib.md5((ws+str(sess['ts'])+content).encode()).hexdigest()[:16]}"
                content_hash = hashlib.sha256(content.encode()).hexdigest()

                # PG
                conn = await asyncpg.connect(PG_DSN)
                try:
                    await conn.execute(
                        """INSERT INTO memories 
                           (memory_id, user_id, workspace_id, content, content_hash,
                            entity_key, memory_class, tier, confidence, importance,
                            trust, origin_type, valid_from, created_at, updated_at)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                           ON CONFLICT (memory_id) DO NOTHING""",
                        memory_id, "u_eval", ws, content, content_hash,
                        f"eval.item.{sess['ts']}", "fact", "L3_SEMANTIC", 0.9, 0.7,
                        "trusted", "conversation", sess["ts"], sess["ts"], sess["ts"]
                    )
                    total_pg += 1
                finally:
                    await conn.close()

                # Qdrant
                vec = await embed(content)
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "dxos:" + memory_id))
                r = await c.put(
                    f"{QDRANT}/collections/{COLL}/points",
                    json={"points": [{
                        "id": point_id, "vector": vec,
                        "payload": {"memory_id": memory_id, "workspace_id": ws,
                                    "user_id": "u_eval", "content": content,
                                    "is_deleted": False}
                    }]}
                )
                if r.status_code == 200:
                    total_qd += 1
                else:
                    failed += 1
                    print(f"❌ Qdrant 写入失败: {r.status_code} {r.text[:80]}")

    print(f"✅ PG: {total_pg} 条，Qdrant: {total_qd} 条，失败: {failed}")

if __name__ == "__main__":
    asyncio.run(main())
