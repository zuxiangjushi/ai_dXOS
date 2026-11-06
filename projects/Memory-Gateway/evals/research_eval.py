"""Research Evidence Infrastructure 评测框架

核心指标：
1. CitationPrecision   - 引用准确率（期望引用时真引用）
2. avg_citations       - 平均引用数
3. avg_answer_len      - 平均答案长度
4. latency_p50/p95     - 延迟分布
5. avg_tokens          - token 消耗
6. groundedness        - 有据可依程度（有引用的回答占比）
7. refusal_precision   - 该拒答时拒答（含"无证据"判断）

用法：
    python evals/research_eval.py --limit 5
"""
import asyncio
import sys
import time
import json
import argparse
import re
from pathlib import Path
from typing import List, Dict
from datetime import datetime

if "/ai/Memory-Gateway" not in sys.path:
    sys.path.insert(0, "/ai/Memory-Gateway")


DEFAULT_TEST_SET = [
    # 实时类
    {"id": "q1", "query": "重庆今天气温", "expect_citation": True, "category": "realtime"},
    {"id": "q2", "query": "最新 Python 版本", "expect_citation": True, "category": "realtime"},
    {"id": "q4", "query": "今天重庆有雨吗", "expect_citation": True, "category": "realtime"},
    {"id": "q6", "query": "今天的日期", "expect_citation": True, "category": "realtime"},
    {"id": "q7", "query": "最近有什么 AI 新闻", "expect_citation": True, "category": "realtime"},
    # 事实类
    {"id": "q3", "query": "Qdrant 是什么向量数据库", "expect_citation": True, "category": "factual"},
    {"id": "q5", "query": "2026年国庆节放假安排", "expect_citation": True, "category": "factual"},
    {"id": "q8", "query": "bge-m3 是什么模型", "expect_citation": True, "category": "factual"},
    {"id": "q9", "query": "Meilisearch 支持中文吗", "expect_citation": True, "category": "factual"},
    {"id": "q13", "query": "RAG 是什么", "expect_citation": True, "category": "factual"},
    # 对比类（不强制引用，用模型知识）
    {"id": "q10", "query": "Qdrant 和 Milvus 哪个更好", "expect_citation": False, "category": "compare"},
    # 操作类（不强制引用，用模型知识）
    {"id": "q11", "query": "如何安装 Docker", "expect_citation": False, "category": "howto"},
    # 时效性
    {"id": "q12", "query": "2026年中秋节是哪天", "expect_citation": True, "category": "factual"},
    # 拒答测试
    {"id": "q14", "query": "张三昨天中午吃了什么", "expect_citation": False, "category": "unanswerable"},
    {"id": "q15", "query": "2027年诺贝尔奖得主是谁", "expect_citation": False, "category": "unanswerable"},
]


class ResearchEvaluator:
    def __init__(self, gateway_url: str = "http://127.0.0.1:9982",
                 api_key: str = None, model: str = None):
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key or self._read_key()
        # ★ 动态选模型（解耦底座模型名）
        if model is None:
            try:
                import sys
                sys.path.insert(0, "/ai/Memory-Gateway")
                from adapters.model_picker import pick_model
                model = pick_model()
            except Exception:
                model = "yy38_27b"  # 兜底
        self.model = model
        print(f"   [eval] 使用模型: {self.model}", flush=True)

    def _read_key(self) -> str:
        import os
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

    async def run_one(self, q: dict) -> dict:
        import httpx
        t0 = time.time()
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(
                    f"{self.gateway_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "X-User-Id": "eval_user",
                             "Content-Type": "application/json"},
                    json={"model": self.model,
                          "messages": [{"role": "user", "content": q["query"]}],
                          "max_tokens": 400})
                elapsed = time.time() - t0
                d = r.json()
                answer = d["choices"][0]["message"].get("content", "") or ""
                usage = d.get("usage") or {}
        except Exception as e:
            return {"id": q["id"], "query": q["query"], "error": str(e)[:100],
                    "latency": time.time() - t0}

        answer_clean = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
        # 匹配 [1] [2] [N] 都算引用
        citations = re.findall(r"\[(\d+|N)\]", answer_clean)
        has_citation = len(citations) > 0

        citation_correct = (has_citation if q.get("expect_citation")
                            else not has_citation)

        return {
            "id": q["id"],
            "query": q["query"],
            "category": q.get("category", "general"),
            "expect_citation": q.get("expect_citation", True),
            "answer_len": len(answer_clean),
            "has_citation": has_citation,
            "citation_count": len(citations),
            "citation_correct": citation_correct,
            "latency": elapsed,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "answer_preview": answer_clean[:150],
        }

    def evaluate_category_thresholds(self, cat_stats: dict) -> dict:
        """按类别评估是否达标

        阈值（可在业务上调整）：
        - realtime:     ≥ 0.95（实时数据必须引用）
        - factual:      ≥ 0.90
        - howto:        ≥ 0.50（可参考知识）
        - compare:      ≥ 0.50
        - unanswerable: ≤ 0.30（应避免引用，除非拒答）
        """
        THRESHOLDS = {
            "realtime":     {"min": 0.95, "judge": "min"},
            "factual":      {"min": 0.90, "judge": "min"},
            "howto":        {"min": 0.50, "judge": "min"},
            "compare":      {"min": 0.50, "judge": "min"},
            "unanswerable": {"max": 0.30, "judge": "max"},
        }
        out = {}
        for cat, stats in cat_stats.items():
            cp = stats["citation_precision"]
            rule = THRESHOLDS.get(cat, {"min": 0.50, "judge": "min"})
            if rule["judge"] == "min":
                ok = cp >= rule["min"]
                reason = f"需 ≥ {rule['min']}"
            else:
                ok = cp <= rule["max"]
                reason = f"需 ≤ {rule['max']}"
            out[cat] = {
                "precision": cp,
                "threshold": rule.get("min") or rule.get("max"),
                "judge": rule["judge"],
                "ok": ok,
                "reason": reason,
            }
        return out

    def aggregate(self, results: List[dict]) -> dict:
        valid = [r for r in results if "error" not in r]
        n = len(valid)
        if n == 0:
            return {"n_questions": len(results), "n_valid": 0}

        # 按类别细分
        by_cat = {}
        for r in valid:
            cat = r.get("category", "general")
            by_cat.setdefault(cat, []).append(r)

        cat_stats = {}
        for cat, rs in by_cat.items():
            m = len(rs)
            correct = sum(1 for r in rs if r["citation_correct"])
            # ★ 该类别内 refusal 成功数（用于 unanswerable）
            _refuse_rs = [r for r in rs if not r.get("expect_citation", True)]
            _refuse_ok = sum(1 for r in _refuse_rs if r.get("citation_correct"))
            _rp = round(_refuse_ok / len(_refuse_rs), 3) if _refuse_rs else None
            cat_stats[cat] = {
                "n": m,
                "citation_precision": round(correct / m, 3),
                "refusal_precision": _rp,
                "avg_citations": round(sum(r["citation_count"] for r in rs) / m, 2),
                "avg_latency": round(sum(r["latency"] for r in rs) / m, 2),
            }

        latencies = sorted(r["latency"] for r in valid)
        p50 = latencies[n // 2]
        p95 = latencies[min(n - 1, int(n * 0.95))]

        citation_precision = sum(1 for r in valid if r["citation_correct"]) / n
        # ★ 新增：拒答成功率（仅针对 expect_citation=False 的题）
        _refuse_qs = [r for r in valid if not r.get("expect_citation", True)]
        if _refuse_qs:
            _refuse_ok = sum(1 for r in _refuse_qs if r.get("citation_correct"))
            refusal_precision = _refuse_ok / len(_refuse_qs)
        else:
            refusal_precision = None
        groundedness = sum(1 for r in valid if r["has_citation"]) / n

        return {
            "n_questions": len(results),
            "n_valid": n,
            "by_category": cat_stats,
            "citation_precision": round(citation_precision, 3),
            "refusal_precision": round(refusal_precision, 3) if refusal_precision is not None else None,
            "groundedness": round(groundedness, 3),
            "avg_citations": round(sum(r["citation_count"] for r in valid) / n, 2),
            "avg_answer_len": round(sum(r["answer_len"] for r in valid) / n, 1),
            "latency_p50": round(p50, 2),
            "latency_p95": round(p95, 2),
            "latency_avg": round(sum(latencies) / n, 2),
            "avg_prompt_tokens": round(sum(r["prompt_tokens"] for r in valid) / n, 0),
            "avg_completion_tokens": round(sum(r["completion_tokens"] for r in valid) / n, 0),
        }

    async def run(self, test_set: List[dict]) -> dict:
        results = []
        for i, q in enumerate(test_set):
            print(f"  [{i+1}/{len(test_set)}] {q['query'][:40]}...", end=" ", flush=True)
            r = await self.run_one(q)
            results.append(r)
            if "error" in r:
                print(f"❌ {r['error'][:50]}", flush=True)
            else:
                mark = "✅" if r["citation_correct"] else "❌"
                print(f"{mark} {r['latency']:.1f}s, {r['citation_count']} 引用", flush=True)
                if not r["citation_correct"]:
                    preview = r.get("answer_preview", "")
                    print(f"     [debug] 答案: {preview[:150]}", flush=True)

        return {
            "aggregate": self.aggregate(results),
            "details": results,
            "timestamp": datetime.now().isoformat(),
        }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    test_set = DEFAULT_TEST_SET[:args.limit]

    print(f"════════ Research Eval ({len(test_set)} 题) ════════")
    ev = ResearchEvaluator()
    result = await ev.run(test_set)

    print()
    print("════════ 汇总 ════════")
    for k, v in result["aggregate"].items():
        if k == "by_category":
            continue
        print(f"  {k}: {v}")

    # 类别评估
    cat_stats = result["aggregate"].get("by_category", {})
    if cat_stats:
        print()
        print("════════ 类别阈值评估 ════════")
        ev = ResearchEvaluator()
        thresholds = ev.evaluate_category_thresholds(cat_stats)
        for cat, r in thresholds.items():
            mark = "✅" if r["ok"] else "❌"
            print(f"  {mark} {cat}: {r['precision']} ({r['judge']} {r['threshold']})")

    out = args.out or f"evals/runs/research_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存: {out}")


if __name__ == "__main__":
    asyncio.run(main())
