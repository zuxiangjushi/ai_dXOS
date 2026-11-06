"""
v5.2 窗口预算服务：统一管理上下文、tools、thinking、输出 token 分配
Jeff Dean 原则：单一职责、可复现、可观测、可测试
"""
import os
import json
from typing import List, Dict, Optional, Tuple

DEFAULT_MAX_TOKENS      = int(os.getenv("DEFAULT_MAX_TOKENS", "4096"))
THINKING_MIN_TOKENS     = int(os.getenv("THINKING_MIN_TOKENS", "8192"))
THINKING_MAX_TOKENS     = int(os.getenv("THINKING_MAX_TOKENS", "32768"))
NON_THINKING_MAX_TOKENS = int(os.getenv("NON_THINKING_MAX_TOKENS", "8192"))
MAX_CONTEXT_TOKENS = 0  # 已退役，禁止旧路径默认放大上下文
MODEL_CONTEXT_WINDOWS = {}  # 已退役，唯一窗口表由 Gateway 管理
TOOLS_MAX_RATIO         = float(os.getenv("TOOLS_MAX_RATIO", "0.33"))
CONTEXT_BUFFER          = int(os.getenv("CONTEXT_BUFFER", "256"))
HISTORY_KEEP_RECENT     = int(os.getenv("HISTORY_KEEP_RECENT", "20"))


def is_thinking_model(model: str) -> bool:
    if not model:
        return False
    name = model.lower()
    return any(k in name for k in ("qwythos", "glimmer", "qwen3.5", "thinking"))


def _count_tokens(messages: List[Dict], tools: Optional[List] = None) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        total = 0
        for m in messages:
            c = m.get("content")
            if isinstance(c, str):
                total += len(enc.encode(c))
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += len(enc.encode(part.get("text", "")))
            total += 4
        if tools:
            total += len(enc.encode(json.dumps(tools, ensure_ascii=False)))
        return total
    except Exception:
        total = 0
        for m in messages:
            c = m.get("content", "")
            if isinstance(c, str):
                total += len(c) // 3 + 4
        if tools:
            total += len(json.dumps(tools, ensure_ascii=False)) // 3
        return total



def _trim_messages(messages, target_tokens):
    # 旧逐消息裁剪不具备工具事务保护，禁止继续使用。
    return messages



def compute_budget(*args, **kwargs):
    raise RuntimeError(
        "compute_budget 已退役：请使用 fastapi_gateway 的最终上下文预算裁决。"
    )


def ensure_non_empty_content(resp_json: dict) -> dict:
    """thinking 模型 content 为空时，用 reasoning 兜底，永不返回空"""
    if not isinstance(resp_json, dict):
        return resp_json
    for choice in resp_json.get("choices", []) or []:
        msg = choice.get("message") or {}
        content = (msg.get("content") or "").strip()
        reasoning = (msg.get("reasoning_content") or "").strip()
        if not content and reasoning:
            msg["content"] = f"[thinking]\n{reasoning[-1000:]}"
            choice["_fallback_reason"] = "empty_content_from_thinking"
        elif not content and not reasoning:
            msg["content"] = "[ERROR] 模型返回空内容，请检查 token 预算"
            choice["_fallback_reason"] = "empty_all"
        choice["message"] = msg
    return resp_json


def dynamic_max_tokens(prompt_tokens: int, messages: List[Dict],
                       is_thinking: bool, user_requested: Optional[int]) -> int:
    """
    v5.3 动态输出预算：根据 prompt 特征智能分配。
    原则：输入大 → 输出大（需要深度分析）；输入小 → 输出小（快速答）。
    上限：THINKING_MAX_TOKENS（默认 16384）。
    """
    # 提取最后一条 user 消息，看关键词
    user_text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                user_text = c
            elif isinstance(c, list):
                user_text = " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
            break

    lower = user_text.lower()
    THINK_MAX = int(os.getenv("THINKING_MAX_TOKENS", "16384"))

    # 关键词升级
    long_keywords = ("完整实现", "完整代码", "长文档", "详细分析", "写一篇", "写论文",
                     "2000字", "3000字", "5000字", "生成代码", "完整教程", "详细设计",
                     "full implementation", "detailed analysis")
    needs_long = any(k in user_text or k in lower for k in long_keywords)

    # 按输入规模 + 关键词组合
    if needs_long:
        return min(THINK_MAX, 16384)
    if prompt_tokens > 30000:
        return min(THINK_MAX, 8192)
    if prompt_tokens > 10000:
        return min(THINK_MAX, 8192)
    if prompt_tokens > 1000:
        return min(THINK_MAX, 4096)
    return min(THINK_MAX, 2048)
