#!/bin/bash
cd /ai/Memory-Gateway
source .env.g0 2>/dev/null

GW=http://127.0.0.1:9982
LF=${LANGFUSE_HOST:-http://192.168.10.132:3001}
TODAY=$(date +%Y-%m-%d)

echo "================================================"
echo " Memory-Gateway 日报  $TODAY"
echo "================================================"
echo ""

echo "--- 1. 请求量 ---"
curl -s $GW/metrics 2>/dev/null | grep '^gateway_requests_total' || echo "  (无数据)"
echo ""

echo "--- 2. 耗时分布 ---"
curl -s $GW/metrics 2>/dev/null | grep '^gateway_duration_seconds_count' || echo "  (无数据)"
echo ""

echo "--- 3. 记忆召回 ---"
curl -s $GW/metrics 2>/dev/null | grep -E '^memory_recall_total|^memory_recall_hits' || echo "  (无数据)"
echo ""

echo "--- 4. 写回 ---"
curl -s $GW/metrics 2>/dev/null | grep '^memory_write_total' || echo "  (无数据)"
echo ""

echo "--- 5. 降级事件 ---"
curl -s $GW/metrics 2>/dev/null | grep '^context_degraded_total' || echo "  (无数据)"
echo ""

echo "--- 6. Mem0 存活 ---"
curl -s -o /dev/null -w "  Mem0: HTTP %{http_code}\n" http://127.0.0.1:8888/docs
echo ""

echo "--- 7. Qdrant 点数 ---"
curl -s http://127.0.0.1:6333/collections/mem0_memories 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print('  mem0_memories:', d.get('result', {}).get('points_count', '?'))
except Exception:
    print('  (Qdrant 不可达)')
"
echo ""

echo "--- 8. Langfuse trace 数 ---"
AUTH=$(printf '%s:%s' "${LANGFUSE_PUBLIC_KEY}" "${LANGFUSE_SECRET_KEY}" | base64 -w0)
curl -s -H "Authorization: Basic ${AUTH}" "${LF}/api/public/traces?limit=100" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print('  最近 100 条中的数量:', len(d.get('data', [])))
except Exception:
    print('  (Langfuse 不可达)')
"
echo ""

echo "--- 9. 今日错误 ---"
if [ -f "logs/gateway_$(date +%Y%m%d).log" ]; then
  grep -aE "ERROR|失败|异常" "logs/gateway_$(date +%Y%m%d).log" 2>/dev/null | tail -5 || echo "  (无错误)"
else
  echo "  (今日无日志)"
fi
echo ""

echo "--- 10. 明文密钥检查 ---"
if grep -aqE 'sk-[A-Za-z0-9_-]{10,}' logs/gateway_$(date +%Y%m%d).log 2>/dev/null; then
  echo "  ❌ 发现明文密钥"
else
  echo "  ✅ 无明文"
fi
