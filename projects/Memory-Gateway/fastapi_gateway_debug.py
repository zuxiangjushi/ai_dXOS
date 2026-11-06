import os, asyncio, json, time
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List

from app.use_cases.context_engine import ContextEngine
from adapters.langfuse_trace import TraceAdapter
from adapters.litellm_hooks import MemoryHooks
from app.use_cases.pool_route import PoolRouter

PG_DSN = os.environ.get("PG_PROBE_DSN", "postgresql://probe:probe@127.0.0.1:5433/probe")

class MockKeyService:
    async def authenticate(self, bearer):
        return {"user_id": "test_user", "workspace_id": "test_ws",
                "agent_type": "claude_code", "model_allowlist": ["38FN_Q4"],
                "allow_silent_fallback": False}

class MockPilot:
    async def list_models(self, ttl=60):
        return {"38FN_Q4"}

class RealWritebackQueue:
    def __init__(self, dsn):
        self.dsn = dsn
    async def enqueue(self, ident, data, response):
        import hashlib, asyncpg
        content = ""
        for msg in reversed(data.get("messages", [])):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                break
        if not content:
            return
        idem_key = hashlib.sha256(
            f"{ident['user_id']}{data.get('model')}{content}{time.time()}".encode()
        ).hexdigest()[:32]
        conn = await asyncpg.connect(self.dsn)
        try:
            await conn.execute(
                """INSERT INTO writeback_queue 
                   (idem_key, user_id, workspace_id, tier, payload, keep_always, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)""",
                idem_key, ident["user_id"], ident["workspace_id"],
                "A", json.dumps({"content": content, "model": data.get("model")}),
                False, int(time.time())
            )
            print(f"   📝 已入队: {content[:40]}", flush=True)
        finally:
            await conn.close()

key_service = MockKeyService()
pilot = MockPilot()
pool_router = PoolRouter(pilot, packages={"38FN_Q4": {"cold_start_seconds": 1}})
context_engine = ContextEngine()
trace = TraceAdapter(enabled=True)
queue = RealWritebackQueue(PG_DSN)

hooks = MemoryHooks(
    auth=key_service, router=pool_router,
    context_engine=context_engine, queue=queue, trace=trace,
)

app = FastAPI(title="Memory-Gateway Debug")

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    max_tokens: int = 200
    temperature: float = 0.7

@app.get("/v1/models")
async def list_models():
    return {"data": [{"id": "38FN_Q4", "object": "model"}]}

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    print(f"\n📨 收到请求: model={request.model}", flush=True)
    
    data = {
        "model": request.model,
        "messages": [m.model_dump() for m in request.messages],
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
        "_bearer": "sk-test",
    }
    
    print("   ⏳ 调用 pre-call hook...", flush=True)
    try:
        data = await hooks.async_pre_call_hook({"token": "test"}, {}, data, "completion")
        print(f"   ✅ pre-call hook 完成", flush=True)
    except Exception as e:
        print(f"   ❌ pre-call 失败: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
    
    # ===== 关键：跳过真实模型调用，返回固定回复 =====
    content = "【测试模式】这是固定回复，用于验证写回链路。"
    print(f"   ✅ 使用固定回复（跳过模型调用）", flush=True)
    
    print("   ⏳ 调用 post-call hook...", flush=True)
    try:
        await hooks.async_post_call_success_hook(
            data, {"token": "test"}, {"choices": [{"message": {"content": content}}]}
        )
        print(f"   ✅ post-call hook 完成", flush=True)
    except Exception as e:
        print(f"   ⚠️ post-call 失败: {e}", flush=True)
    
    trace.export()
    return JSONResponse({
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 50}
    })

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("🚀 Memory-Gateway 调试模式（跳过模型调用）")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=9984, log_level="info")
