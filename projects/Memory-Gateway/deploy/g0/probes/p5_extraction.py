import json, httpx
from .base import ProbeResult, secret, discovered
import sys, os
sys.path.insert(0, os.getcwd())
from contracts.t0_rules import classify_tier

SCHEMA = {"name": "facts", "schema": {
    "type": "object", "additionalProperties": False, "required": ["facts"],
    "properties": {"facts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["op", "entity_key", "memory_class", "content", "confidence"],
        "properties": {
            "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE", "NOOP"]},
            "entity_key": {"type": "string"},
            "memory_class": {"type": "string",
                             "enum": ["fact", "preference", "decision", "procedure", "episode"]},
            "content": {"type": "string"},
            "confidence": {"type": "number"}}}}}}}

# 受控词表：entity_key 必须命中，否则判 FAIL（取代机制依赖它稳定可枚举）
PREFIX = ("user.pref.", "user.id.", "user.role.", "proj.", "tool.", "code.")

SAMPLES = [
    ("我们项目统一用Qdrant做向量库，不要用Milvus", "ADD"),
    ("我以前喜欢用Milvus，但从今天开始改用Qdrant", "UPDATE"),
    ("别再返回500了，改成503带retry_after", "UPDATE"),
    ("记住，我叫老张，负责网关", "ADD"),
    ("帮我查一下明天天气", "NONE"),
    ("编译报错E1042，是网关超时，把max_context调大", "ADD"),
    ("忘掉我之前说喜欢pgvector那句话", "DELETE"),
    ("resolve_candidates是先出候选集不选最终模型", "ADD"),
]

HEAD = "从对话中抽取需要长期记忆的原子事实。只输出紧凑JSON，不要换行，不要解释。"
HEAD += "entity_key 必须以下列前缀之一开头：" + ",".join(PREFIX) + "。若无可抽取内容输出空数组。"
HEAD += "<conversation>"
TAIL = "</conversation>"


def parse_content(msg):
    c = (msg.get("content") or "").strip()
    if not c:
        c = (msg.get("reasoning_content") or "").strip()
    return c


def extract_json(txt):
    try:
        return json.loads(txt)
    except Exception:
        s, e = txt.find("{"), txt.rfind("}")
        if s >= 0 and e > s:
            return json.loads(txt[s:e + 1])
        raise


async def run(cfg):
    r = ProbeResult("P5", "LLM抽取")
    d = discovered()
    model = d.get("judge_model")
    if not model:
        r.passed, r.reason = None, "未发现可用 chat 模型"
        return r
    try:
        key = secret("KEY_qwen3_32b")   # 从 keys.conf 读取 [2]
    except Exception as e:
        r.passed, r.reason = None, str(e)[:80]
        return r
    hdr = {"Authorization": "Bearer " + key}
    stat = {"截断": 0, "空返回": 0, "schema失败": 0, "词表不合规": 0,
            "op正确": 0, "通过": 0}
    details = []
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            for text, expect in SAMPLES:
                payload = {"model": model, "temperature": 0.0, "max_tokens": 1600, "thinking": {"type": "disabled"},
                           "response_format": {"type": "json_schema", "json_schema": SCHEMA},
                           "messages": [{"role": "user", "content": HEAD + text + TAIL}]}
                try:
                    resp = await c.post(cfg["base"]["gateway_url"] + "/v1/chat/completions",
                                        headers=hdr, json=payload)
                    if resp.status_code != 200:
                        stat["schema失败"] += 1
                        details.append((text[:14], "HTTP" + str(resp.status_code)))
                        continue
                    ch = resp.json()["choices"][0]
                    msg = ch.get("message", {})
                    if ch.get("finish_reason") == "length":
                        stat["截断"] += 1
                        details.append((text[:14], "截断"))
                        continue
                    content = parse_content(msg)
                    if not content:
                        stat["空返回"] += 1
                        details.append((text[:14], "空返回"))
                        continue
                    facts = extract_json(content).get("facts")
                    assert isinstance(facts, list)
                    ops = [f.get("op") for f in facts]
                    rule_op = "DELETE" if classify_tier(text).rule == "forget" \
                        else ("UPDATE" if classify_tier(text).rule == "negation_flip" else "ADD")
                    if classify_tier(text).tier != "A":
                        rule_op = "NONE" if not ops else ops[0]
                    if rule_op == expect:
                        stat["规则op正确"] = stat.get("规则op正确", 0) + 1
                    bad_key = [f.get("entity_key") for f in facts
                               if not str(f.get("entity_key", "")).startswith(PREFIX)]
                    if bad_key:
                        stat["词表不合规"] += 1
                        details.append((text[:14], "key非法:" + str(bad_key[0])[:22]))
                    else:
                        got = "NONE" if not ops else ops[0]
                        if got == expect:
                            stat["op正确"] += 1
                        if not bad_key:
                            stat["通过"] += 1
                        details.append((text[:14], (got or "NONE") + " 期望" + expect))
                except Exception as e:
                    stat["schema失败"] += 1
                    details.append((text[:14], str(e)[:40]))
    except Exception as e:
        r.passed, r.reason = False, type(e).__name__ + ": " + str(e)[:80]
        return r
    n = len(SAMPLES)
    r.metrics = dict(stat)
    r.metrics["模型"] = model
    rp = stat.get("规则op正确", 0)
    r.passed = (stat["通过"] >= 7 and stat["截断"] == 0
                and rp >= int(len(SAMPLES) * 0.85))
    r.reason = ("抽取通过 {}/{}，规则op {}/{}，截断{}，模型op {}/{}"
                .format(stat["通过"], n, rp, n, stat["截断"],
                        stat["op正确"], n))
    if not r.passed:
        r.hint = "截断→再提max_tokens；空返回→该模型不适合判定；词表→加词表重试"
    for a, b in details:
        print("        [{}] {}".format(b, a))
    return r
