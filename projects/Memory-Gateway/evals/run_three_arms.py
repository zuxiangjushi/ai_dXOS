"""M4 三档对照跑分器（完整版：none / memory_only / memory+retrieval）"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, "/ai/Memory-Gateway")
from evals.judge import judge_answer
from evals.arm_runner import (
    call_model, build_context_none, build_context_memory_only,
    build_context_memory_retrieval, retrieval_recall,
)

DATASET = "evals/datasets/smoke_20.jsonl"
MAX_TOKENS = 500  # 从 200 提到 500，避免思考耗尽

async def run_one(sample, arm):
    if arm == "none":
        messages = build_context_none(sample)
        n_hits = 0
    elif arm == "memory_only":
        messages = build_context_memory_only(sample)
        n_hits = len(sample["sessions"])
    elif arm == "memory+retrieval":
        hits = await retrieval_recall(sample["persona"], sample["question"], top_k=5)
        messages = build_context_memory_retrieval(sample, hits)
        n_hits = len(hits)
    else:
        raise ValueError(arm)
    
    # 统计 prompt 字符数
    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
    
    t0 = time.perf_counter()
    try:
        answer = await call_model(messages, max_tokens=MAX_TOKENS)
        elapsed = time.perf_counter() - t0
    except Exception as e:
        answer = f"[ERROR: {type(e).__name__}]"
        elapsed = time.perf_counter() - t0
    
    correct, reason = await judge_answer(sample["question"], sample["gold"], answer)
    return {
        "id": sample["id"],
        "arm": arm,
        "conflict_type": sample["conflict_type"],
        "n_hits": n_hits,
        "prompt_chars": prompt_chars,
        "gold": sample["gold"],
        "answer": answer[:200],
        "correct": correct,
        "reason": reason,
        "elapsed_s": round(elapsed, 2),
    }

async def main():
    samples = [json.loads(l) for l in open(DATASET)]
    arms = ["none", "memory_only", "memory+retrieval"]
    
    print(f"📊 加载 {len(samples)} 条样本，跑 {len(arms)} 个档位")
    print("=" * 70)
    
    results = []
    for arm in arms:
        print(f"\n▶️  档位: {arm}")
        correct_count = 0
        total_chars = 0
        for i, s in enumerate(samples):
            r = await run_one(s, arm)
            results.append(r)
            total_chars += r["prompt_chars"]
            mark = "✅" if r["correct"] else "❌"
            print(f"  [{i+1:2d}/{len(samples)}] {mark} {s['id']} | "
                  f"{s['conflict_type']:16s} | hits={r['n_hits']} | chars={r['prompt_chars']:5d} | "
                  f"{r['elapsed_s']:5.2f}s | {r['answer'][:35]}")
            if r["correct"]:
                correct_count += 1
        avg_chars = total_chars / len(samples)
        print(f"  → {arm}: {correct_count}/{len(samples)} = {correct_count/len(samples):.1%} "
              f"| 平均 prompt {avg_chars:.0f} 字符")
    
    # 保存
    os.makedirs("evals/runs", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"evals/runs/run_{ts}.jsonl"
    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    
    # 汇总
    print("\n" + "=" * 70)
    print("📊 汇总")
    print("=" * 70)
    print(f"\n{'档位':<22} {'总体':<12} {'矛盾正确率':<12} {'简单事实':<12} {'平均prompt':<12}")
    print("-" * 70)
    for arm in arms:
        arm_results = [r for r in results if r["arm"] == arm]
        total = len(arm_results)
        overall = sum(1 for r in arm_results if r["correct"]) / total
        
        # 矛盾正确率
        conflict = [r for r in arm_results if r["conflict_type"] in ("preference_flip", "fact_correction")]
        conflict_acc = sum(1 for r in conflict if r["correct"]) / len(conflict) if conflict else 0
        
        # 简单事实
        simple = [r for r in arm_results if r["conflict_type"] == "none"]
        simple_acc = sum(1 for r in simple if r["correct"]) / len(simple) if simple else 0
        
        avg_chars = sum(r["prompt_chars"] for r in arm_results) / total
        
        print(f"{arm:<22} {overall:<12.1%} {conflict_acc:<12.1%} {simple_acc:<12.1%} {avg_chars:<12.0f}")
    
    print(f"\n💾 结果已保存到 {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
