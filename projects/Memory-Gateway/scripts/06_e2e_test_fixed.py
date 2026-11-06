import os, sys, asyncio, time, json
from unittest.mock import MagicMock, AsyncMock

# 首先加载 .env.g0 环境变量
env_path = "/ai/Memory-Gateway/.env.g0"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k] = v.strip()
    print("✅ 已加载 .env.g0")
else:
    print("⚠️ .env.g0 不存在，使用默认环境变量")

# 现在可以安全导入项目组件
sys.path.insert(0, "/ai/Memory-Gateway")

from contracts.credentials import PROFILES
from app.use_cases.context_engine import ContextEngine
from adapters.langfuse_trace import TraceAdapter
from adapters.litellm_hooks import MemoryHooks
from app.use_cases.pool_route import PoolRouter
from adapters.pilot_openai import PilotAdapter

# 模拟 KeyService（避免数据库依赖）
class MockKeyService:
    async def authenticate(self, bearer):
        return {
            "user_id": "test_user",
            "workspace_id": "test_ws",
            "agent_type": "claude_code",
            "model_allowlist": ["38FN_Q4"],
            "allow_silent_fallback": False,
        }

# 模拟 PilotAdapter（避免真实网络调用）
class MockPilot:
    async def list_models(self, ttl=60):
        return {"38FN_Q4"}

# 模拟队列
class MockQueue:
    async def enqueue(self, ident, data, response):
        print("   ✅ 写回队列已接收任务")

async def test():
    print("=" * 60)
    print("M1+M2 端到端测试（无需数据库/网络）")
    print("=" * 60)

    # 初始化组件
    key_service = MockKeyService()
    pilot = MockPilot()
    pool_router = PoolRouter(pilot, packages={"38FN_Q4": {"cold_start_seconds": 1}})
    context_engine = ContextEngine()
    trace = TraceAdapter(enabled=True)
    queue = MockQueue()

    hooks = MemoryHooks(
        auth=key_service,
        router=pool_router,
        context_engine=context_engine,
        queue=queue,
        trace=trace,
    )

    # 模拟请求数据
    data = {
        "model": "38FN_Q4",
        "messages": [{"role": "user", "content": "你好，介绍一下自己"}],
        "_bearer": "sk-dx-test.xxx",
    }
    user_api_key_dict = MagicMock()
    cache = MagicMock()
    call_type = "completion"

    # 测试 pre-call hook
    print("\n>>> 测试 pre-call hook...")
    try:
        result = await hooks.async_pre_call_hook(user_api_key_dict, cache, data, call_type)
        print("   ✅ pre-call hook 执行成功")
        print(f"   📦 消息数量: {len(result['messages'])}")
        for i, msg in enumerate(result['messages']):
            content = msg.get('content', '')
            if len(content) > 60:
                content = content[:60] + "..."
            print(f"      [{i}] {msg.get('role', 'unknown')}: {content}")
        # 检查是否注入了上下文
        context_injected = any("上下文" in msg.get('content', '') for msg in result['messages'])
        print(f"   📌 上下文注入: {'✅ 是' if context_injected else '⚠️ 否（可能无记忆）'}")
    except Exception as e:
        print(f"   ❌ pre-call hook 失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 测试实际调用底座（仅当底座可达时）
    print("\n>>> 测试实际调用底座（可选）...")
    try:
        import httpx
        r = httpx.get("http://192.168.10.132:9980/v1/models", timeout=2)
        if r.status_code == 200:
            # 使用 litellm 调用
            import litellm
            litellm.api_base = "http://192.168.10.132:9980"
            resp = await litellm.acompletion(
                model="openai/38FN_Q4",
                messages=[{"role": "user", "content": "说一句话"}],
                max_tokens=10,
                temperature=0,
            )
            content = resp.choices[0].message.content
            print(f"   ✅ 调用成功: {content}")
        else:
            print(f"   ⚠️ 底座不可达 (HTTP {r.status_code})，跳过")
    except Exception as e:
        print(f"   ⚠️ 底座调用失败（可忽略）: {e}")

    # 导出 trace
    trace.export()
    print("\n✅ Trace 已写入 docs/traces.jsonl")

    print("\n🎉 测试通过！M1+M2 核心逻辑工作正常。")
    return True

if __name__ == "__main__":
    asyncio.run(test())
