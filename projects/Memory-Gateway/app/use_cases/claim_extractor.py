"""Claim Extractor: 用 LLM 从 Evidence 中抽取事实声明

设计原则：
- 失败降级：LLM 超时/异常 → 返回空列表（上层回退到 raw evidence）
- 输出结构化：JSON 数组
- 引用绑定：每个 claim 关联 evidence_ids
"""
import sys
import os
import json
import re
import time
from typing import List, Dict

if "/ai/Memory-Gateway" not in sys.path:
    sys.path.insert(0, "/ai/Memory-Gateway")

from contracts.research import Claim, Evidence, make_id


CLAIM_PROMPT = """你是一个信息抽取助手。请从以下搜索结果中抽取与问题相关的**事实性声明**。

问题：{query}

搜索结果：
{evidences_text}

要求：
1. 每个声明必须是**单一事实**（不要合并多个事实）
2. 每个声明必须引用至少一个证据编号 [N]
3. 优先抽取包含**具体数值/日期/名称**的声明
4. 最多抽取 8 条声明
5. 只输出 JSON 数组，不要其他文字

输出格式（严格 JSON）：
[
  {{"text": "声明内容", "evidence_indexes": [1, 3], "confidence": 0.9, "claim_type": "number"}},
  {{"text": "另一个声明", "evidence_indexes": [2], "confidence": 0.8, "claim_type": "fact"}}
]

claim_type 可选值：fact / number / date / categorical / opinion
"""


class ClaimExtractor:
    def __init__(self, base_url: str = None, api_key: str = None,
                 model: str = "yy35b_q6", timeout: float = 20.0):
        self.base_url = (base_url
                         or os.environ.get("UPSTREAM_BASE",
                                           "http://192.168.10.132:9980")).rstrip("/")
        self.api_key = api_key or self._read_key()
        self.model = model
        self.timeout = timeout

    def _read_key(self) -> str:
        k = os.environ.get("PILOT_KEY_M00", "").strip()
        if k:
            return k
        try:
            for line in open("/ai/Memory-Gateway/.env.g0"):
                if line.startswith("PILOT_KEY_M00="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
        return ""

    async def extract(self, query: str,
                      evidences: List[Evidence]) -> List[Claim]:
        """从 evidences 抽取 claims；失败返回空列表"""
        if not evidences:
            return []

        # 构造证据文本
        ev_text = "\n".join(
            f"[{i+1}] {ev.quote[:200]}"
            for i, ev in enumerate(evidences[:4])
        )
        prompt = CLAIM_PROMPT.format(query=query, evidences_text=ev_text)

        # 调 LLM
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "你是严谨的信息抽取助手，只输出 JSON。"},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 2500,
                        "temperature": 0.1,
                        # ★ 禁用 thinking（速度提升 10 倍）
                        "chat_template_kwargs": {"enable_thinking": False},
                    })
            if r.status_code != 200:
                print(f"   [claim] LLM HTTP {r.status_code}", flush=True)
                return []
            content = r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"   [claim] LLM 异常: {type(e).__name__}: {e}", flush=True)
            return []

        # ★ 剥掉 <think> 标签（用 split，不用正则）
        if "</think>" in content:
            content = content.split("</think>", 1)[1].strip()

        # 剥掉 ```json ... ``` 包裹
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```\s*$", "", content)
            content = content.strip()

        # 第一次尝试：直接解析
        items = None
        try:
            items = json.loads(content)
        except Exception:
            pass

        # 第二次尝试：找最后一个 [...] 块（rfind，不用正则）
        if items is None:
            left = content.rfind("[")
            right = content.rfind("]")
            if left >= 0 and right > left:
                try:
                    items = json.loads(content[left:right+1])
                except Exception:
                    pass

        # 第三次尝试：找第一个 [...]（兼容旧格式）
        if items is None:
            left = content.find("[")
            right = content.find("]", left)
            if left >= 0 and right > left:
                try:
                    items = json.loads(content[left:right+1])
                except Exception:
                    pass

        # 第四次尝试：补齐截断的 JSON
        if items is None:
            left = content.find("[")
            if left >= 0:
                # 补 ] 和 }
                truncated = content[left:]
                # 如果最后没 ]，补上
                if not truncated.rstrip().endswith("]"):
                    truncated = truncated.rstrip()
                    # 去掉末尾不完整的对象（保留到最后一个完整的 }）
                    if truncated.endswith(","):
                        truncated = truncated[:-1]
                    elif "}" in truncated:
                        last_brace = truncated.rfind("}")
                        truncated = truncated[:last_brace+1]
                    truncated += "]"
                try:
                    items = json.loads(truncated)
                    if items:
                        print(f"   [claim] JSON 截断已修补，解析 {len(items)} 条", flush=True)
                except Exception:
                    pass

        if items is None:
            print(f"   [claim] JSON 解析失败: {content[:150]}", flush=True)
            return []

        if not isinstance(items, list):
            return []

        # 构造 Claim 对象
        claims = []
        for i, item in enumerate(items[:8]):
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            if not text:
                continue
            idxs = item.get("evidence_indexes") or []
            eids = []
            for ix in idxs:
                try:
                    j = int(ix) - 1
                    if 0 <= j < len(evidences):
                        eids.append(evidences[j].evidence_id)
                except Exception:
                    continue
            if not eids:
                continue
            claims.append(Claim(
                claim_id=make_id("clm", f"{query}:{text[:50]}:{i}"),
                text=text[:300],
                evidence_ids=eids,
                confidence=float(item.get("confidence") or 0.8),
                claim_type=item.get("claim_type") or "fact",
            ))
        return claims


_extractor = None


def get_claim_extractor() -> ClaimExtractor:
    global _extractor
    if _extractor is None:
        _extractor = ClaimExtractor()
    return _extractor


if __name__ == "__main__":
    import asyncio
    from adapters.discovery import get_discovery
    from app.use_cases.evidence_engine import get_evidence_engine
    from contracts.research import QueryPlan

    async def main():
        plan = QueryPlan(plan_id="test", need_web_search=True,
                         reason="test", queries=["重庆今天气温"],
                         max_candidates=5)
        result = await get_discovery().discover(plan)
        hits = result.get("raw", [])
        sources = result.get("sources", [])

        bundle = await get_evidence_engine().build("重庆今天气温", hits, sources)
        print(f"Evidence: {len(bundle.evidences)}")

        t0 = time.time()
        claims = await get_claim_extractor().extract("重庆今天气温", bundle.evidences)
        elapsed = time.time() - t0
        print(f"\n抽取 {len(claims)} 条 claims ({elapsed:.2f}s)")
        for c in claims:
            print(f"  · [{c.claim_type}] {c.text[:80]}")
            print(f"    evidence_ids={c.evidence_ids} conf={c.confidence:.2f}")

    asyncio.run(main())
