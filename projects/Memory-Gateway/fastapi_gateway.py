"""
Memory-Gateway · 透明代理版
- /v1/models 透传底座（底座自己会动态适配启动的模型）
- /v1/chat/completions 透传（支持 SSE 流式）
- 可选记忆注入 / 写回（环境变量控制）
- 用户身份：X-User-Id Header → 缺省 default_user
"""
import os
import json
import time
import uuid
import asyncio
import hashlib
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.metrics import (
    gateway_requests_total, gateway_ttft_seconds,
    gateway_duration_seconds, gateway_tokens_total,
    memory_recall_total, memory_recall_hits,
    memory_write_total, context_degraded_total,
    gateway_cost_yuan, gateway_rate_limited_total,
    metrics_endpoint,
)

# ================= 配置 =================
UPSTREAM = os.environ.get("UPSTREAM_BASE", "http://192.168.10.132:9980")
M19_UPSTREAM = os.environ.get("M19_UPSTREAM_BASE", "http://127.0.0.1:8023")
M19_PUBLIC_NAME = "qwen2.5_3b"
M19_MODEL_ID = "qwen2.5-3b-instruct-q5_k_m.gguf"
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-REDACTED")

# ★ 3080 Ti 摘要节点（Pool-WIN，独立资源域）
SUMMARIZER_BASE_URL = os.environ.get("SUMMARIZER_BASE_URL", "http://192.168.10.208:8001/v1")
SUMMARIZER_API_KEY = os.environ.get("SUMMARIZER_API_KEY", "sk-REDACTED")
SUMMARIZER_MODEL = os.environ.get("SUMMARIZER_MODEL", "qwen25_coder_7b_awq")
SUMMARIZER_TIMEOUT = float(os.environ.get("SUMMARIZER_TIMEOUT", "60"))
SUMMARIZER_MAX_CONCURRENT = int(os.environ.get("SUMMARIZER_MAX_CONCURRENT", "4"))

# ★ Hermes 用自带搜索
DISABLE_SEARCH_AGENTS = set(s.strip().lower() for s in os.environ.get("DISABLE_SEARCH_AGENTS", "").split(",") if s.strip())
DISABLE_SEARCH_USERS = set(s.strip().lower() for s in os.environ.get("DISABLE_SEARCH_USERS", "").split(",") if s.strip())
DISABLE_SEARCH_SYSTEM_MARKERS = [s.strip() for s in os.environ.get("DISABLE_SEARCH_SYSTEM_MARKERS", "").split(",") if s.strip()]

def _is_hermes_request(body: dict, request=None) -> bool:
    # ★ v5.0: 显式 _force_search 优先
    _force = body.get("_force_search")
    if _force is True:
        return False      # MG_：允许搜索
    if _force is False:
        return True       # 无 MG_：明确跳过搜索
    if request:
        _h = request.headers.get("x-disable-search", "").lower()
        if _h in ("1", "true", "yes"):
            return True
    if (body.get("_agent_type") or "").lower() in DISABLE_SEARCH_AGENTS:
        return True
    if ((body.get("_ident") or {}).get("user_id") or "").lower() in DISABLE_SEARCH_USERS:
        return True
    for m in (body.get("messages") or []):
        if m.get("role") == "system":
            _c = str(m.get("content", ""))
            for marker in DISABLE_SEARCH_SYSTEM_MARKERS:
                if marker in _c:
                    return True
    return False



# ===== 剥离 <think>...</think> 思维链（防止 Claude Code 吞内容）=====
import re as _re_think
from window_budget import ensure_non_empty_content
_THINK_RE = _re_think.compile(r"<think\b[^>]*>.*?</think\s*>", _re_think.DOTALL | _re_think.IGNORECASE)

def _strip_think(text: str) -> str:
    if not text:
        return text
    return _THINK_RE.sub("", text).lstrip()
# ===== end =====
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "9982"))
MEMORY_INJECT_ENABLED = os.environ.get("MEMORY_INJECT_ENABLED", "false").lower() == "true"
MEMORY_WRITEBACK_ENABLED = os.environ.get("MEMORY_WRITEBACK_ENABLED", "false").lower() == "true"
PG_DSN = os.environ.get("PG_PROBE_DSN") or "postgresql://probe:probe@127.0.0.1:5433/probe"

# ================= 内部任务过滤 =================
INTERNAL_TASK_MARKERS = (
    "### Task:",
    "Generate a concise title",
    "Generate 1-3 broad tags",
    "Suggest 3-5 relevant follow-up",
)

def is_internal_task(content: str) -> bool:
    """识别 Open WebUI 的内部辅助任务（生成标题/标签/推荐问题）"""
    if not content:
        return False
    # 前 200 字符内匹配即认为内部任务
    head = content[:200]
    return any(m in head for m in INTERNAL_TASK_MARKERS)



def _log_ua(request, tag=""):
    """记录 User-Agent 便于识别客户端（临时调试用，稳定后可删）"""
    ua = (request.headers.get("user-agent") or "")[:120]
    xagent = (request.headers.get("x-agent-type") or "")[:40]
    if ua or xagent:
        print(f"   [ua{tag}] ua={ua!r} x-agent={xagent!r}", flush=True)

# ================= 内部任务过滤 =================
INTERNAL_TASK_MARKERS = (
    "### Task:",
    "Generate a concise title",
    "Generate 1-3 broad tags",
    "Suggest 3-5 relevant follow-up",
)

def is_internal_task(content: str) -> bool:
    """识别 Open WebUI 的内部辅助任务（生成标题/标签/推荐问题）"""
    if not content:
        return False
    # 前 200 字符内匹配即认为内部任务
    head = content[:200]
    return any(m in head for m in INTERNAL_TASK_MARKERS)


# ================= 记忆组件（可选加载） =================
_hooks = None
_worker = None
_reconciler = None

if MEMORY_INJECT_ENABLED or MEMORY_WRITEBACK_ENABLED:
    try:
        from app.use_cases.context_engine import ContextEngine
        from adapters.langfuse_trace import TraceAdapter
        from adapters.litellm_hooks import MemoryHooks
        from app.use_cases.pool_route import PoolRouter
        from app.workers.writeback_worker import WritebackWorker
        from app.workers.index_reconciler import IndexReconciler

        class _MockKeyService:
            async def authenticate(self, bearer):
                return {"user_id": "default_user", "workspace_id": "default_ws",
                        "agent_type": "claude_code", "model_allowlist": ["*"],
                        "allow_silent_fallback": False}

        class _MockPilot:
            async def list_models(self, ttl=60):
                return set()

        class _WritebackQueue:
            def __init__(self, dsn): self.dsn = dsn
            async def enqueue(self, ident, data, response):
                import asyncpg
                content = data.get("_original_user_content", "")
                if not content: return
                # ★ 过滤 Open WebUI 内部辅助任务
                if is_internal_task(content):
                    print(f"   [skip] 内部任务不写回: {content[:40]}", flush=True)
                    return
                # ★ 过滤 Open WebUI 内部辅助任务
                if is_internal_task(content):
                    print(f"   [skip] 内部任务不写回: {content[:40]}", flush=True)
                    return
                idem = hashlib.sha256(f"{ident['user_id']}{content}{time.time()}".encode()).hexdigest()[:32]
                conn = await asyncpg.connect(self.dsn)
                try:
                    await conn.execute(
                        """INSERT INTO writeback_queue
                           (idem_key, user_id, workspace_id, tier, payload, keep_always, created_at)
                           VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)
                           ON CONFLICT (idem_key) DO NOTHING""",
                        idem, ident["user_id"], ident["workspace_id"], "A",
                        json.dumps({"content": content}), False, int(time.time()))
                finally:
                    await conn.close()

        _hooks = MemoryHooks(
            auth=_MockKeyService(),
            router=PoolRouter(_MockPilot()),
            context_engine=ContextEngine(),
            queue=_WritebackQueue(PG_DSN),
            trace=TraceAdapter(enabled=True))
        _worker = WritebackWorker(dsn=PG_DSN, pilot=None, vector_store=None,
                                  repo=None, embed_client=None, max_concurrent=1)
        print("✅ 记忆组件已加载", flush=True)
        _reconciler = IndexReconciler(dsn=PG_DSN, qdrant_url='http://127.0.0.1:6333')
    except Exception as e:
        print(f"⚠️ 记忆组件加载失败，降级为纯透传: {type(e).__name__}: {e}", flush=True)

# ================= 后台任务管理（防 GC） =================
import asyncio as _aio_bg

_BG_TASKS = set()

async def _bg_runner(coro):
    try:
        await coro
    except Exception as e:
        print(f"   [bg-task] 失败: {type(e).__name__}: {e}", flush=True)
    finally:
        _BG_TASKS.discard(_aio_bg.current_task())

import threading as _threading
import asyncio as _asyncio

def _run_index_in_thread(indexer, user_id, title, content, doc_id, fname, size_kb):
    """在线程里跑异步任务（绕过 uvicorn 事件循环问题）"""
    def worker():
        try:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                _d = loop.run_until_complete(
                    indexer.index_document(user_id, title, content, doc_id=doc_id))
                print(f"   [rag-upload-bg] {fname} ({size_kb}KB) 线程完成: {_d}", flush=True)
            finally:
                loop.close()
        except Exception as e:
            import traceback as _tb
            print(f"   [rag-upload-bg] {fname} 线程失败: {type(e).__name__}: {e}", flush=True)
            _tb.print_exc()
    t = _threading.Thread(target=worker, daemon=False)
    t.start()
    return t


async def _index_document_async(indexer, user_id, title, content, doc_id, fname, size_kb):
    try:
        _d = await indexer.index_document(user_id, title, content, doc_id=doc_id)
        print(f"   [rag-upload-bg] {fname} ({size_kb}KB) 完成: {_d}", flush=True)
    except Exception as _e:
        import traceback as _tb
        print(f"   [rag-upload-bg] {fname} 失败: {type(_e).__name__}: {_e}", flush=True)
        _tb.print_exc()


def _spawn_bg(coro):
    """安全创建后台任务（防 GC）"""
    task = _aio_bg.create_task(_bg_runner(coro))
    _BG_TASKS.add(task)
    return task


# ================= 上下文窗口检查 =================
# 每个模型的物理窗口大小（token）
MODEL_CONTEXT_WINDOWS = {
    "deepseek_v41_flash": 8192,
    "deepseek-v4.1-flash": 8192,
    "Flint": 262144,
    "flint": 262144,

    "Qwythos-9B-Claude-Mythos-5-1M": 1048576,  # v5.3.3: 1M 原生窗口

    "qwen38_27b": 262144,
    "gemma_4": 131072,
    "yy38_27b": 131072,
    "yy35b_q6": 262144,
    "38FN_Q4": 131072,
    "deepseek_70b": 131072,
    "qwen3_30b": 262144,
    "Qwen3.8-27B": 262144,  # v5.3.6: qwen38_27b 的别名
    "Qwen3.6-27B": 262144,  # v5.3.6: qwen36_27b 的别名
    "Qwen3.6-35B": 262144,  # v5.3.6: qwen36_35b 的别名
    "Qwen3-32B-AWQ": 40960,           # v5.3.6: 从 config.json 补入
    "deepseek_V25": 163840,
    "qwen3_emb_8b": 40960,
    # ---- 动态补全（2026-10-04）----
    "qwen36_35b": 262144,
    "qwen36_27b": 262144,
    "gemma_4_31B": 16384,
    "Glimmer-30B": 131072,
    "deepseek_V4": 32768,
    "MiniMax_H3": 32768,
    "qwen2.5_3b": 32768,  # M19: llama.cpp --ctx-size 32768
    "Holo_31": 65536,
}


# ================= 动态模型路由 =================
import threading as _th_routing
import time as _time_routing
import urllib.request as _ur_routing
import json as _json_routing

_DXOS_PANEL_URL = os.environ.get("DXOS_PANEL_URL", "http://127.0.0.1:9981/api/models")

_TOOL_MODEL_PRIORITY = ["yy35b_q6", "yy35b_q6", "qwen38_27b", "deepseek_70b", "qwen3_30b"]
_REASON_MODEL_PRIORITY = ["yy35b_q6", "qwen38_27b"]

_MODEL_KEYS = {
    "yy35b_q6": "sk-REDACTED",
    "qwen38_27b": "sk-REDACTED",
    "deepseek_70b": "sk-REDACTED",
    "qwen3_30b": "sk-REDACTED",
    "gemma_4": "sk-REDACTED",
    "yy38_27b": "sk-REDACTED",
    "yy35b_q6": "sk-REDACTED",
}

_routing_cache = {"tool": None, "reason": None, "updated": 0, "running": []}
_routing_lock = _th_routing.Lock()


def _refresh_routing(force=False):
    age = _time_routing.time() - _routing_cache.get("updated", 0)
    if not force and age < 60:
        return
    try:
        with _ur_routing.urlopen(_DXOS_PANEL_URL, timeout=3) as r:
            models = _json_routing.loads(r.read().decode())
        running = {m.get("api_name") for m in (models or []) if m.get("status") == "running"}
    except Exception as e:
        print(f"   [routing] 底座 API 查询失败: {e}", flush=True)
        with _routing_lock:
            _routing_cache["updated"] = _time_routing.time()
        return
    tool = next((m for m in _TOOL_MODEL_PRIORITY if m in running), None)
    reason = next((m for m in _REASON_MODEL_PRIORITY if m in running), None)
    if not tool and running:
        tool = sorted(running)[0]
    if not reason and running:
        reason = sorted(running)[0]
    if not tool:
        tool = reason = "deepseek_70b"
    with _routing_lock:
        _routing_cache["tool"] = tool
        _routing_cache["reason"] = reason
        _routing_cache["running"] = sorted(running)
        _routing_cache["updated"] = _time_routing.time()
    print(f"   [routing] tool={tool} reason={reason} running={sorted(running)}", flush=True)


def _get_routing(has_tools):
    _refresh_routing()
    with _routing_lock:
        m = _routing_cache["tool"] if has_tools else _routing_cache["reason"]
        if not m:
            m = _routing_cache["reason"] or "deepseek_70b"
    return m, _MODEL_KEYS.get(m, "")


_tk_enc = None

def _get_enc():
    global _tk_enc
    if _tk_enc is None:
        try:
            import tiktoken
            _tk_enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tk_enc = False
    return _tk_enc if _tk_enc else None


def _count_msgs_tokens(msgs) -> int:
    """优先使用 tokenizer；不可用时按完整消息 JSON 做保守估算。"""
    import json
    enc = None
    try:
        enc = _get_enc()
    except Exception:
        enc = None

    try:
        payload = json.dumps(
            msgs if isinstance(msgs, list) else [],
            ensure_ascii=False,
            separators=(",", ":"),
            default=str
        )
    except Exception:
        payload = str(msgs)

    if enc is not None:
        try:
            return len(enc.encode(payload))
        except Exception:
            pass

    # 中文按 UTF-8 字节估算，英文按字符估算；包含工具调用及消息结构
    chars = len(payload)
    byte_count = len(payload.encode("utf-8", errors="replace"))
    return max(1, (chars + 1) // 2, (byte_count + 2) // 3)


async def _compress_history(body: dict, model: str, max_tokens: int = 8000) -> dict:
    """分层摘要：超窗口时，用 LLM 摘要历史"""
    msgs = body.get("messages") or []
    if not msgs:
        return body
    
    total = _count_msgs_tokens(msgs)
    if total <= max_tokens:
        return body
    
    system_msgs = [m for m in msgs if m.get("role") == "system"]
    non_system = [m for m in msgs if m.get("role") != "system"]
    recent = non_system[-10:]
    older = non_system[:-10]
    
    if not older:
        return body
    
    older_text = "\n".join([
        f"{m.get('role')}: {str(m.get('content', ''))[:500]}"
        for m in older
    ])
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{UPSTREAM}/v1/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                json={
                    "model": "qwen36_35b",
                    "messages": [{
                        "role": "user",
                        "content": f"用 300 字总结以下对话历史的关键信息：\n\n{older_text}"
                    }],
                    "max_tokens": 500,
                    "stream": False,
                },
            )
            r_json = r.json()
            summary = r_json["choices"][0]["message"]["content"]
        
        new_msgs = system_msgs + [
            {"role": "system", "content": f"## 历史摘要\n{summary}"}
        ] + recent
        body["messages"] = new_msgs
        print(f"   [compress-history] {len(msgs)} 条 → {len(new_msgs)} 条（含摘要）", flush=True)
    except Exception as e:
        print(f"   [compress-history] 失败: {e}", flush=True)
        body["messages"] = system_msgs + recent
    
    return body


# ═══════════════════════════════════════════════════════════════════
# 无限上下文：异步分层摘要 + Redis 缓存
# ═══════════════════════════════════════════════════════════════════

import redis.asyncio as _aioredis_sum
_summary_redis = None

async def _get_summary_redis():
    """获取 Redis 连接（单例）"""
    global _summary_redis
    if _summary_redis is None:
        try:
            _summary_redis = await _aioredis_sum.from_url(
                "redis://127.0.0.1:6379/0",
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=2,
            )
        except Exception as e:
            print(f"   [summary-redis] 连接失败: {e}", flush=True)
            return None
    return _summary_redis


async def _read_summary(user_id: str, session_id: str = "default") -> str:
    """从 Redis 读取现有摘要"""
    try:
        r = await _get_summary_redis()
        if not r:
            return ""
        key = f"summary:{user_id}:{session_id}"
        return await r.get(key) or ""
    except Exception:
        return ""


async def _write_summary(user_id: str, session_id: str, summary: str, ttl: int = 86400):
    """写入摘要到 Redis（TTL 24 小时）"""
    try:
        r = await _get_summary_redis()
        if not r:
            return
        key = f"summary:{user_id}:{session_id}"
        await r.setex(key, ttl, summary)
    except Exception as e:
        print(f"   [summary-write] 失败: {e}", flush=True)


import asyncio as _aio_sum
_SUMMARIZE_SEMAPHORE = _aio_sum.Semaphore(SUMMARIZER_MAX_CONCURRENT)

async def _do_summarize(older_msgs: list, session_id: str = "default") -> str:
    """用 LLM 摘要历史（★ 强制用小模型，避免抢占主力）"""
    # ★ 优先 3080 Ti 摘要节点（Pool-WIN），失败降级 memory-llm
    _summarize_url = SUMMARIZER_BASE_URL + "/chat/completions"
    _summarize_key = SUMMARIZER_API_KEY
    _summarize_model = SUMMARIZER_MODEL
    _summarize_is_remote = True
    
    # 健康检查（2s 超时）
    try:
        import httpx as _hx_s
        async with _hx_s.AsyncClient(timeout=2.0) as _c_s:
            _r_s = await _c_s.get(SUMMARIZER_BASE_URL + "/models",
                                  headers={"Authorization": f"Bearer {_summarize_key}"})
            if _r_s.status_code != 200:
                raise Exception(f"HTTP {_r_s.status_code}")
        print(f"   [summarize] 3080 Ti 节点可用（{_summarize_model}）", flush=True)
    except Exception as _e_s:
        # 降级到 memory-llm
        _summarize_url = f"{UPSTREAM}/v1/chat/completions"
        _summarize_key = LITELLM_KEY
        _summarize_model = "memory-llm"
        _summarize_is_remote = False
        print(f"   [summarize] 3080 Ti 不可用({_e_s})，回退 memory-llm", flush=True)
    
    if not older_msgs:
        return ""
    
    # 构造摘要 prompt
    text = "\n".join([
        f"{m.get('role')}: {str(m.get('content', ''))[:400]}"
        for m in older_msgs
    ])
    
    prompt = f"""请用 300 字总结以下对话历史的关键信息（保留：用户身份、偏好、已讨论的事实、未解决的任务）：

{text}

要求：
- 只输出摘要内容，不要额外说明
- 用简洁的陈述句
- 保留具体信息（名字、地点、日期、数字）"""
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                _summarize_url,
                headers={"Authorization": f"Bearer {_summarize_key}"},
                json={
                    "model": _summarize_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "stream": False,
                    "temperature": 0.3,
                },
            )
            r_json = r.json()
            summary = r_json["choices"][0]["message"].get("content", "")
            print(f"   [summarize] 使用 {_summarize_model} 摘要完成（{len(summary)} 字）", flush=True)
            return summary.strip()
    except Exception as e:
        print(f"   [summarize] 失败: {e}", flush=True)
        return ""


async def _compress_history_async(body: dict, ident: dict) -> dict:
    """v7：暂停旧的非事务安全历史压缩，交由最终预算器统一裁剪。"""
    return body


def _dynamic_trim(non_system: list, token_budget: int = 8000, min_keep: int = 3) -> list:
    """v7：不再进行可能拆散工具事务的局部历史裁剪。"""
    return non_system


def _enforce_context_window(body: dict, model: str) -> dict:
    """最终上下文预算裁决：完整计数、事务安全裁剪、严格输出预算。"""
    import json

    def fail(message):
        body["_context_error"] = str(message)
        return body

    budget_model = body.get("_resolved_context_model") or model
    windows = globals().get("MODEL_CONTEXT_WINDOWS", {})
    if not isinstance(windows, dict) or budget_model not in windows:
        return fail(f"未知模型上下文窗口：{budget_model}。拒绝使用猜测的默认窗口。")

    try:
        window = int(windows[budget_model])
    except Exception:
        return fail(f"模型上下文窗口配置无效：{budget_model}")

    if window < 1024:
        return fail(f"模型上下文窗口配置过小：{budget_model}={window}")

    messages = body.get("messages")
    if not isinstance(messages, list):
        return fail("messages 必须是数组。")

    tools = body.get("tools")
    if tools is None:
        tools = []
    if not isinstance(tools, list):
        return fail("tools 必须是数组。")

    def count(obj):
        raw = json.dumps(
            obj, ensure_ascii=False, separators=(",", ":"), default=str
        )
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(raw))
        except Exception:
            return max(1, (len(raw.encode("utf-8")) + 2) // 3)

    # 工具定义完整计数，绝不裁减客户端 tools。
    try:
        tools_tokens = count(tools) if tools else 0
    except Exception as exc:
        return fail(f"工具定义无法计数：{exc}")

    # 固定指令单独保护。
    fixed = []
    ordinary = []
    for msg in messages:
        if not isinstance(msg, dict):
            return fail("messages 中存在非对象元素，拒绝不完整转发。")
        if msg.get("role") in ("system", "developer"):
            fixed.append(msg)
        else:
            ordinary.append(msg)

    # 将 assistant tool_calls 和全部对应 tool 回复组成不可拆分事务。
    groups = []
    i = 0
    while i < len(ordinary):
        msg = ordinary[i]
        role = msg.get("role")

        if role == "tool":
            return fail(
                f"发现孤立 tool 回复（tool_call_id={msg.get('tool_call_id')}）。"
            )

        calls = msg.get("tool_calls") if role == "assistant" else None
        if calls:
            if not isinstance(calls, list):
                return fail("assistant.tool_calls 格式错误。")

            expected = []
            for call in calls:
                if not isinstance(call, dict) or not call.get("id"):
                    return fail("tool_calls 存在缺少 id 的调用。")
                call_id = str(call["id"])
                if call_id in expected:
                    return fail(f"tool_calls 存在重复 id：{call_id}")
                expected.append(call_id)

            group = [msg]
            received = set()
            j = i + 1

            while j < len(ordinary) and len(received) < len(expected):
                reply = ordinary[j]
                if reply.get("role") != "tool":
                    return fail(
                        "工具调用事务不完整：收到全部 tool 回复前出现了其他消息。"
                    )

                reply_id = str(reply.get("tool_call_id") or "")
                if reply_id not in expected:
                    return fail(f"工具回复 ID 不匹配：{reply_id}")
                if reply_id in received:
                    return fail(f"工具回复重复：{reply_id}")

                received.add(reply_id)
                group.append(reply)
                j += 1

            if received != set(expected):
                missing = sorted(set(expected) - received)
                return fail(f"工具调用事务缺少回复：{missing}")

            groups.append(group)
            i = j
        else:
            groups.append([msg])
            i += 1

    def count_messages(items):
        return count(items) if items else 0

    safety = min(512, max(128, window // 32))
    # 至少给模型留下 1 个输出 token。
    input_limit = window - safety - 1

    fixed_tokens = count_messages(fixed)
    if fixed_tokens + tools_tokens > input_limit:
        return fail(
            f"system/developer 指令与 tools 已超出输入预算："
            f"{fixed_tokens + tools_tokens}>{input_limit}。"
            "不会静默删除系统指令或工具定义。"
        )

    kept = list(groups)

    def current_input_tokens():
        flattened = [m for group in kept for m in group]
        return count_messages(fixed + flattened) + tools_tokens

    # 只移除最旧的完整消息组，至少保留最新消息组。
    while len(kept) > 1 and current_input_tokens() > input_limit:
        kept.pop(0)

    used = current_input_tokens()
    if used > input_limit:
        return fail(
            f"最新消息组、固定指令及工具定义仍超出模型窗口："
            f"{used}+安全余量{ safety }>{window}。"
            "为避免破坏工具事务，拒绝转发。"
        )

    requested = body.get("max_tokens", 2048)
    try:
        requested = int(requested)
    except Exception:
        return fail("max_tokens 不是有效整数。")

    if requested < 1:
        return fail("max_tokens 必须大于零。")

    actual_output = min(requested, window - used - safety)
    if actual_output < 1:
        return fail("上下文已无可用输出预算。")

    body["messages"] = fixed + [m for group in kept for m in group]
    body["max_tokens"] = actual_output
    body.pop("_context_error", None)

    print(
        f"   [context-v7] model={budget_model} window={window} "
        f"input={used} tools={tools_tokens} output={actual_output} "
        f"groups={len(kept)}",
        flush=True
    )
    return body



# ================= 引用链接化 =================
import re as _re_cite
_CITE_RE = _re_cite.compile(r'\[(\d+)\](?!\()')

def _linkify_citations(text: str, url_map: dict) -> str:
    """把 [1] 替换为 [1](url)，跳过已经是链接的 [1](...)"""
    if not text or not url_map:
        return text
    def sub(m):
        n = int(m.group(1))
        url = url_map.get(n)
        if not url:
            return m.group(0)
        # ★ 若下一位是中文标点，加空格防止被吃进 URL
        _nx = m.end()
        _nc = text[_nx] if _nx < len(text) else ""
        if _nc and _nc in "。，、；：！？）】」』":
            return f"[{n}]({url}) "
        return f"[{n}]({url})"
    return _CITE_RE.sub(sub, text)


def _format_references(meta: dict) -> str:
    """构造参考列表文本（流式/非流式通用）"""
    if not meta:
        return ""
    lines = ["", "", "─────", "**参考来源：**"]
    for n in sorted(meta.keys()):
        m = meta[n]
        tag = m.get("tag", "")
        url = m.get("url", "")
        title = m.get("title", "")
        if title:
            lines.append(f"- [{n}] {tag} [{title}]({url})")
        else:
            lines.append(f"- [{n}] {tag} {url}")
    return "\n".join(lines)


def _append_references(answer: str, meta: dict) -> str:
    """在答案末尾追加参考列表（非流式）"""
    refs = _format_references(meta)
    if not refs:
        return answer
    if answer and "参考来源" in answer[-500:]:
        return answer
    return answer + refs


class _CiteLinker:
    """流式引用链接化：保守 buffer，防止 [1] 跨 chunk 被截断"""
    TAIL = 20
    def __init__(self, url_map: dict):
        self.url_map = url_map or {}
        self.buf = ""
    def feed(self, delta: str) -> str:
        if not self.url_map:
            return delta
        self.buf += delta
        if len(self.buf) <= self.TAIL:
            return ""
        safe, self.buf = self.buf[:-self.TAIL], self.buf[-self.TAIL:]
        return _linkify_citations(safe, self.url_map)
    def flush(self) -> str:
        out = _linkify_citations(self.buf, self.url_map)
        self.buf = ""
        return out


# ================= 上游模型健康检查 =================
import time as _time_health
_health_cache = {"ts": 0, "ok": True, "models": []}

async def _check_upstream_models() -> dict:
    """检查底座是否有可用模型（5s 缓存）"""
    now = _time_health.time()
    if now - _health_cache["ts"] < 5:
        return _health_cache

    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(
                f"{UPSTREAM}/v1/models",
                headers={"Authorization": f"Bearer {os.environ.get('PILOT_KEY_M00', '')}"},
            )
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                _health_cache.update({
                    "ts": now,
                    "ok": len(models) > 0,
                    "models": models,
                })
                return _health_cache
    except Exception as e:
        print(f"   [health-upstream] 检查失败: {type(e).__name__}", flush=True)

    _health_cache.update({"ts": now, "ok": False, "models": []})
    return _health_cache


# ================= Anthropic → OpenAI messages 转换 =================

import re as _re_tc

_TOOL_CALL_RE = _re_tc.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", _re_tc.DOTALL)

def _extract_tool_calls(text):
    """提取 <tool_call>{...}</tool_call> → (clean_text, [{"name":..,"arguments":..}])"""
    if not text or "<tool_call>" not in text:
        return text or "", []
    calls = []
    for m in _TOOL_CALL_RE.finditer(text):
        try:
            obj = json.loads(m.group(1))
            name = obj.get("name", "")
            args = obj.get("arguments", {})
            if not isinstance(args, dict):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name:
                calls.append({"name": name, "arguments": args})
        except Exception:
            continue
    clean = _TOOL_CALL_RE.sub("", text).strip()
    return clean, calls



def _count_tools_tokens(tools):
    """估算 tools schema 的 token 数"""
    if not tools:
        return 0
    enc = _get_enc()
    if enc is None:
        return len(json.dumps(tools, ensure_ascii=False)) // 3
    try:
        return len(enc.encode(json.dumps(tools, ensure_ascii=False)))
    except Exception:
        return len(json.dumps(tools, ensure_ascii=False)) // 3



# Claude Code 核心工具（必须保留，其余可裁）
_ESSENTIAL_TOOLS = {"Bash", "Read", "Write", "Edit", "Glob", "Grep", "TodoWrite"}

def _fit_total_window(openai_body, model):
    """v7：兼容旧调用名，统一委托最终预算器，不再删减工具定义。"""
    return _enforce_context_window(openai_body, model)



def _normalize_chat_response(resp_json):
    """OpenAI 路径响应后处理：剥 think + 解析 <tool_call> XML → 标准 tool_calls"""
    # ★ 入口清理：删除空的 tool_calls 字段（None/[] 都会触发 Hermes 误判）
    try:
        _choices = resp_json.get("choices") or []
        for _c in _choices:
            _msg = _c.get("message") or {}
            if "tool_calls" in _msg and _msg["tool_calls"] in (None, []):
                _msg.pop("tool_calls", None)
    except Exception:
        pass

    try:
        choices = resp_json.get("choices") or []
        if not choices:
            return resp_json
        choice = choices[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""

        # 1) 剥 think
        clean = _strip_think(content)

        # 2) 解析 tool_call
        if "<tool_call>" in clean:
            clean_text, tool_calls = _extract_tool_calls(clean)
            if tool_calls:
                msg["content"] = clean_text or None
                msg["tool_calls"] = [
                    {
                        "id": "call_" + uuid.uuid4().hex[:16],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in tool_calls
                ]
                choice["message"] = msg
                choice["finish_reason"] = "tool_calls"
                print(f"   [tool-parse] 解析出 {len(tool_calls)} 个 tool_calls", flush=True)
                return resp_json

        # 3) 没 tool_call，先检查 content 是否空 + reasoning_content 是否有值
        if not clean.strip():
            reasoning = msg.get("reasoning_content") or ""
            if reasoning and "<tool_call>" in reasoning:
                _rt, _rtcs = _extract_tool_calls(reasoning)
                if _rtcs:
                    msg["content"] = None
                    msg["tool_calls"] = [
                        {"id": "call_" + uuid.uuid4().hex[:16],
                         "type": "function",
                         "function": {"name": tc["name"],
                                      "arguments": json.dumps(tc["arguments"], ensure_ascii=False)}}
                        for tc in _rtcs
                    ]
                    choice["message"] = msg
                    choice["finish_reason"] = "tool_calls"
                    print(f"   [tool-parse-from-reasoning] 从 reasoning 提取 {len(_rtcs)} 个 tool_calls", flush=True)
                    return resp_json
            if reasoning.strip():
                # 从 reasoning 里剥 think 后作为正文（去掉"Here's a thinking process"等前缀）
                _r = _strip_think(reasoning)
                # llama.cpp 有时把思考包装成 "Here's a thinking process: ..." 或带 <think>
                # 尝试提取最终答案（多数模型在 reasoning 末尾给出结论）
                _r = _r.strip()
                if _r:
                    # guard: filter history-repetition to avoid content pollution
                    _user_refs = _r.count("User asked") + _r.count("User instructed")
                    _too_long = len(_r) > 500
                    _is_history = _user_refs >= 2
                    if _too_long or _is_history:
                        print(f"   [think-fallback-skip] reasoning looks like history "
                              f"(len={len(_r)}, user_refs={_user_refs}), skip", flush=True)
                        # 兜底：给一个明确的提示，避免 Hermes 判为 No reply
                        msg["content"] = ""
                        choice["finish_reason"] = "length"
                        choice["message"] = msg
                        return resp_json
                    else:
                        msg["content"] = _r
                        choice["message"] = msg
                        print(f"   [think-fallback] content 空，从 reasoning 提取 {len(_r)} 字", flush=True)
                        return resp_json

        if clean != content:
            msg["content"] = clean
            choice["message"] = msg
        return resp_json
    except Exception as e:
        print(f"   [tool-parse] 失败: {e}", flush=True)
        return resp_json




async def _proxy_stream_realtime(body, headers, t0, upstream_base=None):
    """真流式：逐 token 转发，不等完整响应（用于无 tools 请求）"""
    try:
        async with httpx.AsyncClient(timeout=300.0) as c:
            async with c.stream(
                "POST",
                f"{(upstream_base or UPSTREAM).rstrip('/')}/v1/chat/completions",
                headers=headers, json=body
            ) as r:
                print(f"   ⏳ [realtime] 上游 {r.status_code}", flush=True)
                chunks = 0
                async for line in r.aiter_lines():
                    if line:
                        chunks += 1
                        yield line + "\n\n"
                print(f"   ✅ [realtime] {chunks} chunks ({time.perf_counter()-t0:.2f}s)", flush=True)
    except Exception as e:
        print(f"   ❌ [realtime] {type(e).__name__}: {e}", flush=True)
        yield f"data: {json.dumps({'error': {'message': str(e)[:200]}})}\n\n"
        yield "data: [DONE]\n\n"


async def _proxy_stream_buffered(body, headers, t0, upstream_base=None):
    """有 tools 的流式请求：内部非流式 → 包装成 OpenAI SSE（可正常发 tool_calls）"""
    # ★★★ 临时诊断：dump 最终发给 9980 的 body + 上游响应 ★★★
    # [PATCHED] Removed UPSTREAM Dump
    try:
        async with httpx.AsyncClient(timeout=300.0) as c:
            r = await c.post(
                f"{(upstream_base or UPSTREAM).rstrip('/')}/v1/chat/completions",
                headers=headers, json={**body, "stream": False}
            )
            # ★ 打印上游响应状态和内容
            print(f"   [DUMP-RESP] status={r.status_code}, body_head={str(r.text)[:500]}", flush=True)
            resp_json = _normalize_chat_response(r.json())
    except Exception as e:
        print(f"   ❌ buffered stream 上游失败: {type(e).__name__}: {e}", flush=True)
        yield f"data: {json.dumps({'error': {'message': str(e)[:200]}})}\n\n"
        yield "data: [DONE]\n\n"
        return

    try:
        choice = (resp_json.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        finish = choice.get("finish_reason", "stop")
        msg_id = "chatcmpl-" + uuid.uuid4().hex[:16]
        _model = resp_json.get("model", body.get("model", "?"))

        def _chunk(delta, fin=None):
            return "data: " + json.dumps({
                "id": msg_id, "object": "chat.completion.chunk",
                "created": int(time.time()), "model": _model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": fin}],
            }, ensure_ascii=False) + "\n\n"

        # role 起始
        yield _chunk({"role": "assistant"})

        # 正文
        content = msg.get("content")
        if content:
            yield _chunk({"content": content})

        # tool_calls（OpenAI 流式格式：index + id + function）
        tcs = msg.get("tool_calls")
        if tcs:
            for i, tc in enumerate(tcs):
                yield _chunk({"tool_calls": [{
                    "index": i,
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }]})

        # 结束
        yield _chunk({}, fin=finish)
        yield "data: [DONE]\n\n"

        print(f"   ✅ buffered stream 完成 text_len={len(content or '')} tool_calls={len(tcs or [])} ({time.perf_counter()-t0:.2f}s)", flush=True)
    except Exception as e:
        print(f"   ❌ buffered stream 解析失败: {e}", flush=True)
        yield f"data: {json.dumps({'error': {'message': str(e)[:200]}})}\n\n"
        yield "data: [DONE]\n\n"




# ================= 统一预处理层（所有 /v1/* 协议共享） =================

# 各客户端的裁剪策略
# 按 token 裁剪（更准确，长文件不会误杀）
_AGENT_TRIM_POLICY = {
    "claude-code": {"max_input_tokens": 900000, "keep_system": True},
    "openwebui":   {"max_input_tokens": 900000, "keep_system": True},
    "hermes":      {"max_input_tokens": 900000, "keep_system": True},
    "cline":       {"max_input_tokens": 900000, "keep_system": True},
    "continue":    {"max_input_tokens": 900000, "keep_system": True},
    "codex":       {"max_input_tokens": 900000, "keep_system": True},
    "comfyui":     {"max_input_tokens": 8000,  "keep_system": True},
    "_default":    {"max_input_tokens": 900000, "keep_system": True},
}


def _trim_by_tokens(msgs, max_tokens, keep_system=True):
    """v7：禁用旧的逐消息裁剪，历史只允许由最终预算器处理。"""
    return msgs


def _parse_pools() -> dict:
    """读取模型池，优先从 models.conf 读取，其次从环境变量读取"""
    import os as _os
    pools = {"Pool-A": [], "Pool-B": [], "Pool-ALL": []}
    
    # 1. 尝试从 models.conf 解析 (优先)
    conf_path = "/ai/ai_dxos/configs/models.conf"
    if _os.path.exists(conf_path):
        try:
            with open(conf_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    parts = line.split("|")
                    if len(parts) >= 7:
                        api_name = parts[0].strip()
                        pool = parts[6].strip()
                        if pool in pools:
                            pools[pool].append(api_name)
        except Exception as e:
            print(f"   [parse-conf-err] {e}", flush=True)

    # 2. 如果 models.conf 没读到，回退到环境变量
    if not any(pools.values()):
        raw_a = _os.environ.get("POOL_A_MODELS", "").strip()
        raw_b = _os.environ.get("POOL_B_MODELS", "").strip()
        raw_all = _os.environ.get("POOL_ALL_MODELS", "").strip()
        if raw_a: pools["Pool-A"] = [m.strip() for m in raw_a.split(",") if m.strip()]
        if raw_b: pools["Pool-B"] = [m.strip() for m in raw_b.split(",") if m.strip()]
        if raw_all: pools["Pool-ALL"] = [m.strip() for m in raw_all.split(",") if m.strip()]
        
    return pools

def _strip_mg_prefix(model: str) -> tuple:
    """剥离 MG/ 或 MG_ 前缀，返回 (clean_name, has_prefix)
    v5.0: OpenWebUI 的 OpenAI 连接器会剥离 `MG/`（视为 provider），
    所以需同时支持下划线前缀 `MG_`
    """
    if model.startswith("MG/"):
        return model[3:], True
    if model.startswith("MG_"):
        return model[3:], True
    return model, False


def _normalize_forward_model(model: str) -> str:
    """保留模型池别名后缀；MG_ 只控制搜索开关，不改变池身份。"""
    clean, _ = _strip_mg_prefix(model)
    if clean.startswith("memory-llm"):
        return clean
    return model



def _get_active_models_sync() -> list:
    """请求 LiteLLM 获取当前真正存活的模型"""
    import os
    import httpx
    upstream_base = os.environ.get("UPSTREAM_BASE", "http://127.0.0.1:9980/v1")
    if not upstream_base.endswith("/v1"):
        upstream_base += "/v1"
    key = os.environ.get("LITELLM_MASTER_KEY", "sk-REDACTED")
    try:
        r = httpx.get(f"{upstream_base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=2.0)
        if r.status_code == 200:
            return [m["id"] for m in r.json().get("data", [])]
    except Exception as e:
        print(f"   [active-models-err] {e}", flush=True)
    return []

def _resolve_real_model(model: str) -> str:
    _clean_name, _ = _strip_mg_prefix(model)
    if _clean_name == M19_PUBLIC_NAME:
        return M19_PUBLIC_NAME

    pools = _parse_pools()
    active_models = _get_active_models_sync()

    # 🛑 需求：Claude 模型 -> 智能寻找当前激活的任意池（优先 ALL，其次 A，再次 B）
    if "claude" in model.lower() or "opus" in model.lower() or "sonnet" in model.lower() or "haiku" in model.lower():
        target_pools = ["Pool-ALL", "Pool-A", "Pool-B"]
        for pname in target_pools:
            for m in pools.get(pname, []):
                if m in active_models:
                    print(f"   [claude-mapping] 捕获 Claude {model} -> 动态映射至 {pname}: {m}", flush=True)
                    return m
        return model

    """v5.0：支持 memory-llm / memory-llm1 / memory-llm2 / MG/memory-llm"""
    clean, _ = _strip_mg_prefix(model)

    if not clean.startswith("memory-llm"):
        return model

    suffix = clean[len("memory-llm"):]  # "" | "1" | "2"

    if suffix == "1":
        target_pools = ["Pool-A"]
    elif suffix == "2":
        target_pools = ["Pool-B"]
    else:
        # 无后缀 memory-llm 严格只属于 Pool-ALL
        target_pools = ["Pool-ALL"]

    # 遍历目标池，找到真正存活的模型
    for pname in target_pools:
        for real_model in pools.get(pname, []):
            if real_model in active_models:
                print(f"   [resolve-pool] {model} -> {real_model} (pool={pname})", flush=True)
                return real_model

    print(f"   [resolve-pool] {model} 对应池没有活跃模型；拒绝跨池兜底", flush=True)
    return clean

def _resolve_real_model_legacy(model: str) -> str:
    """旧逻辑：从 LiteLLM /v1/models 动态挑（池未配置时的兜底）"""
    _url = f"{UPSTREAM}/v1/models"
    try:
        import httpx as _hx
        r = _hx.get(_url,
                    headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                    timeout=5).json()
        models = [m["id"] for m in r.get("data", [])]
        real = [m for m in models if not m.startswith("memory-llm")]
        _EXCLUDE = {
            "emb_bge_m3_gpu", "emb_bge_m3", "bge_reranker_v2_m3",
            "qwen25_coder_7b_awq", "qwen25_14b_awq",
            "Qwen3_Embedding_06B",
        }
        real_filtered = [m for m in real if m not in _EXCLUDE]
        print(f"   [resolve-legacy] models={models} filtered={real_filtered}", flush=True)
        if real_filtered:
            return real_filtered[0]
        if real:
            return real[0]
    except Exception as e:
        print(f"   [resolve-err] {type(e).__name__}: {e}", flush=True)
    return model


def _is_thinking_model(model: str) -> bool:
    """统一判断：模型是否是原生 thinking 模型"""
    if not model:
        return False
    m = model.lower()
    return any(k in m for k in ("glimmer", "gemma-4", "gemma_4"))


def _unified_preprocess(body: dict, model: str, agent_type: str = "_default") -> dict:
    """三协议共用预处理；不提前裁剪历史、工具或系统提示。"""

    original = body.get("model") or model
    try:
        clean, has_mg = _strip_mg_prefix(original)
        if "_has_mg_prefix" not in body:
            body["_has_mg_prefix"] = has_mg

        real_model = _resolve_real_model(model)
        body["_resolved_context_model"] = real_model

        normalized = _normalize_forward_model(original)
        if body.get("model"):
            body["model"] = normalized

        print(
            f"   [context-v7] model={model} real={real_model} "
            f"MG={body.get('_has_mg_prefix')}",
            flush=True
        )
    except Exception as exc:
        # 让最终预算器给出明确错误，不以猜测窗口继续转发。
        body["_resolved_context_model"] = ""
        body["_context_error"] = f"模型解析失败：{type(exc).__name__}: {exc}"
        return body

    enabled = body.pop("_enable_thinking", None)
    if enabled is True or _is_thinking_model(real_model):
        body["chat_template_kwargs"] = {"enable_thinking": True}
    else:
        body["chat_template_kwargs"] = {"enable_thinking": False}

    # 不调用 compute_budget，不做早期历史裁剪。
    return body



def _anthropic_to_openai_messages(msgs):
    """Claude Code 的 messages → OpenAI 格式
    处理 text / tool_use / tool_result 三种 content block
    """
    system_parts = []
    out = []
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "user")
        content = m.get("content", "")

        # content 是字符串
        if not isinstance(content, list):
            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue
            out.append({"role": role, "content": content if content is not None else ""})
            continue

        # content 是 list
        text_parts = []
        image_parts = []
        tool_calls = []
        tool_results = []

        for c in content:
            if isinstance(c, str):
                text_parts.append(c)
                continue
            if not isinstance(c, dict):
                continue
            ctype = c.get("type")
            if ctype == "text":
                text_parts.append(c.get("text", ""))
            elif ctype == "image":
                _source = c.get("source") or {}
                _image_url = ""
                if isinstance(_source, dict):
                    if _source.get("type") == "base64":
                        _media = _source.get("media_type", "image/jpeg")
                        _data = _source.get("data", "")
                        if _data:
                            _image_url = f"data:{_media};base64,{_data}"
                    elif _source.get("type") == "url":
                        _image_url = _source.get("url", "")
                if _image_url:
                    image_parts.append({
                        "type": "image_url",
                        "image_url": {"url": _image_url}
                    })
            elif ctype == "tool_use":
                tool_calls.append({
                    "id": c.get("id", "") or ("call_" + uuid.uuid4().hex[:16]),
                    "type": "function",
                    "function": {
                        "name": c.get("name", ""),
                        "arguments": json.dumps(c.get("input", {}), ensure_ascii=False),
                    },
                })
            elif ctype == "tool_result":
                _tr_content = c.get("content", "")
                if isinstance(_tr_content, list):
                    _tr_content = "\n".join(
                        (b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else str(b))
                        for b in _tr_content
                    )
                tool_results.append({
                    "tool_call_id": c.get("tool_use_id", ""),
                    "content": str(_tr_content),
                })
            elif ctype == "thinking":
                pass  # 忽略 thinking block

        # 生成 OpenAI 消息
        if role == "assistant" and tool_calls:
            msg = {"role": "assistant", "content": "\n".join(text_parts) or None}
            msg["tool_calls"] = tool_calls
            out.append(msg)
        elif role == "user" and tool_results:
            for tr in tool_results:
                out.append({"role": "tool", "tool_call_id": tr["tool_call_id"], "content": tr["content"]})
            if text_parts:
                _txt = "\n".join(text_parts)
                if _txt.strip():
                    out.append({"role": "user", "content": _txt})
        else:
            if role == "system":
                _txt = "\n".join(text_parts)
                if _txt:
                    system_parts.append(_txt)
                continue
            _plain_text = "\n".join(text_parts)
            if image_parts:
                _mixed = []
                if _plain_text:
                    _mixed.append({"type": "text", "text": _plain_text})
                _mixed.extend(image_parts)
                out.append({"role": role, "content": _mixed})
            else:
                out.append({"role": role, "content": _plain_text})

    if system_parts:
        out = [{"role": "system", "content": "\n\n".join(system_parts)}] + out

    return out
def resolve_identity(request: Request) -> dict:
    return {
        "user_id": request.headers.get("x-user-id") or "default_user",
        "workspace_id": request.headers.get("x-workspace-id") or "default_ws",
        "agent_type": request.headers.get("x-agent-type") or "openwebui",
        "model_allowlist": ["*"],
        "allow_silent_fallback": False,
    }

# ================= messages 规范化 =================
def _normalize_messages(messages):
    """规范化 messages（兼容所有引擎）：
    - 所有 system 合并为 1 个（放在首位）
    - 其他消息顺序不变
    - llama.cpp 只允许 1 个 system，必须合并
    """
    if not messages:
        return messages
    system_texts = []
    others = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "system":
            c = m.get("content", "")
            if c:
                system_texts.append(str(c))
        else:
            others.append(m)
    if system_texts:
        merged = "\n\n".join(system_texts)
        return [{"role": "system", "content": merged}] + others
    return others



# ================= Lifespan =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60, flush=True)
    print(f"[BOOT] _hooks = {_hooks}", flush=True)
    print(f"[BOOT] _worker = {_worker}", flush=True)
    print(f"[BOOT] _reconciler = {_reconciler}", flush=True)
    print(f"[BOOT] MEMORY_INJECT_ENABLED = {MEMORY_INJECT_ENABLED}", flush=True)
    print(f"🚀 Memory-Gateway (Transparent) 启动", flush=True)
    print(f"   监听端口: {GATEWAY_PORT}", flush=True)
    print(f"   上游底座: {UPSTREAM}", flush=True)
    _refresh_routing(force=True)
    print(f"   记忆注入: {'✅' if MEMORY_INJECT_ENABLED else '❌'}", flush=True)
    print(f"   记忆写回: {'✅' if MEMORY_WRITEBACK_ENABLED else '❌'}", flush=True)
    print("=" * 60, flush=True)
    if _worker:
        asyncio.create_task(_worker.start())
    if _reconciler:
        asyncio.create_task(_reconciler.start())
    yield
    if _worker:
        await _worker.stop()
    if _reconciler:
        await _reconciler.stop()

app = FastAPI(title="Memory-Gateway", lifespan=lifespan)

# 🛑 通道 B：独立安全接入 (自动注入)
from claude_bridge import claude_messages_handler
app.add_api_route("/messages", claude_messages_handler, methods=["POST"], name="claude_messages")


# ═══════════════════════════════════════════════════════════════
# v6.5：Network Controller 反向代理
# ═══════════════════════════════════════════════════════════════
import httpx as _nx

_NETWORK_CTRL = "http://127.0.0.1:9983"

async def _proxy_to_network_ctrl(path: str, method: str = "GET", json_body=None):
    try:
        async with _nx.AsyncClient(timeout=35.0) as c:
            r = await c.request(method, f"{_NETWORK_CTRL}{path}", json=json_body)
            try:
                return JSONResponse(r.json(), status_code=r.status_code)
            except Exception:
                return JSONResponse({"raw": r.text}, status_code=r.status_code)
    except Exception as e:
        return JSONResponse(
            {"error": f"network controller unreachable: {type(e).__name__}: {e}"},
            status_code=503)


@app.get("/network/status")
async def gw_network_status(force: bool = False):
    return await _proxy_to_network_ctrl(f"/network/status?force={str(force).lower()}")


@app.get("/network/nodes")
async def gw_network_nodes():
    return await _proxy_to_network_ctrl("/network/nodes")


@app.get("/network/probe")
async def gw_network_probe():
    return await _proxy_to_network_ctrl("/network/probe")


@app.get("/network/config")
async def gw_network_config():
    return await _proxy_to_network_ctrl("/network/config")


@app.post("/network/proxy/start")
async def gw_proxy_start():
    return await _proxy_to_network_ctrl("/network/proxy/start", method="POST")


@app.post("/network/proxy/stop")
async def gw_proxy_stop():
    return await _proxy_to_network_ctrl("/network/proxy/stop", method="POST")


@app.post("/network/proxy/restart")
async def gw_proxy_restart():
    return await _proxy_to_network_ctrl("/network/proxy/restart", method="POST")


@app.post("/network/proxy/switch")
async def gw_proxy_switch(payload: dict):
    return await _proxy_to_network_ctrl(
        "/network/proxy/switch", method="POST", json_body=payload)


@app.get("/network/proxy/logs")
async def gw_proxy_logs(lines: int = 30):
    return await _proxy_to_network_ctrl(f"/network/proxy/logs?lines={lines}")


@app.get("/metrics")
async def metrics():
    return metrics_endpoint()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def rate_limit_mw(request: Request, call_next):
    """限流中间件（仅作用于 /v1/chat/* 和 /v1/messages）"""
    path = request.url.path
    if path.startswith("/v1/chat") or path.startswith("/v1/messages") or path.startswith("/v1/responses"):
        user_id = request.headers.get("x-user-id", "anonymous")
        try:
            from app.use_cases.rate_limiter import get_limiter
            if not get_limiter().allow(user_id):
                gateway_rate_limited_total.labels(user_id=user_id).inc()
                return JSONResponse(
                    {"error": {"message": f"rate limit exceeded for {user_id}",
                               "type": "rate_limit_exceeded"}},
                    status_code=429)
        except Exception as e:
            print(f"   [rate_limit] 异常: {type(e).__name__}: {e}", flush=True)
    return await call_next(request)

# ================= /v1/models =================
@app.get("/v1/models")
async def list_models(request: Request):
    """v5.0: 根据池配置和当前真实活跃模型动态返回网关别名"""
    import os as _os
    pools = _parse_pools()
    active_models = _get_active_models_sync()

    # 判断哪些池子真正开启了模型
    has_all = any(m in active_models for m in pools.get("Pool-ALL", []))
    has_a = any(m in active_models for m in pools.get("Pool-A", []))
    has_b = any(m in active_models for m in pools.get("Pool-B", []))

    allowed = []
    if has_all:
        allowed.extend(["memory-llm", "MG_memory-llm"])
    if has_a:
        allowed.extend(["memory-llm1", "MG_memory-llm1"])
    if has_b:
        allowed.extend(["memory-llm2", "MG_memory-llm2"])

    # 兜底：如果一个都没开，默认给个 memory-llm 防止前端直接报错空白
    if not allowed:
        allowed = ["memory-llm", "MG_memory-llm"]

    # ★ 新增：1. 动态追加 Dxos 中实际 Running 的模型及对应的池虚拟名
    try:
        import json, os
        _state_file = "/ai/ai_dxos/configs/state/state.json"
        if os.path.exists(_state_file):
            with open(_state_file, "r") as _f:
                _state = json.load(_f)
                for _m, _info in _state.get("running_models", {}).items():
                    if _info.get("status") == "running":
                        # 1.1 追加真实模型名
                        if _m not in allowed:
                            allowed.append(_m)
                        # 1.2 追加对应池的虚拟名
                        _pool = _info.get("pool")
                        if _pool == "Pool-ALL":
                            for _v in ["memory-llm", "MG_memory-llm"]:
                                if _v not in allowed: allowed.append(_v)
                        elif _pool == "Pool-A":
                            for _v in ["memory-llm1", "MG_memory-llm1"]:
                                if _v not in allowed: allowed.append(_v)
                        elif _pool == "Pool-B":
                            for _v in ["memory-llm2", "MG_memory-llm2"]:
                                if _v not in allowed: allowed.append(_v)
    except Exception as _e:
        print(f"   [/v1/models] 读取 Dxos state 失败: {_e}", flush=True)

    # ★ 新增：2. 获取 LiteLLM 中真实可用的模型（兜底，防止 state 未同步）
    try:
        _active_models = _get_active_models_sync()
        for _m in _active_models:
            if _m not in allowed:
                allowed.append(_m)
    except Exception as _e:
        print(f"   [/v1/models] 获取 LiteLLM 模型失败: {_e}", flush=True)

    print(f"   [/v1/models] 动态检测 (ALL:{has_all} A:{has_a} B:{has_b})，返回: {allowed}", flush=True)

    now = 1677610602
    result_data = [
        {"id": name, "object": "model", "created": now, "owned_by": "gateway"}
        for name in allowed
    ]
    return JSONResponse({"object": "list", "data": result_data}, status_code=200)



# ================= /v1/chat/completions =================
class ChatRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    class Config:
        extra = "allow"

# ================= 用户记忆统计 /v1/users/{uid}/stats =================
@app.get("/v1/users/{user_id}/stats")
async def user_memory_stats(user_id: str, days: int = 7):
    """返回用户最近 N 天的记忆访问统计"""
    try:
        from app.use_cases.access_logger import get_user_stats
        stats = await get_user_stats(user_id, days=days)
        return JSONResponse(stats)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


# ================= 统计 /v1/stats =================
@app.get("/v1/stats")
async def stats():
    """返回限流统计、成本汇总"""
    try:
        from app.use_cases.rate_limiter import get_limiter
        limiter_stats = get_limiter().stats()
    except Exception:
        limiter_stats = {}
    return JSONResponse({
        "rate_limiter": limiter_stats,
        "note": "成本看 /metrics 里 gateway_cost_yuan",
    })


# ================= 池列表 /v1/pools =================
@app.get("/v1/pools")
async def list_pools():
    """返回池路由配置"""
    try:
        from app.use_cases.model_router import ModelRouter
        return JSONResponse(ModelRouter().describe())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ================= 健康检查 /healthz =================
@app.get("/healthz")
async def healthz():
    """综合健康检查"""
    out = {"ok": True, "checks": {}}
    # 网关
    out["checks"]["gateway"] = "ok"
    # Mem0
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get("http://127.0.0.1:8888/docs")
            out["checks"]["mem0"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        out["checks"]["mem0"] = f"err:{type(e).__name__}"
        out["ok"] = False
    # Qdrant
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get("http://127.0.0.1:6333/")
            out["checks"]["qdrant"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        out["checks"]["qdrant"] = f"err:{type(e).__name__}"
        out["ok"] = False
    # Meili
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get("http://127.0.0.1:7700/health")
            out["checks"]["meili"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        out["checks"]["meili"] = f"err:{type(e).__name__}"
    # bge-m3
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post("http://192.168.10.132:8003/embeddings",
                             json={"model": "models/bge-m3", "input": ["hi"]})
            out["checks"]["bge_m3"] = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        out["checks"]["bge_m3"] = f"err:{type(e).__name__}"
    # ★ 上游模型健康状态
    try:
        _up = await _check_upstream_models()
        out["upstream_models"] = _up
    except Exception as e:
        out["upstream_models"] = {"ok": False, "err": str(e)[:100]}

    return JSONResponse(out, status_code=200 if out["ok"] else 503)


# ================= LongCite 句子级引用 =================
LONGCITE_URL = os.environ.get("LONGCITE_URL", "http://127.0.0.1:8020")

@app.post("/v1/cite")
async def generate_citation(request: Request):
    """生成句子级引用（CPU 版 60s，按需调用）"""
    body = await request.json()
    context = body.get("context", "")
    query = body.get("query", "")
    max_new = body.get("max_new_tokens", 256)

    if not context or not query:
        raise HTTPException(400, "context 和 query 必填")

    try:
        async with httpx.AsyncClient(timeout=180.0) as c:
            r = await c.post(
                f"{LONGCITE_URL}/v1/cite",
                json={"context": context, "query": query, "max_new_tokens": max_new},
            )
            return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.TimeoutException:
        raise HTTPException(504, "LongCite 超时")
    except Exception as e:
        raise HTTPException(502, f"LongCite 不可达: {e}")


@app.get("/v1/cite/health")
async def cite_health():
    """LongCite 健康检查"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{LONGCITE_URL}/healthz")
            return JSONResponse(r.json())
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)


# ================= RAG 文档管理 =================
@app.get("/v1/rag/documents")
async def rag_list(request: Request):
    """列出当前用户的 RAG 文档"""
    ident = resolve_identity(request)
    user_id = ident["user_id"]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post("http://127.0.0.1:7700/indexes/documents/search",
                             headers={"Authorization": f"Bearer {os.environ.get('MEILISEARCH_API_KEY','')}"},
                             json={"q": "", "limit": 100,
                                   "filter": f'user_id = "{user_id}"'})
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                return JSONResponse({
                    "user_id": user_id,
                    "count": len(hits),
                    "documents": [
                        {"id": h.get("id"), "title": h.get("title"),
                         "content": (h.get("content") or "")[:200]}
                        for h in hits
                    ],
                })
            return JSONResponse({"error": f"meili_{r.status_code}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.delete("/v1/rag/documents/{doc_id}")
async def rag_delete(doc_id: str, request: Request):
    """删除 RAG 文档（含所有分块）"""
    ident = resolve_identity(request)
    user_id = ident["user_id"]
    try:
        deleted = {"meili": 0, "qdrant": 0, "errors": []}

        # 1. 列出该 doc_id 的所有分块 id
        chunk_ids = [doc_id]  # 兼容未分块的老数据
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.post(
                    "http://127.0.0.1:7700/indexes/documents/search",
                    headers={"Authorization": f"Bearer {os.environ.get('MEILISEARCH_API_KEY','')}"},
                    json={"q": "", "limit": 500,
                          "filter": f'doc_id = "{doc_id}"'})
                if r.status_code == 200:
                    for h in r.json().get("hits", []):
                        cid = h.get("id")
                        if cid and cid not in chunk_ids:
                            chunk_ids.append(cid)
        except Exception as e:
            deleted["errors"].append(f"list:{type(e).__name__}")

        print(f"   [rag-delete] doc_id={doc_id} 分块数={len(chunk_ids)}", flush=True)

        # 2. Meili 删除所有分块
        for cid in chunk_ids:
            try:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.delete(
                        f"http://127.0.0.1:7700/indexes/documents/documents/{cid}",
                        headers={"Authorization": f"Bearer {os.environ.get('MEILISEARCH_API_KEY','')}"})
                    if r.status_code in (200, 202):
                        deleted["meili"] += 1
            except Exception as e:
                deleted["errors"].append(f"meili:{cid}:{type(e).__name__}")

        # 3. Qdrant 删除所有分块
        try:
            from adapters.qdrant_rag import get_rag
            rag = get_rag()
            qids = [rag._id(cid) for cid in chunk_ids]
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.post(
                    f"{rag.qdrant_url}/collections/{rag.collection}/points/delete",
                    params={"wait": "true"},
                    json={"points": qids})
                if r.status_code in (200, 201):
                    deleted["qdrant"] = len(qids)
        except Exception as e:
            deleted["errors"].append(f"qdrant:{type(e).__name__}")

        return JSONResponse({
            "ok": True, "doc_id": doc_id,
            "chunks": len(chunk_ids),
            "deleted": deleted})
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


# ================= 用户管理 =================
@app.get("/v1/users/{user_id}/memories")
async def user_memories(user_id: str, request: Request, limit: int = 50):
    """列出用户的 Mem0 记忆"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"http://127.0.0.1:8888/memories",
                params={"user_id": user_id},
                headers={"X-API-Key": os.environ.get("MEM0_ADMIN_KEY", "")})
            if r.status_code != 200:
                return JSONResponse({"error": f"mem0_{r.status_code}"}, status_code=500)
            body = r.json()
            mems = body.get("results") or body if isinstance(body, list) else body.get("results", [])
            if not isinstance(mems, list):
                mems = []
            return JSONResponse({
                "user_id": user_id,
                "count": len(mems[:limit]),
                "memories": [
                    {"id": m.get("id"), "memory": m.get("memory"),
                     "created_at": m.get("created_at")}
                    for m in mems[:limit]
                ],
            })
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.delete("/v1/users/{user_id}/memories/{memory_id}")
async def user_memory_delete(user_id: str, memory_id: str, request: Request):
    """删除指定记忆"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.delete(
                f"http://127.0.0.1:8888/memories/{memory_id}",
                headers={"X-API-Key": os.environ.get("MEM0_ADMIN_KEY", "")})
            return JSONResponse({"ok": r.status_code == 200,
                                 "status": r.status_code}, status_code=200)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


# ================= RAG 文件上传 /v1/rag/upload =================
@app.post("/v1/rag/upload")
async def rag_upload_file(request: Request, ):
    """上传文件（PDF/Word/Markdown/TXT）到 RAG 索引

    两种请求体：
    - multipart/form-data: file=<文件>, title=<可选>
    - application/json: {"file_path": "/本地/路径", "title": "..."}
    """
    ident = resolve_identity(request)
    user_id = ident["user_id"]
    ct = request.headers.get("content-type", "")

    # ---------- multipart 分支 ----------
    if "multipart/form-data" in ct:
        try:
            form = await request.form()
        except Exception as e:
            raise HTTPException(400, f"multipart 解析失败: {type(e).__name__}: {e}")
        file = form.get("file")
        if not file:
            raise HTTPException(400, "缺少 file 字段")
        title = form.get("title") or getattr(file, "filename", "uploaded")
        raw = await file.read()
        fname = getattr(file, "filename", "upload.bin")

        import tempfile, os
        suffix = os.path.splitext(fname)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            from adapters.doc_parser import parse_document
            content = parse_document(tmp_path)
            print(f"   [rag-upload] {fname} ({len(raw)} bytes) → 解析 {len(content)} 字", flush=True)
            if not content or content.startswith("["):
                raise HTTPException(400, f"解析失败: {content[:200]}")
            from adapters.meili_client import get_meili
            from adapters.qdrant_rag import get_rag
            from app.workers.rag_indexer import RagIndexer
            import asyncio as _aio

            # ★ 文件大小决定同步/异步
            _size_kb = len(raw) // 1024
            _SYNC_LIMIT_KB = 200   # 200KB 以下同步
            _indexer = RagIndexer(get_meili(), qdrant_rag=get_rag())

            if _size_kb <= _SYNC_LIMIT_KB:
                # 小文件：同步处理
                doc_id = await _indexer.index_document(user_id, title, content)
                print(f"   [rag-upload] {fname} ({_size_kb}KB) 同步处理完成", flush=True)
            else:
                # 大文件：异步处理
                import hashlib as _hl
                doc_id = "doc_" + _hl.md5(f"{user_id}{title}{content[:500]}".encode()).hexdigest()[:16]

                async def _bg():
                    try:
                        _d = await _indexer.index_document(user_id, title, content, doc_id=doc_id)
                        print(f"   [rag-upload-bg] {fname} ({_size_kb}KB) 后台完成: {_d}", flush=True)
                    except Exception as _e:
                        print(f"   [rag-upload-bg] {fname} 失败: {type(_e).__name__}: {_e}", flush=True)

                # ★ 用线程（最可靠）
                _run_index_in_thread(_indexer, user_id, title, content, doc_id, fname, _size_kb)
                print(f"   [rag-upload] {fname} ({_size_kb}KB) 后台异步处理中", flush=True)

                # 返回"处理中"状态
                return JSONResponse({
                    "ok": True,
                    "doc_id": doc_id,
                    "user_id": user_id,
                    "filename": fname,
                    "chars": len(content),
                    "title": title,
                    "status": "processing",
                    "message": f"文件 {_size_kb}KB 较大，后台处理中"
                })
            if not doc_id:
                raise HTTPException(500, "index failed")
            return JSONResponse({
                "ok": True, "doc_id": doc_id, "user_id": user_id,
                "filename": fname, "chars": len(content), "title": title,
            })
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ---------- JSON 分支 ----------
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "请求体必须是 multipart 或合法 JSON")

    file_path = body.get("file_path")
    title = body.get("title", "")
    content = ""

    if file_path:
        try:
            from adapters.doc_parser import parse_document
            content = parse_document(file_path)
            if not title:
                title = file_path.split("/")[-1]
        except Exception as e:
            raise HTTPException(500, f"解析失败: {type(e).__name__}: {e}")
    else:
        content = body.get("content", "")

    if not content:
        raise HTTPException(400, "content 或 file_path 必须提供")
    if content.startswith("["):
        raise HTTPException(400, f"解析失败: {content[:200]}")

    try:
        from adapters.meili_client import get_meili
        from adapters.qdrant_rag import get_rag
        from app.workers.rag_indexer import RagIndexer
        indexer = RagIndexer(get_meili(), qdrant_rag=get_rag())
        doc_id = await indexer.index_document(user_id, title, content)
        if not doc_id:
            raise HTTPException(500, "index failed")
        return JSONResponse({
            "ok": True, "doc_id": doc_id, "user_id": user_id,
            "title": title, "chars": len(content),
        })
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ================= RAG 文档上传 /v1/rag/documents =================
@app.post("/v1/rag/documents")
async def rag_upload(request: Request):
    """上传文档到 RAG 索引"""
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(400, f"请求体必须是合法 JSON: {type(e).__name__}")
    ident = resolve_identity(request)
    user_id = ident["user_id"]
    title = body.get("title", "")
    content = body.get("content", "")
    if not content:
        raise HTTPException(400, "content is required")
    try:
        from adapters.meili_client import get_meili
        from adapters.qdrant_rag import get_rag
        from app.workers.rag_indexer import RagIndexer
        indexer = RagIndexer(get_meili(), qdrant_rag=get_rag())
        doc_id = await indexer.index_document(user_id, title, content)
        if not doc_id:
            raise HTTPException(500, "index failed")
        return JSONResponse({"ok": True, "doc_id": doc_id, "user_id": user_id})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ================= OpenAI Responses API 兼容 /v1/responses =================
@app.post("/v1/responses")
async def openai_responses(request: Request):
    """
    OpenAI Responses API -> LiteLLM Chat Completions adapter.
    Supports input/messages, instructions, function tools,
    function_call/function_call_output, JSON response and SSE.
    """
    import json
    import time
    import uuid
    import httpx

    def make_id(prefix):
        return prefix + uuid.uuid4().hex[:24]

    def as_text(value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)

    def response_shell(response_id, model_name, created):
        return {
            "id": response_id,
            "object": "response",
            "created_at": created,
            "status": "in_progress",
            "error": None,
            "incomplete_details": None,
            "instructions": None,
            "max_output_tokens": None,
            "model": model_name,
            "output": [],
            "parallel_tool_calls": True,
            "previous_response_id": None,
            "reasoning": {"effort": None, "summary": None},
            "store": False,
            "temperature": None,
            "text": {"format": {"type": "text"}},
            "tool_choice": "auto",
            "tools": [],
            "top_p": 1.0,
            "truncation": "disabled",
            "usage": None,
            "user": None,
            "metadata": {}
        }

    def content_to_chat(content):
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return as_text(content)

        converted = []
        for part in content:
            if not isinstance(part, dict):
                continue
            typ = part.get("type", "")
            if typ in ("input_text", "output_text", "text"):
                converted.append({
                    "type": "text",
                    "text": as_text(part.get("text", ""))
                })
            elif typ in ("input_image", "image_url"):
                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                if not image_url:
                    image_url = part.get("image_url")
                if image_url:
                    converted.append({
                        "type": "image_url",
                        "image_url": (
                            image_url if isinstance(image_url, dict)
                            else {"url": image_url}
                        )
                    })
        return converted if converted else ""

    def convert_input(body):
        messages = []
        instructions = body.get("instructions")
        if instructions:
            messages.append({"role": "system", "content": as_text(instructions)})

        source = body.get("input", body.get("messages", []))
        if isinstance(source, str):
            if source:
                messages.append({"role": "user", "content": source})
            return messages

        if not isinstance(source, list):
            raise ValueError("input 必须是字符串或数组")

        for item in source:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
                continue
            if not isinstance(item, dict):
                continue

            typ = item.get("type", "")
            if typ == "function_call":
                call_id = item.get("call_id") or item.get("id") or make_id("call_")
                name = item.get("name", "")
                args = item.get("arguments", "{}")
                if not isinstance(args, str):
                    args = as_text(args)
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": args}
                    }]
                })
                continue

            if typ == "function_call_output":
                call_id = item.get("call_id") or item.get("id")
                if not call_id:
                    raise ValueError("function_call_output 缺少 call_id")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": as_text(item.get("output", ""))
                })
                continue

            role = item.get("role", "user")
            if role not in ("system", "developer", "user", "assistant", "tool"):
                role = "user"

            content = content_to_chat(item.get("content", ""))
            msg = {"role": role, "content": content}

            if item.get("name"):
                msg["name"] = item["name"]
            if item.get("tool_call_id"):
                msg["tool_call_id"] = item["tool_call_id"]
            if item.get("tool_calls"):
                msg["tool_calls"] = item["tool_calls"]

            messages.append(msg)

        return messages

    def convert_tools(source_tools):
        result = []
        for tool in source_tools or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") != "function":
                # 当前网关只转发 function 工具；不伪装支持内置工具
                continue
            fn = tool.get("function")
            if isinstance(fn, dict):
                fn_data = dict(fn)
            else:
                fn_data = {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {
                        "type": "object", "properties": {}
                    })
                }
            if not fn_data.get("name"):
                continue
            result.append({"type": "function", "function": fn_data})
        return result

    def convert_tool_choice(choice):
        if choice is None:
            return None
        if isinstance(choice, str):
            if choice in ("auto", "none", "required"):
                return choice
            return None
        if isinstance(choice, dict):
            if choice.get("type") == "function":
                name = choice.get("name")
                if not name and isinstance(choice.get("function"), dict):
                    name = choice["function"].get("name")
                if name:
                    return {"type": "function", "function": {"name": name}}
        return None

    def usage_from_chat(usage):
        if not isinstance(usage, dict):
            return None
        prompt = usage.get("prompt_tokens", 0) or 0
        completion = usage.get("completion_tokens", 0) or 0
        return {
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": usage.get("total_tokens", prompt + completion),
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0}
        }

    def build_output(message):
        output = []
        text_parts = message.get("content")
        if isinstance(text_parts, str):
            text_value = text_parts
        elif isinstance(text_parts, list):
            text_value = "".join(
                p.get("text", "") for p in text_parts
                if isinstance(p, dict) and p.get("type") in ("text", "output_text")
            )
        else:
            text_value = ""

        if text_value or not message.get("tool_calls"):
            output.append({
                "id": make_id("msg_"),
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": text_value,
                    "annotations": []
                }]
            })

        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments", "{}")
            if not isinstance(args, str):
                args = as_text(args)
            output.append({
                "id": make_id("fc_"),
                "type": "function_call",
                "status": "completed",
                "call_id": call.get("id") or make_id("call_"),
                "name": fn.get("name", ""),
                "arguments": args
            })
        return output

    def sse(event_type, payload):
        payload = dict(payload)
        payload["type"] = event_type
        return "event: " + event_type + "\ndata: " + json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ) + "\n\n"

    try:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": {"message": "请求体必须是 JSON 对象", "type": "invalid_request_error"}},
                status_code=400
            )

        if body.get("previous_response_id"):
            return JSONResponse(
                {"error": {
                    "message": "当前网关尚未实现 previous_response_id 会话存储；请在 input 中传入完整上下文。",
                    "type": "unsupported_parameter",
                    "param": "previous_response_id"
                }},
                status_code=400
            )

        raw_model = body.get("model") or "yy35b_q6"
        _clean_raw_model, _has_mg_prefix = _strip_mg_prefix(raw_model)
        body["_has_mg_prefix"] = bool(_has_mg_prefix)
        body["_force_search"] = bool(_has_mg_prefix)
        try:
            model = _resolve_real_model(raw_model)
            if not model:
                model = raw_model
        except Exception:
            model = raw_model

        messages = convert_input(body)
        if not messages:
            return JSONResponse(
                {"error": {"message": "input 不能为空", "type": "invalid_request_error"}},
                status_code=400
            )

        tools = convert_tools(body.get("tools"))
        chat_body = {
            "model": model,
            "messages": messages,
            "stream": bool(body.get("stream", False)),
            "_has_mg_prefix": body["_has_mg_prefix"],
            "_force_search": body["_force_search"],
        }

        if tools:
            chat_body["tools"] = tools
            chat_body["parallel_tool_calls"] = body.get("parallel_tool_calls", True)

        choice = convert_tool_choice(body.get("tool_choice"))
        if choice is not None and tools:
            chat_body["tool_choice"] = choice

        for key in ("temperature", "top_p", "stop", "seed"):
            if key in body and body[key] is not None:
                chat_body[key] = body[key]

        requested_max = body.get("max_output_tokens", body.get("max_tokens", 4096))
        try:
            requested_max = int(requested_max)
        except Exception:
            requested_max = 4096
        requested_max = max(1, min(requested_max, 8192))
        try:
            if "_model_cap" in globals():
                requested_max = min(requested_max, max(1, int(_model_cap(model))))
        except Exception:
            pass
        chat_body["max_tokens"] = requested_max

        # Responses 与 Chat Completions 共用同一套记忆/搜索 Hook
        # v6: Responses 已转换成 OpenAI messages/tools，统一预处理在此执行
        _responses_agent_type = request.headers.get("x-agent-type", "_default")
        chat_body = _unified_preprocess(
            chat_body, model, agent_type=_responses_agent_type
        )
        model = chat_body.get("model") or model
        try:
            chat_body["_ident"] = resolve_identity(request)
        except Exception as _identity_error:
            print(f"   [Responses identity] 解析失败: {_identity_error}", flush=True)
        if MEMORY_INJECT_ENABLED and _hooks:
            try:
                _ident = resolve_identity(request)
                chat_body["_ident"] = _ident
                for _msg in reversed(chat_body.get("messages", [])):
                    if isinstance(_msg, dict) and _msg.get("role") == "user":
                        chat_body["_original_user_content"] = _msg.get("content", "")
                        break
                if _is_hermes_request(chat_body, request):
                    chat_body["_skip_search"] = True
                chat_body = await _hooks.async_pre_call_hook(
                    {"token": "mock"}, {}, chat_body, "completion"
                )
                print(
                    f"   [Responses Hook] 完成 user={_ident.get('user_id', 'unknown')} "
                    f"MG={chat_body.get('_has_mg_prefix')}",
                    flush=True
                )
            except Exception as _hook_error:
                print(
                    f"   [Responses Hook] 失败，透传原始请求: "
                    f"{type(_hook_error).__name__}: {_hook_error}",
                    flush=True
                )

        # v6: Hook 注入完成后压缩历史，最后检查最终上下文预算
        try:
            chat_body = await _compress_history_async(
                chat_body, chat_body.get("_ident") or {}
            )
        except Exception as _compress_error:
            print(f"   [Responses compress] 跳过: {_compress_error}", flush=True)

        chat_body = _enforce_context_window(chat_body, model)
        if chat_body.get("_context_error"):
            return JSONResponse(
                {
                    "error": {
                        "message": chat_body["_context_error"],
                        "type": "context_window_exceeded"
                    }
                },
                status_code=400
            )
        try:
            requested_max = int(chat_body.get("max_tokens") or requested_max)
        except Exception:
            requested_max = 2048
        response_id = make_id("resp_")
        created = int(time.time())
        response_obj = response_shell(response_id, model, created)
        response_obj["max_output_tokens"] = requested_max
        response_obj["instructions"] = body.get("instructions")
        response_obj["parallel_tool_calls"] = body.get("parallel_tool_calls", True)
        response_obj["tool_choice"] = body.get("tool_choice", "auto")
        response_obj["tools"] = body.get("tools", [])
        response_obj["temperature"] = body.get("temperature")
        response_obj["top_p"] = body.get("top_p")
        response_obj["metadata"] = body.get("metadata") or {}

        upstream = str(UPSTREAM).rstrip("/") + "/v1/chat/completions"
        api_key = str(globals().get("LITELLM_KEY", "") or "")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        else:
            incoming_auth = request.headers.get("authorization")
            if incoming_auth:
                headers["Authorization"] = incoming_auth

        if not body.get("stream", False):
            async with httpx.AsyncClient(timeout=300.0) as client:
                upstream_response = await client.post(
                    upstream, json=chat_body, headers=headers
                )

            if upstream_response.status_code >= 400:
                return JSONResponse(
                    {
                        "error": {
                            "message": "上游模型服务返回 HTTP " + str(upstream_response.status_code),
                            "type": "upstream_error",
                            "code": "upstream_http_error"
                        }
                    },
                    status_code=502
                )

            try:
                result = upstream_response.json()
            except Exception:
                return JSONResponse(
                    {"error": {"message": "上游返回的不是有效 JSON", "type": "upstream_error"}},
                    status_code=502
                )

            choices = result.get("choices") or []
            if not choices:
                return JSONResponse(
                    {"error": {"message": "上游没有返回 choices", "type": "upstream_error"}},
                    status_code=502
                )

            choice0 = choices[0]
            message = choice0.get("message") or {}
            response_obj["output"] = build_output(message)
            response_obj["status"] = (
                "incomplete" if choice0.get("finish_reason") == "length"
                else "completed"
            )
            if response_obj["status"] == "incomplete":
                response_obj["incomplete_details"] = {"reason": "max_output_tokens"}
            response_obj["usage"] = usage_from_chat(result.get("usage"))
            response_obj["model"] = result.get("model") or model
            return JSONResponse(response_obj)

        async def response_stream():
            seq = 0
            text_value = ""
            text_item = None
            tool_items = {}
            tool_order = []
            finish_reason = None
            usage = None
            response_obj["status"] = "in_progress"

            def emit(event_type, data):
                nonlocal seq
                seq += 1
                data["sequence_number"] = seq
                return sse(event_type, data)

            yield emit("response.created", {"response": dict(response_obj)})
            yield emit("response.in_progress", {"response": dict(response_obj)})

            try:
                timeout = httpx.Timeout(300.0, connect=15.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST", upstream, json=chat_body, headers=headers
                    ) as upstream_response:
                        if upstream_response.status_code >= 400:
                            await upstream_response.aread()
                            yield emit("response.failed", {
                                "response": {
                                    **response_obj,
                                    "status": "failed",
                                    "error": {
                                        "message": "上游模型服务返回 HTTP " + str(upstream_response.status_code),
                                        "type": "upstream_error",
                                        "code": "upstream_http_error"
                                    }
                                }
                            })
                            yield "data: [DONE]\n\n"
                            return

                        async for line in upstream_response.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data_line = line[5:].strip()
                            if data_line == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_line)
                            except Exception:
                                continue

                            if chunk.get("usage"):
                                usage = chunk["usage"]

                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}
                            finish_reason = choices[0].get("finish_reason") or finish_reason

                            content = delta.get("content")
                            if isinstance(content, str) and content:
                                if text_item is None:
                                    text_item = {
                                        "id": make_id("msg_"),
                                        "type": "message",
                                        "status": "in_progress",
                                        "role": "assistant",
                                        "content": []
                                    }
                                    yield emit("response.output_item.added", {
                                        "response_id": response_id,
                                        "output_index": 0,
                                        "item": text_item
                                    })
                                    yield emit("response.content_part.added", {
                                        "response_id": response_id,
                                        "item_id": text_item["id"],
                                        "output_index": 0,
                                        "content_index": 0,
                                        "part": {"type": "output_text", "text": "", "annotations": []}
                                    })
                                text_value += content
                                yield emit("response.output_text.delta", {
                                    "response_id": response_id,
                                    "item_id": text_item["id"],
                                    "output_index": 0,
                                    "content_index": 0,
                                    "delta": content
                                })

                            for tc in delta.get("tool_calls") or []:
                                index = tc.get("index", 0)
                                if index not in tool_items:
                                    tool_items[index] = {
                                        "id": make_id("fc_"),
                                        "type": "function_call",
                                        "status": "in_progress",
                                        "call_id": tc.get("id") or make_id("call_"),
                                        "name": "",
                                        "arguments": ""
                                    }
                                    tool_order.append(index)
                                    output_index = len(tool_order) - 1 + (1 if text_item else 0)
                                    yield emit("response.output_item.added", {
                                        "response_id": response_id,
                                        "output_index": output_index,
                                        "item": dict(tool_items[index])
                                    })

                                item = tool_items[index]
                                if tc.get("id"):
                                    item["call_id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    item["name"] += fn["name"]
                                arg_delta = fn.get("arguments")
                                if isinstance(arg_delta, str) and arg_delta:
                                    item["arguments"] += arg_delta
                                    output_index = len(tool_order) - 1 + (1 if text_item else 0)
                                    yield emit("response.function_call_arguments.delta", {
                                        "response_id": response_id,
                                        "item_id": item["id"],
                                        "output_index": output_index,
                                        "delta": arg_delta
                                    })

                output = []
                if text_item is not None:
                    text_item["status"] = "completed"
                    text_item["content"] = [{
                        "type": "output_text",
                        "text": text_value,
                        "annotations": []
                    }]
                    output.append(text_item)
                    yield emit("response.output_text.done", {
                        "response_id": response_id,
                        "item_id": text_item["id"],
                        "output_index": 0,
                        "content_index": 0,
                        "text": text_value
                    })
                    yield emit("response.content_part.done", {
                        "response_id": response_id,
                        "item_id": text_item["id"],
                        "output_index": 0,
                        "content_index": 0,
                        "part": text_item["content"][0]
                    })
                    yield emit("response.output_item.done", {
                        "response_id": response_id,
                        "output_index": 0,
                        "item": text_item
                    })

                for position, index in enumerate(tool_order):
                    item = tool_items[index]
                    item["status"] = "completed"
                    output_index = position + (1 if text_item else 0)
                    yield emit("response.function_call_arguments.done", {
                        "response_id": response_id,
                        "item_id": item["id"],
                        "output_index": output_index,
                        "arguments": item["arguments"]
                    })
                    yield emit("response.output_item.done", {
                        "response_id": response_id,
                        "output_index": output_index,
                        "item": item
                    })
                    output.append(item)

                response_obj["output"] = output
                response_obj["usage"] = usage_from_chat(usage)
                response_obj["status"] = (
                    "incomplete" if finish_reason == "length" else "completed"
                )
                if response_obj["status"] == "incomplete":
                    response_obj["incomplete_details"] = {"reason": "max_output_tokens"}
                yield emit("response.completed", {"response": response_obj})
                yield "data: [DONE]\n\n"

            except Exception as exc:
                response_obj["status"] = "failed"
                response_obj["error"] = {
                    "message": "流式上游请求失败：" + str(exc)[:500],
                    "type": "upstream_error"
                }
                yield emit("response.failed", {"response": response_obj})
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            response_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except ValueError as exc:
        return JSONResponse(
            {"error": {"message": str(exc), "type": "invalid_request_error"}},
            status_code=400
        )
    except Exception as exc:
        return JSONResponse(
            {
                "error": {
                    "message": "Responses 网关处理失败：" + str(exc)[:500],
                    "type": "gateway_error"
                }
            },
            status_code=500
        )


# ================= Anthropic 协议兼容 /v1/messages =================
@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    """Claude Code / Anthropic 协议 → OpenAI 协议转发 (终极重构版)"""
    t0 = time.perf_counter()
    body = await request.json()
    
    auth = request.headers.get("authorization") or ""
    if not auth:
        ak = request.headers.get("x-api-key", "")
        if ak: auth = f"Bearer {ak}"

    _raw_model = body.get("model", "claude-opus-5")
    _clean_raw_model, _has_mg_prefix = _strip_mg_prefix(_raw_model)
    body["_has_mg_prefix"] = bool(_has_mg_prefix)
    body["_force_search"] = bool(_has_mg_prefix)

    _has_tools = bool(body.get("tools") and len(body["tools"]) > 0)

    # memory-llm / memory-llm1 / memory-llm2 必须保留客户端指定的池
    if _clean_raw_model.startswith("memory-llm"):
        model = _resolve_real_model(_raw_model)
        _route_key = None
        if LITELLM_KEY:
            auth = f"Bearer {LITELLM_KEY}"
    else:
        # Claude 等非池别名继续沿用既有动态路由
        model, _route_key = _get_routing(_has_tools)
        if "reranker" in model.lower() or "embedding" in model.lower():
            model = "memory-llm"
            _route_key = None

    if _route_key:
        auth = f"Bearer {_route_key}"

    # max_tokens 处理
    _req_max = body.get("max_tokens")
    _win = MODEL_CONTEXT_WINDOWS.get(model, 32768)
    _model_cap = 65536 if isinstance(model, str) and "flint" in model.lower() else 8192
    _safe_by_window = max(256, _win - 4096)
    _effective_cap = min(_model_cap, _safe_by_window)
    body["max_tokens"] = min(_req_max or 2048, _effective_cap)

    stream = bool(body.get("stream"))
    
    # 组装 OpenAI 请求
    msgs = list(body.get("messages") or [])
    system = body.get("system")
    if system:
        sys_text = "\n".join((x.get("text", "") if isinstance(x, dict) else str(x)) for x in system) if isinstance(system, list) else str(system)
        msgs = [{"role": "system", "content": sys_text}] + msgs

    # Anthropic tool_use/tool_result 必须先转换成 OpenAI 标准消息
    _has_tool_results = any(
        isinstance(_m, dict)
        and _m.get("role") == "user"
        and isinstance(_m.get("content"), list)
        and any(
            isinstance(_c, dict) and _c.get("type") == "tool_result"
            for _c in _m["content"]
        )
        for _m in msgs
    )
    msgs = _anthropic_to_openai_messages(msgs)

    # 首轮工具调用保留引导；工具结果返回后允许模型正常组织最终答复
    if _has_tools and not _has_tool_results:
        agent_prompt = "You are an autonomous AI agent. You MUST use the provided tools via function calling. Do not explain, just call the tool.\n\n"
        if msgs and msgs[0].get("role") == "system":
            msgs[0]["content"] = agent_prompt + msgs[0]["content"]
        else:
            msgs.insert(0, {"role": "system", "content": agent_prompt})

    openai_body = {
        "model": model,
        "messages": msgs,
        "max_tokens": body["max_tokens"],
        "stream": False  # 强制非流式
    }
    if body.get("temperature") is not None:
        openai_body["temperature"] = body["temperature"]
    if body.get("tools"):
        openai_body["tools"] = [
            {"type": "function", "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            }} for t in body["tools"]
        ]

    # Anthropic 转换完成后再执行 Hook，确保 Hook 看到 OpenAI 标准 messages/tools
    openai_body["_has_mg_prefix"] = body["_has_mg_prefix"]
    openai_body["_force_search"] = body["_force_search"]

    # v6: Anthropic 已转换成 OpenAI messages/tools，统一预处理在此执行
    openai_body = _unified_preprocess(
        openai_body, model, agent_type="claude-code"
    )
    model = openai_body.get("model") or model
    openai_body["stream"] = False
    try:
        openai_body["_ident"] = resolve_identity(request)
    except Exception as _identity_error:
        print(f"   [Anthropic identity] 解析失败: {_identity_error}", flush=True)
    if MEMORY_INJECT_ENABLED and _hooks:
        try:
            _ident = resolve_identity(request)
            openai_body["_ident"] = _ident
            for _msg in reversed(openai_body.get("messages", [])):
                if isinstance(_msg, dict) and _msg.get("role") == "user":
                    openai_body["_original_user_content"] = _msg.get("content", "")
                    break
            if _is_hermes_request(openai_body, request):
                openai_body["_skip_search"] = True
            openai_body = await _hooks.async_pre_call_hook(
                {"token": "mock"}, {}, openai_body, "completion"
            )
            print(
                f"   [Anthropic Hook] 完成 user={_ident.get('user_id', 'unknown')} "
                f"MG={openai_body.get('_has_mg_prefix')}",
                flush=True
            )
        except Exception as _hook_error:
            print(
                f"   [Anthropic Hook] 失败，透传原始请求: "
                f"{type(_hook_error).__name__}: {_hook_error}",
                flush=True
            )

    # 请求上游
    # v6: Hook 注入完成后压缩历史，执行最终上下文检查
    try:
        openai_body = await _compress_history_async(
            openai_body, openai_body.get("_ident") or {}
        )
    except Exception as _compress_error:
        print(f"   [Anthropic compress] 跳过: {_compress_error}", flush=True)

    openai_body = _enforce_context_window(openai_body, model)
    if openai_body.get("_context_error"):
        return JSONResponse(
            {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": openai_body["_context_error"]
                }
            },
            status_code=400
        )
    # 最终保险：合并全部 system，并确保 system 位于第一条消息
    _roles_before = [
        str(m.get("role", "?")) for m in (openai_body.get("messages") or [])
        if isinstance(m, dict)
    ]
    openai_body["messages"] = _normalize_messages(
        openai_body.get("messages") or []
    )
    _roles_after = [
        str(m.get("role", "?")) for m in (openai_body.get("messages") or [])
        if isinstance(m, dict)
    ]
    print(
        f"   [Anthropic outbound] model={model} "
        f"roles_before={_roles_before} roles_after={_roles_after} "
        f"tools={len(openai_body.get('tools') or [])}",
        flush=True
    )

    async with httpx.AsyncClient(timeout=300.0) as c:
        r = await c.post(
            f"{UPSTREAM}/v1/chat/completions",
            headers={"Authorization": auth, "Content-Type": "application/json"},
            json=openai_body
        )

        if r.status_code >= 400:
            try:
                _up_error = r.json()
            except Exception:
                _up_error = {"error": {"message": r.text[:1500]}}

            _err_obj = _up_error.get("error", _up_error) if isinstance(_up_error, dict) else _up_error
            _err_msg = (
                _err_obj.get("message", str(_err_obj))
                if isinstance(_err_obj, dict) else str(_err_obj)
            )
            print(
                f"   [Anthropic upstream-error] HTTP={r.status_code} "
                f"message={str(_err_msg)[:1200]}",
                flush=True
            )
            return JSONResponse(
                {
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": str(_err_msg)[:2000]
                    }
                },
                status_code=r.status_code
            )

        try:
            resp = r.json()
        except Exception as _json_error:
            print(
                f"   [Anthropic upstream-error] invalid JSON: {_json_error}",
                flush=True
            )
            return JSONResponse(
                {
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": "上游返回了无法解析的响应。"
                    }
                },
                status_code=502
            )

    msg_id = "msg_" + uuid.uuid4().hex[:16]
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message", {})
    text = _strip_think(msg.get("content", ""))
    _tool_calls = msg.get("tool_calls")
    usage = resp.get("usage") or {}

    if not stream:
        # 非流式直接返回
        _stop = "tool_use" if _tool_calls else "end_turn"
        content_blocks = []
        if _tool_calls:
            for tc in _tool_calls:
                try: args = json.loads(tc["function"]["arguments"])
                except: args = {}
                content_blocks.append({"type": "tool_use", "id": tc.get("id", "call_x"), "name": tc["function"]["name"], "input": args})
        else:
            content_blocks.append({"type": "text", "text": text})
            
        return JSONResponse({
            "id": msg_id, "type": "message", "role": "assistant", "model": model,
            "content": content_blocks, "stop_reason": _stop, "stop_sequence": None,
            "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)}
        })

    # 流式返回（包装成 SSE）
    def _sse(ev, data):
        return "event: " + ev + "\ndata: " + json.dumps(data) + "\n\n"

    async def gen():
        yield _sse("message_start", {"type": "message_start", "message": {"id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": 0}}})
        yield _sse("ping", {"type": "ping"})
        
        _idx = 0
        _stop = "end_turn"
        
        if _tool_calls:
            _stop = "tool_use"
            for tc in _tool_calls:
                _id = tc.get("id", "call_" + uuid.uuid4().hex[:8])
                _name = tc["function"]["name"]
                _args = tc["function"]["arguments"]
                yield _sse("content_block_start", {"type": "content_block_start", "index": _idx, "content_block": {"type": "tool_use", "id": _id, "name": _name, "input": {}}})
                yield _sse("content_block_delta", {"type": "content_block_delta", "index": _idx, "delta": {"type": "input_json_delta", "partial_json": _args}})
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": _idx})
                _idx += 1
        elif text:
            yield _sse("content_block_start", {"type": "content_block_start", "index": _idx, "content_block": {"type": "text", "text": ""}})
            for i in range(0, len(text), 20):
                yield _sse("content_block_delta", {"type": "content_block_delta", "index": _idx, "delta": {"type": "text_delta", "text": text[i:i+20]}})
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": _idx})
            _idx += 1
            
        yield _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": _stop, "stop_sequence": None}, "usage": {"output_tokens": usage.get("completion_tokens", 0)}})
        yield _sse("message_stop", {"type": "message_stop"})

    return StreamingResponse(gen(), media_type="text/event-stream")

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    t0 = time.perf_counter()
    body = await request.json()
    auth = request.headers.get("authorization", "")
    # ★★★ 临时诊断：抓 Hermes 完整请求 ★★★
    # [PATCHED] Removed HERMES Dump
    # ★★★ 诊断结束 ★★★
    # ★ 统一模型身份：requested_model（对外）+ resolved_model（内部）
    requested_model = body.get("model", "?")
    # ★ v5.0: 立即捕获 MG_ 前缀（在 body["model"] 被任何逻辑改之前）
    _m19_clean_name, _early_has_mg = _strip_mg_prefix(requested_model)
    _is_m19_request = (_m19_clean_name == M19_PUBLIC_NAME)
    body["_has_mg_prefix"] = _early_has_mg
    print(f"   [mg-prefix] requested={requested_model} has_mg={_early_has_mg}", flush=True)
    resolved_model = _resolve_real_model(requested_model)
    if resolved_model != requested_model:
        print(f"   [chat-resolve] {requested_model} → {resolved_model}", flush=True)
    model = resolved_model   # v5.1 fix: 转发用真实模型名，不用归一化别名
    body["model"] = resolved_model   # ★ v5.1 fix: 同步写回 body，下游用的是 body["model"]
    _real = resolved_model    # 新增：内部判断用真实模型
    _thinking_model = _is_thinking_model(_real)
    stream = bool(body.get("stream"))
    # 池感知路由
    preferred_pool = request.headers.get("x-preferred-pool", "Pool-A")

    # ★ v8.3: 模型名兜底（排除嵌入/重排模型）
    # ★ 已删除 ModelRouter 双重路由：LiteLLM 9980 是单一真相源
    _log_ua(request, "/chat")
    # ★ 统一预处理
    _agent = request.headers.get("x-agent-type", "openwebui")
    body = _unified_preprocess(body, model, agent_type=_agent)
    # ===== Flint 差异化分流处理 =====
    if isinstance(model, str) and "flint" in model.lower():
        if body.get("tools"):
            # Agent 模式：给足预算
            _cur = body.get("max_tokens") or 2048
            _win = MODEL_CONTEXT_WINDOWS.get(model, 262144)
            _input_est = _count_msgs_tokens(body.get("messages") or []) + _count_tools_tokens(body.get("tools"))
            _safe_cap = max(8192, _win - _input_est - 4096)
            _target = min(65536, _safe_cap)
            if _cur < _target:
                body["max_tokens"] = _target
                print(f"   [flint-agent-max-tokens] {_cur} -> {_target} (win={_win} input_est={_input_est} safe_cap={_safe_cap})", flush=True)
        else:
            # 普通对话：只放宽字数，不强制改温度，交还给客户端
            _cur = body.get("max_tokens") or 2048
            if _cur < 8192:
                body["max_tokens"] = 8192
            print(f"   [flint-chat-optimize] 普通对话: max_tokens 调整为 {body['max_tokens']}", flush=True)

    print(f"\n📨 model={model} msgs={len(body.get('messages', []))} stream={stream} agent={_agent}", flush=True)
    gateway_requests_total.labels(model=model, stream=str(stream).lower(), status="started").inc()

    # pre-call 记忆注入（可选）
    # 判断是否内部任务（如 Open WebUI 的标题/标签生成）
    _is_internal = False
    for _m in reversed(body.get("messages", [])):
        if isinstance(_m, dict) and _m.get("role") == "user":
            _is_internal = is_internal_task(_m.get("content", ""))
            break
    # ComfyUI Desktop 等无记忆 profile 也跳过
    _agent_type = request.headers.get("x-agent-type", "openwebui")
    if _agent_type in ("comfyui_desktop",):
        _is_internal = True
    if _is_internal:
        print(f"   [skip] 内部任务跳过记忆注入", flush=True)
    if MEMORY_INJECT_ENABLED and _hooks and not _is_internal:
        try:
            # ★ 先从 Header 解析身份，再传给 hook
            ident = resolve_identity(request)
            body["_ident"] = ident
            for msg in reversed(body.get("messages", [])):
                if msg.get("role") == "user":
                    body["_original_user_content"] = msg.get("content", "")
                    break
            # ★ v5.0: MG/ 前缀 → 控制搜索开关
            _has_mg = body.get("_has_mg_prefix")
            if _has_mg is True:
                body["_force_search"] = True
                print(f"   [search] MG/ 前缀 → 强制开启搜索", flush=True)
            elif _has_mg is False:
                body["_force_search"] = False
                print(f"   [search] 无 MG/ 前缀 → 强制关闭搜索", flush=True)
            # ★ v7.7: sanitize（在 _force_search 设置之后）
            try:
                _msgs = body.get("messages") or []
                # (1) 移除错误的 system prompt
                _removed = []
                for _i in range(len(_msgs) - 1, -1, -1):
                    _m = _msgs[_i]
                    if _m.get("role") == "system":
                        _c = str(_m.get("content", ""))
                        for _pat in ["不要使用工具调用", "你是一个代码生成助手"]:
                            if _pat in _c:
                                _removed.append(_pat)
                                _msgs.pop(_i)
                                break
                if _removed:
                    print(f"   [sanitize] 移除错误 system prompt（{_removed}）", flush=True)
            except Exception as _se:
                print(f"   [sanitize] 失败: {type(_se).__name__}: {_se}", flush=True)
            if _is_hermes_request(body, request):
                body["_skip_search"] = True
                print(f"   [search] Hermes 请求，跳过 Gateway 搜索", flush=True)
            body = await _hooks.async_pre_call_hook({"token": "mock"}, {}, body, "completion")
            print(f"   ✅ pre-call 完成 user={ident['user_id']}", flush=True)
        except Exception as e:
            print(f"   ⚠️ pre-call 失败，透传原始请求: {e}", flush=True)
    else:
        # 即使不注入也记录原始消息，供写回使用
        for msg in reversed(body.get("messages", [])):
            if msg.get("role") == "user":
                body["_ident"] = resolve_identity(request)
                body["_original_user_content"] = msg.get("content", "")
                break

    # ★ 方案 B：按能力边界注入"简洁"提示
    _classify = body.get("_classify") or {}
    _cat = _classify.get("category")

    _style_hint = None
    if _cat == "howto":
        _style_hint = "请简洁回答，控制在 300 字以内，只给关键步骤。"
    elif _cat == "compare":
        _style_hint = "请简洁回答，控制在 250 字以内，用要点对比。"
    elif _cat == "unanswerable":
        _style_hint = "请简短拒答，50 字以内。"

    if _style_hint:
        _sys = {"role": "system", "content": f"【回答风格】{_style_hint}"}
        _msgs = body.get("messages") or []
        if _msgs and _msgs[0].get("role") == "system":
            _msgs[0]["content"] = _msgs[0]["content"] + "\n\n" + _sys["content"]
        else:
            _msgs = [_sys] + _msgs
        body["messages"] = _msgs
        print(f"   [style] {_cat} 注入简洁提示", flush=True)

    # ★ max_tokens 兜底（thinking 模型用 _thinking_model 判断）
    _orig_max = body.get("max_tokens", 2048)
    if not _thinking_model and _orig_max > 8192:
        body["max_tokens"] = 8192
        print(f"   [max_tokens] 兜底 _fb（原 {_orig_max}）", flush=True)
    elif _thinking_model:
        # ★ 动态计算：使用真实 tokenizer，不再使用“字符 ÷ 3”
        _win = MODEL_CONTEXT_WINDOWS.get(_real, 16384)

        _msg_tokens = _count_msgs_tokens(body.get("messages") or [])
        _tools_tokens = _count_tools_tokens(body.get("tools"))
        _prompt_tokens = _msg_tokens + _tools_tokens

        # 留 256 tokens 安全余量
        _margin = 256
        _available = max(256, _win - _prompt_tokens - _margin)

        # thinking 模型最多允许 4096，但绝不能超过真实剩余窗口
        _cap = min(4096, _available)

        if _orig_max is None:
            _final = _cap
        else:
            _final = min(int(_orig_max), _cap)

        body["max_tokens"] = max(256, _final)

        print(
            f"   [max_tokens] thinking {_real}: {_orig_max} → {body['max_tokens']} "
            f"(win={_win}, prompt={_prompt_tokens}, avail={_available})",
            flush=True
        )

    # ★ 参数调优（按模型 + 分类）
    try:
        from app.use_cases.param_tuner import get_tuner
        _cat_for_tune = (body.get("_classify") or {}).get("category")
        _tune = get_tuner().tune(body, model, _cat_for_tune)
        for _k, _v in _tune.items():
            body[_k] = _v
        if _tune:
            print(f"   [param] model={model} cat={_cat_for_tune} → {_tune}", flush=True)
    except Exception as _pe:
        print(f"   [param] 调优失败: {type(_pe).__name__}: {_pe}", flush=True)

    # ★ 上下文窗口检查（防止超模型物理窗口）
    # ★ 分层摘要（异步，缓存优先）
    try:
        _ident = body.get("_ident") or {"user_id": "default_user", "session_id": "default"}
        body = await _compress_history_async(body, _ident)
    except Exception as _ce:
        print(f"   [compress-history] 跳过: {_ce}", flush=True)
    

    # ★ thinking 控制（统一用 _thinking_model 判断）
    _user_think = body.pop("_enable_thinking", None)
    if _user_think is True or _thinking_model:
        body["chat_template_kwargs"] = {"enable_thinking": True}
        _who = "thinking 模型强制开启" if _thinking_model else "用户显式开启"
        print(f"   [thinking] model={_real} enabled=True ({_who})", flush=True)
    else:
        body["chat_template_kwargs"] = {"enable_thinking": False}
        print(f"   [thinking] model={_real} enabled=False", flush=True)

    # ★ thinking 模型剥离 response_format（避免 json_schema + thinking 冲突导致空响应）
    if _thinking_model and "response_format" in body:
        _rf = body.pop("response_format")
        print(f"   [strip] thinking 模型 {_real} 剥离 response_format（原: {str(_rf)[:80]}）", flush=True)

    # ---- 规范化 messages（system 必须在前）----
    if isinstance(body.get("messages"), list):
        body["messages"] = _normalize_messages(body["messages"])
        _roles = [m.get("role") for m in body["messages"] if isinstance(m, dict)]
        print(f"   [normalize] roles = {_roles}", flush=True)
    # v6: 最终检查放在 Hook、压缩、风格注入和消息规范化之后
    body = _enforce_context_window(body, _real)
    if body.get("_context_error"):
        return JSONResponse(
            {
                "error": {
                    "message": body["_context_error"],
                    "type": "context_window_exceeded"
                }
            },
            status_code=400
        )
    # M19 独立直连；其他模型继续走 LiteLLM
    _request_upstream = M19_UPSTREAM if _is_m19_request else UPSTREAM

    if _is_m19_request:
        # 移除 Gateway 内部元数据及 LiteLLM 专属参数
        _outbound_body = {
            k: v for k, v in body.items()
            if not k.startswith("_") and k != "chat_template_kwargs"
        }
        _outbound_body["model"] = M19_MODEL_ID
        print(
            f"   [M19 direct] {requested_model} -> "
            f"{_request_upstream} model={M19_MODEL_ID}",
            flush=True
        )
    else:
        _outbound_body = body

    upstream_headers = {"Content-Type": "application/json"}
    if auth and not _is_m19_request:
        upstream_headers["Authorization"] = auth

    if stream:
        gateway_requests_total.labels(model=model, stream="true", status="started").inc()
        # ★ 流式分流：有 tools → buffer（防 XML 破碎）；无 tools → 真流式
        _stream_fn = _proxy_stream_buffered if body.get("tools") else _proxy_stream_realtime
        return StreamingResponse(
            _stream_fn(
                _outbound_body, upstream_headers, t0, _request_upstream
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no",
                     "X-Gateway": "dxos-transparent"})
    else:
        try:
            async with httpx.AsyncClient(timeout=300.0) as c:
                r = await c.post(
                    f"{_request_upstream.rstrip('/')}/v1/chat/completions",
                    headers=upstream_headers, json=_outbound_body
                )
            resp_json = r.json()
            # ★ 统一后处理：剥 think + 解析 <tool_call> → 标准 tool_calls
            resp_json = _normalize_chat_response(resp_json)
            if _is_m19_request and isinstance(resp_json, dict):
                resp_json["model"] = requested_model
            # ★ 引用链接化（[1] → [1](url)）
            _url_map = body.get("_citation_urls") or {}
            if _url_map:
                try:
                    _c = (resp_json.get("choices") or [{}])[0].get("message", {}).get("content", "")
                    if _c:
                        _nc = _linkify_citations(_c, _url_map)
                        _meta = body.get("_citation_meta") or {}
                        if _meta:
                            _nc = _append_references(_nc, _meta)
                            print(f"   [cite] 非流式追加参考列表 {len(_meta)} 条", flush=True)
                        if _nc != _c:
                            resp_json["choices"][0]["message"]["content"] = _nc
                            print(f"   [cite] 非流式链接化 {len(_url_map)} 个引用", flush=True)
                except Exception as _e:
                    print(f"   [cite] 非流式链接化失败: {_e}", flush=True)
            # ---- metrics: 非流式完成 ----
            gateway_requests_total.labels(model=model, stream="false", status="200").inc()
            gateway_duration_seconds.labels(model=model, stream="false").observe(time.perf_counter() - t0)
            print(f"   ✅ 非流式完成 ({time.perf_counter()-t0:.2f}s)", flush=True)
            # ---- metrics: token 计数 ----
            try:
                _u = resp_json.get("usage") or {}
                _pt = int(_u.get("prompt_tokens") or 0)
                _ct = int(_u.get("completion_tokens") or 0)
                if _pt:
                    gateway_tokens_total.labels(model=model, type="prompt").inc(_pt)
                if _ct:
                    gateway_tokens_total.labels(model=model, type="completion").inc(_ct)
            except Exception:
                pass

            # ---- metrics: 成本追踪 ----
            try:
                from app.use_cases.cost_tracker import estimate_cost
                _cost = estimate_cost(model, _pt, _ct)
                if _cost > 0:
                    gateway_cost_yuan.labels(model=model).inc(_cost)
            except Exception:
                pass
        except Exception as e:
            print(f"   ❌ 转发失败: {type(e).__name__}: {e}", flush=True)
            raise HTTPException(status_code=502, detail=f"上游不可达: {e}")
        if MEMORY_WRITEBACK_ENABLED and _hooks and body.get("_ident"):
            try:
                content = (resp_json.get("choices") or [{}])[0].get("message", {}).get("content", "")
                await _hooks.async_post_call_success_hook(
                    body, {"token": "mock"},
                    {"choices": [{"message": {"content": content}}]})
            except Exception as e:
                print(f"   ⚠️ post-call 失败: {e}", flush=True)
        return JSONResponse(resp_json, status_code=r.status_code,
                            headers={"X-Gateway": "dxos-transparent"})

async def _proxy_stream(body: dict, headers: dict, t0: float):
    full_content = []
    _url_map = body.get("_citation_urls") or {}
    _linker = _CiteLinker(_url_map) if _url_map else None
    try:
        async with httpx.AsyncClient(timeout=300.0) as c:
            async with c.stream("POST", f"{UPSTREAM}/v1/chat/completions",
                                headers=headers, json=body) as r:
                print(f"   ⏳ 上游 {r.status_code}，开始流式转发", flush=True)
                chunks = 0
                async for line in r.aiter_lines():
                    if line:
                        chunks += 1
                        # ---- metrics: 流式 token ----
                        if line.startswith("data: ") and '"usage"' in line:
                            try:
                                _p = json.loads(line[6:])
                                _u = _p.get("usage") or {}
                                _pt = int(_u.get("prompt_tokens") or 0)
                                _ct = int(_u.get("completion_tokens") or 0)
                                _m = body.get("model", "?")
                                if _pt:
                                    gateway_tokens_total.labels(model=_m, type="prompt").inc(_pt)
                                if _ct:
                                    gateway_tokens_total.labels(model=_m, type="completion").inc(_ct)
                            except Exception:
                                pass
                        # 提取 content 用于写回
                        if line.startswith("data: ") and "content" in line:
                            try:
                                payload = json.loads(line[6:])
                                delta = (payload.get("choices") or [{}])[0].get("delta", {})
                                piece = delta.get("content")
                                if piece:
                                    full_content.append(piece)
                                    # ★ 链接化：replace content
                                    if _linker:
                                        _new_piece = _linker.feed(piece)
                                        if _new_piece != piece:
                                            delta["content"] = _new_piece
                                            payload["choices"][0]["delta"] = delta
                                            line = "data: " + json.dumps(payload, ensure_ascii=False)
                            except Exception:
                                pass
                        yield line + "\n\n"
                # ★ flush linker 尾部
                if _linker:
                    _tail = _linker.flush()
                    if _tail:
                        _tp = {"choices": [{"delta": {"content": _tail}}]}
                        yield "data: " + json.dumps(_tp, ensure_ascii=False) + "\n\n"
                # ★ 流式：追加参考列表
                _meta = body.get("_citation_meta") or {}
                if _meta:
                    _refs = _format_references(_meta)
                    if _refs:
                        _rp = {"choices": [{"delta": {"content": _refs}}]}
                        yield "data: " + json.dumps(_rp, ensure_ascii=False) + "\n\n"
                        print(f"   [cite] 流式追加参考列表 {len(_meta)} 条", flush=True)
                print(f"   ✅ 流式完成 {chunks} chunks ({time.perf_counter()-t0:.2f}s)", flush=True)
                _m = body.get("model", "?")
                gateway_requests_total.labels(model=_m, stream="true", status="200").inc()
                gateway_duration_seconds.labels(model=_m, stream="true").observe(time.perf_counter() - t0)

        # ★ 流式完成后触发写回
        if MEMORY_WRITEBACK_ENABLED and _hooks and body.get("_ident"):
            try:
                content = "".join(full_content)
                if content.strip():
                    await _hooks.async_post_call_success_hook(
                        body, {"token": "mock"},
                        {"choices": [{"message": {"content": content}}]})
                    print(f"   ✅ 流式 post-call 触发 user={body['_ident'].get('user_id')} len={len(content)}", flush=True)
            except Exception as e:
                print(f"   ⚠️ 流式 post-call 失败: {e}", flush=True)

    except GeneratorExit:
        # 客户端提前断连
        gateway_requests_total.labels(
            model=body.get("model", "?"), stream="true",
            status="client_disconnect").inc()
        print(f"   ⚠️ 流式客户端断连（GeneratorExit）", flush=True)
        raise
    except Exception as e:
        print(f"   ❌ 流式失败: {type(e).__name__}: {e}", flush=True)
        gateway_requests_total.labels(model=body.get("model", "?"), stream="true", status="error").inc()
        yield f"data: {json.dumps({'error': {'message': str(e)[:200]}})}\n\n"
        yield "data: [DONE]\n\n"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=GATEWAY_PORT, log_level="info")
