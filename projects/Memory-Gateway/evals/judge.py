"""LLM 判定：回答是否正确"""
import os
import json

def get_key():
    try:
        with open("/ai/ai_dxos/secrets/keys.conf") as f:
            for line in f:
                if line.startswith("KEY_qwen3_32b="):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return os.environ.get("PILOT_KEY_M00")

JUDGE_PROMPT = """你是评分员。判断【模型回答】是否与【标准答案】语义一致。

【问题】{question}
【标准答案】{gold}
【模型回答】{answer}

规则：
1. 事实问题：模型回答包含标准答案的核心信息即为正确
2. 弃答问题（gold="无法确定"）：模型回答表示"不知道/无法确定/信息不足"即为正确
3. 只输出 JSON：{{"correct": true/false, "reason": "简短理由"}}
"""

async def judge_answer(question, gold, answer, model="38FN_Q4"):
    import litellm
    litellm.api_base = "http://192.168.10.132:9980"
    api_key = get_key()
    
    prompt = JUDGE_PROMPT.format(question=question, gold=gold, answer=answer or "(空)")
    try:
        resp = await litellm.acompletion(
            model=f"openai/{model}",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
            api_key=api_key,
            timeout=300,
        )
        raw = resp.choices[0].message.content or ""
        # 提取 JSON
        try:
            data = json.loads(raw)
            return bool(data.get("correct", False)), data.get("reason", "")[:60]
        except Exception:
            # 兜底：包含 true 就算
            return "true" in raw.lower(), raw[:60]
    except Exception as e:
        return False, f"judge_error: {type(e).__name__}"
