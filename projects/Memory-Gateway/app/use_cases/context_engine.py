"""ContextEngine v2：tiktoken + 历史摘要 + 智能截断 + 前缀缓存标记"""
import time
import hashlib

from contracts.context import LAYOUT, DEGRADE_ORDER
from contracts.errors import MemoryTooLong
from app.metrics import context_degraded_total


class ContextEngine:
    """上下文预算器：按槽位分配 token，稳定前缀字节不变，易变段放尾部。"""

    TOTAL_BUDGET = 24576
    OUTPUT_RESERVE = 4096
    RECENT_N = 8            # 最近 N 条作为易变消息
    SUMMARY_KEEP = 10       # 老消息取最后 10 条做摘要
    SUMMARY_MAX_CHARS = 800

    def __init__(self, tokenizer=None):
        self.tokenizer = tokenizer if tokenizer is not None else self._make_tiktoken()
        self._degraded = 0
        self._last_summary = ""

    def _make_tiktoken(self):
        try:
            import tiktoken
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None

    def count(self, text):
        if not text:
            return 0
        s = str(text)
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(s))
            except Exception:
                pass
        return len(s)

    # ---------- 历史处理 ----------
    def _split_history(self, messages):
        if not messages:
            return [], []
        n = self.RECENT_N
        return messages[-n:], messages[:-n]

    def _summarize_history(self, old_messages):
        """老消息简化摘要：拼接 + 截断（不额外调 LLM，避免延迟）"""
        if not old_messages:
            return ""
        take = old_messages[-self.SUMMARY_KEEP:]
        parts = []
        for m in take:
            if isinstance(m, dict):
                c = str(m.get("content") or "")[:200]
            else:
                c = str(m)[:200]
            if c:
                parts.append(c)
        text = " | ".join(parts)
        return text[:self.SUMMARY_MAX_CHARS]
    async def _llm_summarize(self, old_messages, timeout: float = 8.0):
        """用 yy35b_q6 生成历史摘要（异步）；失败降级到拼接"""
        if not old_messages:
            return ""
        text = "\n".join(
            f"[{m.get('role') if isinstance(m, dict) else '?'}] "
            f"{str(m.get('content',''))[:100] if isinstance(m, dict) else str(m)[:100]}"
            for m in old_messages[-20:]
        )
        if not text.strip():
            return ""
        try:
            import httpx, os
            base = os.environ.get("UPSTREAM_BASE", "http://192.168.10.132:9980")
            key = os.environ.get("PILOT_KEY_M00", "").strip()
            if not key:
                # 兜底：从 .env.g0 直接读
                try:
                    for _l in open("/ai/Memory-Gateway/.env.g0"):
                        if _l.startswith("PILOT_KEY_M00="):
                            key = _l.split("=", 1)[1].strip()
                            break
                except Exception:
                    pass
            if not key:
                print(f"   [summary] 缺少 PILOT_KEY_M00，跳过", flush=True)
                return self._summarize_history(old_messages)
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(
                    f"{base}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": "yy35b_q6",
                        "messages": [
                            {"role": "system",
                             "content": "你是摘要助手。用 150 字以内中文总结以下对话的关键事实、用户偏好和决策。"},
                            {"role": "user", "content": text},
                        ],
                        "max_tokens": 300,
                        "temperature": 0.1,
                    })
                if r.status_code == 200:
                    body = r.json()
                    out = body["choices"][0]["message"]["content"][:800].strip()
                    if out:
                        print(f"   [summary] LLM 摘要成功 ({len(out)} 字)", flush=True)
                        return out
        except Exception as e:
            print(f"   [summary] LLM 摘要失败，降级: {type(e).__name__}: {e}", flush=True)
        return self._summarize_history(old_messages)


    # ---------- 组装 ----------
    def build(self, ident, messages, plan, memory_hits, rag_hits, web_hits,
              precomputed_summary="", stable_context=""):
        self._degraded = 0
        input_budget = self.TOTAL_BUDGET - self.OUTPUT_RESERVE

        recent, old = self._split_history(messages or [])
        summary_from_old = precomputed_summary or self._summarize_history(old)
        self._last_summary = summary_from_old

        # ★ 稳定前缀：把用户级稳定内容前置，最大化 RadixAttention 缓存命中
        stable_slots = [
            ("system_policy", "你是一个 AI 助手，遵循用户指令。当参考资料中有 [N] 编号时，回答中引用的事实必须标注对应的 [N]。"),
            ("tools_spec", ""),
        ]
        # 追加用户级稳定内容（profile + 稳定记忆 + 文档标题）
        if stable_context:
            stable_slots.append(("user_context", stable_context))

        # ★ 易变槽位：summary_history 放这里（不破坏前缀缓存）
        volatile_slots = [
            ("summary_history", summary_from_old or self._get_summary(ident)),
            ("recent_messages", recent),
            ("retrieved_memory", memory_hits or []),
            ("retrieved_rag", rag_hits or []),
            ("web_results", web_hits or []),
        ]

        used = 0
        sections = []
        for name, content in stable_slots:
            if not content:
                continue
            tok = self.count(content)
            if used + tok > input_budget * 0.6:
                self._degraded += 1
                context_degraded_total.labels(reason=f"skip_{name}").inc()
                break
            sections.append((name, content))
            used += tok

        remaining = input_budget - used
        for name, content in volatile_slots:
            if not content:
                continue
            tok = self.count(content)
            if tok > remaining:
                content = self._truncate(content, remaining)
                self._degraded += 1
                context_degraded_total.labels(reason=f"truncate_{name}").inc()
            if content:
                sections.append((name, content))
                remaining -= self.count(content)
            if remaining < 100:
                break

        prefix_text = "".join(str(c) for _, c in sections[:4])
        prefix_hash = hashlib.sha256(prefix_text.encode()).hexdigest()[:16]

        return {
            "sections": sections,
            "prefix_hash": prefix_hash,
            "cache_breakpoints": [
                i for i, (n, _) in enumerate(sections)
                if n in ("system_policy", "tools_spec", "user_context")
            ],
            "degraded": self._degraded > 0,
            "summary": summary_from_old,
        }

    def _get_profile(self, ident):
        return ""

    def _get_summary(self, ident):
        return ""

    # ---------- 截断 ----------
    def _truncate(self, content, budget):
        if isinstance(content, list):
            if not content:
                return content
            per = max(1, budget // max(1, len(content)))
            out = []
            for m in content:
                if isinstance(m, dict) and "content" in m:
                    c = m.get("content") or ""
                    if isinstance(c, str) and len(c) > per:
                        m2 = dict(m)
                        m2["content"] = c[:per] + "…[截]"
                        out.append(m2)
                    else:
                        out.append(m)
                elif isinstance(m, str) and len(m) > per:
                    out.append(m[:per] + "…[截]")
                else:
                    out.append(m)
            return out
        if isinstance(content, str):
            if len(content) > budget:
                return content[:budget] + "…[截]"
            return content
        return content
