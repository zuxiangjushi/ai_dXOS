"""能力代理：用能力名路由到实际模型

客户端请求 model=capability/memory-extraction
代理根据优先级选最优在线模型 → 转发到底座

设计目标：消除硬编码模型名
"""
import os
import json
import time
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Capability Proxy")

UPSTREAM = os.environ.get("UPSTREAM", "http://192.168.10.132:9980")
PILOT_KEY = os.environ.get("PILOT_KEY_M00", "")

# 能力契约
# ★ v5.0: 只用 LiteLLM 现有模型，排除嵌入/重排
CAPABILITIES = {
    "memory-extraction": {
        "tier1": ["Qwythos-9B-Claude-Mythos-5-1M"],
        "tier2": [],
        "tier3": [],
    },
    "reasoning": {
        "tier1": ["Qwythos-9B-Claude-Mythos-5-1M", "memory-llm"],
        "tier2": ["memory-llm"],
        "tier3": ["Qwythos-9B-Claude-Mythos-5-1M"],
    },
    "fast": {
        "tier1": ["Qwythos-9B-Claude-Mythos-5-1M", "memory-llm"],
        "tier2": ["memory-llm"],
        "tier3": ["Qwythos-9B-Claude-Mythos-5-1M"],
    },
}

# ★ v5.0: 嵌入/重排模型不能用于 chat
_EXCLUDE_FROM_CHAT = {
    "Qwen3_Embedding_06B", "emb_bge_m3_gpu", "emb_bge_m3",
    "bge_reranker_v2_m3", "gpu_bge_m3", "bge_reranker_v2",
}

# 缓存：在线模型（5s）
_cache = {"ts": 0, "models": []}


async def _get_online_models() -> list:
    now = time.time()
    if now - _cache["ts"] < 5:
        return _cache["models"]
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{UPSTREAM}/v1/models",
                            headers={"Authorization": f"Bearer {PILOT_KEY}"})
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                _cache.update({"ts": now, "models": models})
                return models
    except Exception as e:
        print(f"   [cap-proxy] 拉模型失败: {type(e).__name__}", flush=True)
    return _cache["models"]


async def _resolve_capability(cap_name: str) -> str:
    """根据能力名选实际模型"""
    if cap_name not in CAPABILITIES:
        raise HTTPException(400, f"未知能力: {cap_name}")

    online = await _get_online_models()
    if not online:
        raise HTTPException(503, "底座无可用模型")

    cap = CAPABILITIES[cap_name]
    for tier in ["tier1", "tier2", "tier3"]:
        for m in cap.get(tier, []):
            if m in online:
                print(f"   [cap-proxy] {cap_name} → {m} ({tier})", flush=True)
                return m

    # ★ v5.0: fallback 排除嵌入/重排模型
    chatable = [m for m in online if m not in _EXCLUDE_FROM_CHAT]
    if not chatable:
        raise HTTPException(503, "底座无可用 chat 模型")
    print(f"   [cap-proxy] {cap_name} → {chatable[0]} (fallback)", flush=True)
    return chatable[0]


@app.get("/v1/models")
async def list_models():
    """列出能力名（伪装成模型）"""
    online = await _get_online_models()
    return {
        "data": [
            {"id": f"capability/{name}", "object": "model", "owned_by": "capability-proxy"}
            for name in CAPABILITIES.keys()
        ]
    }


@app.get("/healthz")
async def health():
    online = await _get_online_models()
    return {"ok": True, "upstream_models": online}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "")

    # 解析能力名
    if model.startswith("capability/"):
        cap_name = model.split("/", 1)[1]
        actual_model = await _resolve_capability(cap_name)
        body["model"] = actual_model
    # 否则原样转发

    stream = bool(body.get("stream"))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {PILOT_KEY}",
    }

    if stream:
        async def gen():
            async with httpx.AsyncClient(timeout=300.0) as c:
                async with c.stream("POST", f"{UPSTREAM}/v1/chat/completions",
                                    headers=headers, json=body) as r:
                    async for line in r.aiter_lines():
                        if line:
                            yield line + "\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    else:
        async with httpx.AsyncClient(timeout=300.0) as c:
            r = await c.post(f"{UPSTREAM}/v1/chat/completions",
                             headers=headers, json=body)
            return JSONResponse(r.json(), status_code=r.status_code)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9900)
