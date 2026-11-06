"""M4 Mem0 对照版：只重写 retrieval 档位走 Mem0 /search

差异（vs run_full_200.py）：
- retrieval_recall 调 Mem0 API，不直查 Qdrant
- 其他逻辑完全一致（保证对照公平）
"""
import asyncio
import json
import sys
import time
import hashlib
import argparse
from datetime import datetime
import os
import httpx

sys.path.insert(0, "/ai/Memory-Gateway")
from evals.judge import judge_answer
from evals.arm_runner import call_model

PERSONAS_FILE = "evals/datasets/personas_20.json"
QUESTIONS_FILE = "evals/datasets/questions_200.jsonl"
MAX_TOKENS = 500

MEM0_URL = os.environ.get("MEM0_URL", "http://127.0.0.1:8888")
MEM0_KEY = os.environ.get("MEM0_ADMIN_KEY", "")


def user_id_for(persona):
    return "eval_" + hashlib.md5(persona.encode()).hexdigest()[:8]


async def mem0_recall(persona, question, top_k=5):
    """调用 Mem0 /search"""
    uid = user_id_for(persona)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{MEM0_URL}/search",
            headers={"X-API-Key": MEM0_KEY},
            json={"query": question, "user_id": uid, "limit": top_k})
        if r.status_code != 200:
            print(f"  ⚠️ Mem0 HTTP {r.status_code}: {r.text[:100]}", flush=True)
            return []
        results = r.json().get("results", [])
        return [{"content": x.get("memory", ""), "score": x.get("score", 0)} for x in results]


async def run_one(q_obj, sessions, arm):
    question = q_obj["question"]
    if arm == "none":
        messages = [{"role": "user", "content": question}]
        n_hits = 0
    elif arm == "memory_only":
        history = "\n".join(f"[{s['ts']}] {s['content']}" for s in sessions)
        messages = [{"role": "user", "content": f"以下是历史对话:\n{history}\n\n问题: {question}"}]
        n_hits = len(sessions)
    elif arm == "memory+retrieval":
        hits = await mem0_recall(q_obj["persona"], question, top_k=5)
        if not hits:
            messages = [{"role": "user", "content": question}]
        else:
            mem_text = "\n".join(f"- {h['content']}" for h in hits)
            messages = [{"role": "user",
                        "content": f"以下是关于该用户的历史记忆:\n{mem_text}\n\n请仅根据上述记忆回答: {question}"}]
        n_hits = len(hits)

    prompt_chars = sum(len(m.get("content", "")) for m in messages)
    t0 = time.perf_counter()
    try:
        answer = await call_model(messages, max_tokens=MAX_TOKENS)
        elapsed = time.perf_counter() - t0
    except Exception as e:
        answer = f"[ERROR: {type(e).__name__}]"
        elapsed = time.perf_counter() - t0

    correct, _ = await judge_answer(question, q_obj["gold"], answer)
    return {"id": q_obj["id"], "arm": arm, "persona": q_obj["persona"],
            "conflict_type": q_obj["conflict_type"], "n_hits": n_hits,
            "prompt_chars": prompt_chars, "gold": q_obj["gold"],
            "answer": answer[:200], "correct": correct,
            "elapsed_s": round(elapsed, 2)}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0=全量")
    parser.add_argument("--out", default=None, help="输出 jsonl 路径")
    args = parser.parse_args()

    personas = json.load(open(PERSONAS_FILE))
    p_map = {p["persona"]: p["sessions"] for p in personas}
    questions = [json.loads(l) for l in open(QUESTIONS_FILE)]
    if args.limit > 0:
        questions = questions[:args.limit]

    print(f"📊 [Mem0版] {len(personas)} 角色，{len(questions)} 问题")
    print("=" * 70)

    arms = ["none", "memory_only", "memory+retrieval"]
    results = []
    for arm in arms:
        print(f"\n▶️  {arm}")
        correct = 0
        total_chars = 0
        for i, q in enumerate(questions):
            r = await run_one(q, p_map[q["persona"]], arm)
            results.append(r)
            total_chars += r["prompt_chars"]
            if r["correct"]:
                correct += 1
            if (i + 1) % 10 == 0:
                print(f"  [{i+1:3d}/{len(questions)}] 累计 {correct}/{i+1} = {correct/(i+1):.1%}, "
                      f"平均 prompt {total_chars/(i+1):.0f} 字符", flush=True)
        print(f"  → {arm}: {correct}/{len(questions)} = {correct/len(questions):.1%}")

    # 保存
    out = args.out or f"evals/runs/mem0_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n✅ 已保存: {out}")


if __name__ == "__main__":
    asyncio.run(main())
