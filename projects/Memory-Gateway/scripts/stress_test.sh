#!/bin/bash
# 压测：并发 20 请求 × 3 协议混合
cd /ai/Memory-Gateway
source .env.g0 2>/dev/null

CONC=${1:-20}
echo "════════ 压测 CONC=$CONC ════════"

TMP=$(mktemp -d)
echo "临时目录: $TMP"

START=$(date +%s)

# 启动并发
for i in $(seq 1 $CONC); do
  (
    case $((i % 3)) in
      0)  # OpenAI
        curl -s -o /dev/null -w "%{http_code} %{time_total}\n" \
          -X POST http://127.0.0.1:9982/v1/chat/completions \
          -H "Content-Type: application/json" -H "Authorization: Bearer ${PILOT_KEY_M00}" \
          -H "X-User-Id: stress_$i" \
          -d '{"model":"qwen3_32b","messages":[{"role":"user","content":"hi"}],"max_tokens":10}' \
          --max-time 60 > "$TMP/r_$i.txt"
        ;;
      1)  # Anthropic
        curl -s -o /dev/null -w "%{http_code} %{time_total}\n" \
          -X POST http://127.0.0.1:9982/v1/messages \
          -H "Content-Type: application/json" -H "x-api-key: ${PILOT_KEY_M00}" \
          -H "X-User-Id: stress_$i" \
          -d '{"model":"qwen3_32b","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}' \
          --max-time 60 > "$TMP/r_$i.txt"
        ;;
      2)  # Responses
        curl -s -o /dev/null -w "%{http_code} %{time_total}\n" \
          -X POST http://127.0.0.1:9982/v1/responses \
          -H "Content-Type: application/json" -H "Authorization: Bearer ${PILOT_KEY_M00}" \
          -H "X-User-Id: stress_$i" \
          -d '{"model":"qwen3_32b","input":"hi","max_output_tokens":10}' \
          --max-time 60 > "$TMP/r_$i.txt"
        ;;
    esac
  ) &
done
wait

END=$(date +%s)
DURATION=$((END - START))

echo ""
echo "═══ 结果 ═══"
echo "总耗时: ${DURATION}s"
echo ""

OK=0; BAD=0
TIMES=""
for f in $TMP/r_*.txt; do
  LINE=$(cat "$f" 2>/dev/null)
  CODE=$(echo "$LINE" | awk '{print $1}')
  T=$(echo "$LINE" | awk '{print $2}')
  if [ "$CODE" = "200" ]; then
    OK=$((OK+1))
    TIMES="$TIMES $T"
  else
    BAD=$((BAD+1))
    echo "  ❌ $(basename $f): $LINE"
  fi
done

echo "成功: $OK / 失败: $BAD"
echo ""
echo "═══ 耗时统计 ═══"
echo "$TIMES" | tr ' ' '\n' | grep -v '^$' | sort -n | python3 -c "
import sys
xs = [float(x) for x in sys.stdin if x.strip()]
if not xs:
    print('  (无数据)')
else:
    xs.sort()
    n = len(xs)
    print(f'  N={n}')
    print(f'  min={xs[0]:.2f}s')
    print(f'  p50={xs[n//2]:.2f}s')
    print(f'  p95={xs[int(n*0.95)]:.2f}s')
    print(f'  max={xs[-1]:.2f}s')
"

rm -rf "$TMP"
