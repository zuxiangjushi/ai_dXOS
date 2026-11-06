#!/usr/bin/env python3
"""A/B 测试超参：对比"参数调优 on/off"两组

用法：
    # 跑 A 组（调优 on）
    PARAM_TUNING_ENABLED=true  ./.venv/bin/python evals/ab_test.py --group A

    # 跑 B 组（调优 off）
    PARAM_TUNING_ENABLED=false ./.venv/bin/python evals/ab_test.py --group B
"""
import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, "/ai/Memory-Gateway")

RESULT_DIR = Path("/ai/Memory-Gateway/evals/ab_runs")
RESULT_DIR.mkdir(parents=True, exist_ok=True)


def run_eval(group: str, limit: int = 15) -> dict:
    """跑一次完整评测"""
    print(f"\n{'=' * 60}")
    print(f"A/B 测试 - Group {group}")
    print(f"{'=' * 60}")

    # 关键：设置环境变量
    env = os.environ.copy()
    if group == "A":
        env["PARAM_TUNING_ENABLED"] = "true"
        mode = "参数调优 ON（分类场景化）"
    else:
        env["PARAM_TUNING_ENABLED"] = "false"
        mode = "参数调优 OFF（统一 temp=0.7）"

    print(f"模式: {mode}")
    print(f"样本: {limit} 题\n")

    t0 = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "/ai/Memory-Gateway/evals/research_eval.py",
         "--limit", str(limit)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    duration = time.perf_counter() - t0

    print(result.stdout[-3000:])
    if result.returncode != 0:
        print(f"❌ 评测失败: {result.stderr[-500:]}")
        return {"error": result.stderr[-500:], "group": group}

    # 从 evals/runs/ 里找最新的结果
    runs = sorted(Path("/ai/Memory-Gateway/evals/runs").glob("research_*.json"),
                  key=os.path.getmtime, reverse=True)
    if not runs:
        return {"error": "找不到评测结果", "group": group}

    with open(runs[0]) as f:
        eval_result = json.load(f)

    return {
        "group": group,
        "mode": mode,
        "duration_s": round(duration, 2),
        "result_file": str(runs[0]),
        "aggregate": eval_result.get("aggregate", {}),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", required=True, choices=["A", "B"])
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args()

    result = run_eval(args.group, args.limit)

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULT_DIR / f"ab_{args.group}_{ts}.json"
    with open(out_file, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 结果已保存: {out_file}")


if __name__ == "__main__":
    main()
