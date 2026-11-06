#!/usr/bin/env bash
fail=0
for f in contracts/*.py deploy/g0/report.py deploy/g0/probes/*.py; do
  if ! ./.venv/bin/python -m py_compile "$f" 2>/tmp/e; then
    echo "语法损坏  $f"; head -2 /tmp/e; fail=1; fi
done
for m in errors scope memory scoring credentials plan routing context t0_rules; do
  ./.venv/bin/python -c "import contracts.$m" 2>/dev/null || { echo "缺失/报错 contracts/$m.py"; fail=1; }
done
for m in p1_embedding p2_rerank p3_retrieval p4_pg_owner p5_extraction p6_lease p7_rule_tier p8_eventloop; do
  ./.venv/bin/python -c "import deploy.g0.probes.$m" 2>/dev/null || { echo "探针损坏 probes/$m.py"; fail=1; }
done
[ $fail -eq 0 ] && echo "✅ 全部文件完整" || echo "❌ 按上面清单，用对应代码块逐个重写"
