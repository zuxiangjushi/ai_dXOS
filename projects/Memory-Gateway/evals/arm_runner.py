"""三档对照运行器：none / memory_only / memory+retrieval"""
import os
import json
import time

def get_key():
    try:
        with open("/ai/ai_dxos/secrets/keys.conf") as f:
            for line in f:
                if line.startswith("KEY_qwen3_32b="):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return os.environ.get("PILOT_KEY_M00")

async def call_model(messages, model="38FN_Q4", max_tokens=200, max_retries=3):
    import litellm
    import asyncio
    litellm.api_base = "http://192.168.10.132:9980"
    api_key = get_key()
    
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = await litellm.acompletion(
                model=f"openai/{model}",
                messages=messages,
                max_tokens=max_tokens,
                temperature=0,
                api_key=api_key,
                timeout=300,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s
                print(f"   ⚠️ APIError 第{attempt+1}次，{wait}s 后重试", flush=True)
                await asyncio.sleep(wait)
    raise last_err

def build_context_none(sample):
    """档位 1：无记忆"""
    return [{"role": "user", "content": sample["question"]}]

def build_context_memory_only(sample):
    """档位 2：全部 session 拼接（暴力满窗）"""
    sessions = sample["sessions"]
    history = "\n".join(f"[{s['ts']}] {s['content']}" for s in sessions)
    return [
        {"role": "user", "content": f"以下是历史对话:\n{history}\n\n问题: {sample['question']}"}
    ]

def build_context_memory_retrieval(sample, recall_results):
    """档位 3：检索 top_k 记忆"""
    if not recall_results:
        return [{"role": "user", "content": sample["question"]}]
    hits = "\n".join(f"- {m.get('content', '')}" for m in recall_results[:5])
    return [
        {"role": "user", "content": f"相关记忆:\n{hits}\n\n问题: {sample['question']}"}
    ]

# ===== retrieval 档位 =====
import hashlib

def ws_for(persona):
    return "eval_" + hashlib.md5(persona.encode()).hexdigest()[:8]

async def retrieval_recall(persona, question, top_k=5):
    """调用 Qdrant + 关键词检索（简化版：只用向量）"""
    import httpx
    ws = ws_for(persona)
    
    # 1. 查询向量化
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("http://192.168.10.132:8003/embeddings",
                        json={"model": "models/bge-m3", "input": [question]})
        body = r.json()
        if isinstance(body, list) and isinstance(body[0], list):
            qv = body[0]
        else:
            qv = body["data"][0].get("embedding") if isinstance(body["data"][0], dict) else body["data"][0]
    
    # 2. Qdrant 检索
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"http://localhost:6333/collections/gateway_memory_vector/points/search",
            json={
                "vector": qv,
                "limit": top_k,
                "with_payload": True,
                "filter": {"must": [
                    {"key": "workspace_id", "match": {"value": ws}},
                    {"key": "is_deleted", "match": {"value": False}},
                ]}
            }
        )
        hits = r.json().get("result", [])
    
    return [{"content": h["payload"]["content"], "score": h["score"]} for h in hits]


def build_context_memory_retrieval(sample, hits):
    """档位 3：检索 top_k 记忆"""
    if not hits:
        return [{"role": "user", "content": sample["question"]}]
    mem_text = "\n".join(f"- {h['content']}" for h in hits[:5])
    return [{
        "role": "user",
        "content": f"以下是关于该用户的历史记忆（按相关度排序）:\n{mem_text}\n\n请仅根据上述记忆回答问题: {sample['question']}"
    }]
