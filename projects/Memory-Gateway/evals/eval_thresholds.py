"""按类别评估引用质量

规则：
- realtime/factual: 必须有引用（硬性）
- howto/compare:    不强制（操作/推理题，模型知识合适）
- unanswerable:     应拒答（硬性）
"""
import sys, json, glob, os

THRESHOLDS = {
    "realtime":     {"min": 0.95, "judge": "min", "required": True},
    "factual":      {"min": 0.90, "judge": "min", "required": True},
    "howto":        {"judge": "skip", "required": False},
    "compare":      {"judge": "skip", "required": False},
    "unanswerable": {"min": 0.70, "judge": "min", "required": True, "metric": "refusal_precision"},
}

def main():
    files = sorted(glob.glob("/ai/Memory-Gateway/evals/runs/research_*.json"),
                   key=os.path.getmtime, reverse=True)
    if not files:
        print("❌ 没有评测结果"); sys.exit(1)
    latest = files[0]
    print(f"读: {latest}")
    d = json.load(open(latest))
    cat_stats = d.get("aggregate", {}).get("by_category", {})
    if not cat_stats:
        print("❌ 无 by_category"); sys.exit(1)

    print()
    print("════════ 类别阈值评估（v2）════════")
    hard_fail = 0
    for cat, stats in cat_stats.items():
        rule = THRESHOLDS.get(cat, {"min": 0.5, "judge": "min", "required": True})
        # ★ 按 metric 选择指标
        _metric = rule.get("metric", "citation_precision")
        if _metric == "refusal_precision":
            cp = stats.get("refusal_precision")
            if cp is None:
                cp = 0.0
        else:
            cp = stats.get("citation_precision", 0)
        if rule["judge"] == "skip":
            print(f"  ⏭️  {cat:14s} precision={cp:.3f}  (跳过：不强制引用)")
            continue
        if rule["judge"] == "min":
            ok = cp >= rule["min"]; thr = rule["min"]; op = "≥"
        else:
            ok = cp <= rule["max"]; thr = rule["max"]; op = "≤"
        mark = "✅" if ok else "❌"
        if not ok: hard_fail += 1
        print(f"  {mark} {cat:14s} precision={cp:.3f}  {op} {thr}  (n={stats['n']})")

    print()
    if hard_fail == 0:
        print("🎉 全部硬性指标通过")
    else:
        print(f"❌ {hard_fail} 个硬性指标未达标")

if __name__ == "__main__":
    main()
