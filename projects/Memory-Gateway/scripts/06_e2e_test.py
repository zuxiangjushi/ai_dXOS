import asyncio, os, json, time
from unittest.mock import AsyncMock, MagicMock

# 导入项目组件
import sys
sys.path.insert(0, "/ai/Memory-Gateway")

from contracts.credentials import PROFILES
from app.use_cases.issue_key import KeyService
from app.use_cases.pool_route import PoolRouter
from app.use_cases.context_engine import ContextEngine
from adapters.pilot_openai import PilotAdapter
from adapters.langfuse_trace import TraceAdapter
from adapters.litellm_hooks import MemoryHooks
from adapters.embed_client import EmbedClient
from adapters.vector_store import QdrantVectorStore
from adapters.keyword_store import MeiliKeywordStore
from adapters.pg_repo import MemoryRepo
from app.use_cases.recall import RecallService

# 环境变量
os.environ["DXOS_PEPPER"] = "testpepper"
os.environ["PILOT_KEY_M00"] = "sk-test"
os.environ["PG_PROBE_DSN"] = "postgresql://probe:probe@127.0.0.1:5433/probe"

# 1. 初始化依赖（简化版，仅测试核心流程）
print("=== 初始化依赖 ===")
pilot = PilotAdapter(base_url="http://192.168.10.132:9980", api_key=os.environ["PILOT_KEY_M00"])
key_service = KeyService(dsn=os.environ["PG_PROBE_DSN"], cache=None)
pool_router = PoolRouter(pilot=pilot, packages={"38FN_Q4": {"cold_start_seconds": 1}})
context_engine = ContextEngine()
trace = TraceAdapter(enabled=True)

# 2. 模拟召回服务（暂不连真实向量库）
class FakeRecall:
    async def recall(self, query, scope, top_k=8):
        return []

# 3. 模拟写回队列
class FakeQueue:
    async def enqueue(self, ident, data, response):
        print("写回队列收到任务")

# 4. 创建 MemoryHooks
hooks = MemoryHooks(
    auth=key_service,
    router=pool_router,
    context_engine=context_engine,
    queue=FakeQueue(),
    trace=trace,
)

# 5. 模拟 LiteLLM 的 pre-call hook
async def test_pre_call():
    print("\n=== 测试 pre-call hook ===")
    # 模拟一个密钥（先签发一个临时 key）
    bearer = "sk-dx-test.xxx"  # 简化，实际应签发
    # 直接调用 hooks 的 async_pre_call_hook
    data = {
        "model": "38FN_Q4",
        "messages": [{"role": "user", "content": "你好"}],
        "_bearer": bearer,
    }
    user_api_key_dict = MagicMock()
    cache = MagicMock()
    call_type = "completion"

    try:
        result = await hooks.async_pre_call_hook(user_api_key_dict, cache, data, call_type)
        print("✅ pre-call hook 执行成功")
        print(f"   注入后 messages 数量: {len(result['messages'])}")
        for i, msg in enumerate(result['messages']):
            content = msg.get('content', '')
            if len(content) > 60:
                content = content[:60] + "..."
            print(f"   [{i}] {msg.get('role')}: {content}")
        # 检查是否有上下文段被注入
        context_added = any("上下文" in msg.get('content', '') for msg in result['messages'])
        print(f"   上下文注入: {'✅ 成功' if context_added else '⚠️ 未检测到'}")
    except Exception as e:
        print(f"❌ pre-call hook 失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    return True

# 6. 测试实际调用底座（绕过密钥验证，直接调用）
async def test_actual_call():
    print("\n=== 测试实际调用底座（绕过网关）===")
    try:
        import litellm
        # 配置 litellm 使用 9980 端点
        litellm.api_base = "http://192.168.10.132:9980"
        # 使用底座可用的模型名
        resp = await litellm.acompletion(
            model="openai/38FN_Q4",
            messages=[{"role": "user", "content": "你好，请说一句话介绍自己"}],
            max_tokens=20,
            temperature=0,
        )
        print(f"✅ 调用成功: {resp.choices[0].message.content[:100]}")
        return True
    except Exception as e:
        print(f"❌ 调用失败: {e}")
        return False

async def main():
    print("=" * 60)
    print("端到端冒烟测试")
    print("=" * 60)

    # 先检查底座是否可达
    try:
        import httpx
        r = httpx.get("http://192.168.10.132:9980/v1/models", timeout=2)
        if r.status_code != 200:
            print(f"⚠️ 底座 9980 不可达 (HTTP {r.status_code})，后续调用可能失败")
    except:
        print("⚠️ 底座 9980 不可达，请确认底座运行状态")

    # 测试 pre-call hook
    ok1 = await test_pre_call()

    # 测试实际调用
    ok2 = await test_actual_call()

    # 输出 trace
    trace.export()
    print("\n✅ Trace 已写入 docs/traces.jsonl")

    if ok1 and ok2:
        print("\n🎉 端到端验证通过！")
    else:
        print("\n⚠️ 部分测试失败，请检查日志")

if __name__ == "__main__":
    asyncio.run(main())
