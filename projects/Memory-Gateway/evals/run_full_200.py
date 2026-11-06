"""M4 完整集跑分器：200 问题 × 3 档位"""
import asyncio
import json
import os
import sys
import time
import hashlib
import argparse
from datetime import datetime

sys.path.insert(0, "/ai/Memory-Gateway")
from evals.judge import judge_answer
from evals.arm_runner import call_model

PERSONAS_FILE = "evals/datasets/personas_20.json"
QUESTIONS_FILE = "evals/datasets/questions_200.jsonl"
MAX_TOKENS = 500

def ws_for(persona):
    return "eval_" + hashlib.md5(persona.encode()).hexdigest()[:8]

async def embed(text):
    import httpx
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("http://192.168.10.132:8003/embeddings",
                        json={"model": "models/bge-m3", "input": [text]})
        body = r.json()
        if isinstance(body, list) and body and isinstance(body[0], list):
            return body[0]
        if isinstance(body, dict) and "data" in body:
            d = body["data"]
            if isinstance(d, list) and d:
                x = d[0]
                return x.get("embedding") if isinstance(x, dict) else x
        raise RuntimeError("embed 格式异常")

async def retrieval_recall(persona, question, top_k=5):
    import httpx
    ws = ws_for(persona)
    qv = await embed(question)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"http://localhost:6333/collections/gateway_memory_vector/points/search",
            json={"vector": qv, "limit": top_k, "with_payload": True,
                  "filter": {"must": [
                      {"key": "workspace_id", "match": {"value": ws}},
                      {"key": "is_deleted", "match": {"value": False}}
                  ]}}
        )
        hits = r.json().get("result", [])
    return [{"content": h["payload"]["content"], "score": h["score"]} for h in hits]

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
        hits = await retrieval_recall(q_obj["persona"], question, top_k=5)
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
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个问题（0=全量）")
    args = parser.parse_args()

    personas = json.load(open(PERSONAS_FILE))
    p_map = {p["persona"]: p["sessions"] for p in personas}
    questions = [json.loads(l) for l in open(QUESTIONS_FILE)]
    if args.limit > 0:
        questions = questions[:args.limit]

    print(f"📊 {len(personas)} 角色，{len(questions)} 问题")
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
            if (i + 1) % 20 == 0:
                print(f"  [{i+1:3d}/{len(questions)}] 累计 {correct}/{i+1} = {correct/(i+1):.1%}, "
                      f"平均 prompt {total_chars/(i+1):.0f} 字符", flush=True)
        print(f"  → {arm}: {correct}/{len(questions)} = {correct/len(questions):.1%}, "
              f"平均 prompt {total_chars/len(questions):.0f} 字符")

    # 保存
    os.makedirs("evals/runs", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"evals/runs/full200_{ts}.jsonl"
    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 汇总
    print("\n" + "=" * 70)
    print("📊 汇总")
    print("=" * 70)
    print(f"{'档位':<22} {'总体':<10} {'矛盾正确率':<12} {'简单事实':<10} {'弃答':<10} {'平均prompt':<12}")
    print("-" * 70)
    for arm in arms:
        arm_r = [r for r in results if r["arm"] == arm]
        total = len(arm_r)
        overall = sum(1 for r in arm_r if r["correct"]) / total

        def acc(ct):
            arr = [r for r in arm_r if r["conflict_type"] == ct]
            return sum(1 for r in arr if r["correct"]) / len(arr) if arr else 0

        conflict_arr = [r for r in arm_r if r["conflict_type"] in ("preference_flip", "fact_correction")]
        conflict_acc = sum(1 for r in conflict_arr if r["correct"]) / len(conflict_arr) if conflict_arr else 0
        simple_acc = acc("none")
        reject_acc = acc("should_reject")
        avg_chars = sum(r["prompt_chars"] for r in arm_r) / total

        print(f"{arm:<22} {overall:<10.1%} {conflict_acc:<12.1%} {simple_acc:<10.1%} "
              f"{reject_acc:<10.1%} {avg_chars:<12.0f}")

    print(f"\n💾 已保存: {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
