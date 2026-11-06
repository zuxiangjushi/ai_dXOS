#!/usr/bin/env python3
"""对比 A/B 两组结果"""
import sys
import json
from pathlib import Path

RESULT_DIR = Path("/ai/Memory-Gateway/evals/ab_runs")


def load_latest(group: str) -> dict:
    files = sorted(RESULT_DIR.glob(f"ab_{group}_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {}
    with open(files[0]) as f:
        d = json.load(f)
    d["_file"] = files[0].name
    return d


def main():
    A = load_latest("A")
    B = load_latest("B")

    if not A or not B:
        print("❌ 缺 A 或 B 结果")
        print(f"  A: {A.get('_file', '缺失')}")
        print(f"  B: {B.get('_file', '缺失')}")
        return

    a_agg = A.get("aggregate", {})
    b_agg = B.get("aggregate", {})

    print(f"\n{'=' * 70}")
    print(f"A/B 测试对比")
    print(f"{'=' * 70}")
    print(f"A: {A.get('mode')}")
    print(f"   文件: {A['_file']}")
    print(f"B: {B.get('mode')}")
    print(f"   文件: {B['_file']}")
    print()

    # 总览对比
    print(f"{'指标':<24} {'A':>12} {'B':>12} {'差异':>12}")
    print("-" * 62)

    for k in ["citation_precision", "refusal_precision",
              "latency_p50", "latency_avg", "avg_answer_len"]:
        av = a_agg.get(k)
        bv = b_agg.get(k)
        if av is None or bv is None:
            continue
        try:
            delta = (av - bv) / bv * 100 if bv != 0 else 0
            print(f"{k:<24} {av:>12.3f} {bv:>12.3f} {delta:>+11.1f}%")
        except Exception:
            print(f"{k:<24} {av:>12} {bv:>12}")

    print()
    print("分类别对比:")
    a_cat = a_agg.get("by_category", {})
    b_cat = b_agg.get("by_category", {})
    print(f"{'类别':<16} {'A_cp':>10} {'B_cp':>10} {'A_lat':>8} {'B_lat':>8}")
    print("-" * 56)
    for cat in ["realtime", "factual", "howto", "compare", "unanswerable"]:
        ac = a_cat.get(cat, {})
        bc = b_cat.get(cat, {})
        print(f"{cat:<16} "
              f"{ac.get('citation_precision', 0):>10.3f} "
              f"{bc.get('citation_precision', 0):>10.3f} "
              f"{ac.get('avg_latency', 0):>8.2f} "
              f"{bc.get('avg_latency', 0):>8.2f}")

    print()
    print("=" * 70)
    print("⚠️  样本仅 15 题，统计显著性弱，仅作趋势观察")
    print("=" * 70)


if __name__ == "__main__":
    main()
