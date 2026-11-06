"""修复：重建 Qdrant collection + 重灌数据（含写入检查）"""
import asyncio
import json
import hashlib
import uuid
import httpx

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
        raise RuntimeError(f"embed 格式异常: {body}")

async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        # 1. 删除旧 collection（忽略错误）
        r = await c.delete(f"{QDRANT}/collections/{COLL}")
        print(f"删除旧 collection: HTTP {r.status_code}")
        
        # 2. 创建 collection
        r = await c.put(
            f"{QDRANT}/collections/{COLL}",
            json={"vectors": {"size": DIM, "distance": "Cosine"}}
        )
        if r.status_code != 200:
            print(f"❌ 创建失败: {r.status_code} {r.text[:200]}")
            return
        print(f"✅ 创建 collection 成功 (维度={DIM}, 距离=Cosine)")
        
        # 3. 创建 workspace_id 索引
        r = await c.put(
            f"{QDRANT}/collections/{COLL}/index",
            json={"field_name": "workspace_id", "field_schema": "keyword"}
        )
        print(f"✅ workspace_id 索引: HTTP {r.status_code}")
        
        # 4. 读取样本
        samples = [json.loads(l) for l in open("evals/datasets/smoke_20.jsonl")]
        
        # 5. 逐条写入 Qdrant（含状态检查）
        total = 0
        failed = 0
        for s in samples:
            ws = ws_for(s["persona"])
            for i, sess in enumerate(s["sessions"]):
                content = sess["content"]
                memory_id = f"evalmem_{hashlib.md5((ws+content).encode()).hexdigest()[:16]}"
                vec = await embed(content)
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "dxos:" + memory_id))
                
                r = await c.put(
                    f"{QDRANT}/collections/{COLL}/points",
                    json={"points": [{
                        "id": point_id,
                        "vector": vec,
                        "payload": {
                            "memory_id": memory_id,
                            "workspace_id": ws,
                            "user_id": "u_eval",
                            "content": content,
                            "is_deleted": False,
                        }
                    }]}
                )
                if r.status_code != 200:
                    print(f"❌ 写入失败 [{memory_id}]: {r.status_code} {r.text[:100]}")
                    failed += 1
                else:
                    total += 1
        
        print(f"✅ 写入: {total} 条成功，{failed} 条失败")
        
        # 6. 验证
        r = await c.get(f"{QDRANT}/collections/{COLL}")
        if r.status_code == 200:
            count = r.json()["result"]["points_count"]
            print(f"✅ 验证: collection 现有 {count} 个点")
        
        # 7. 测试一次检索（无过滤）
        test_vec = await embed("向量库")
        r = await c.post(
            f"{QDRANT}/collections/{COLL}/points/search",
            json={"vector": test_vec, "limit": 3, "with_payload": True}
        )
        if r.status_code == 200:
            hits = r.json().get("result", [])
            print(f"✅ 测试检索: 返回 {len(hits)} 条")
            for h in hits[:3]:
                print(f"   - score={h['score']:.3f} ws={h['payload'].get('workspace_id')} "
                      f"content={h['payload'].get('content', '')[:40]}")
        else:
            print(f"⚠️ 检索测试: HTTP {r.status_code} {r.text[:200]}")

if __name__ == "__main__":
    asyncio.run(main())
