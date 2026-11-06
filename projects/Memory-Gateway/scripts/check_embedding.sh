#!/bin/bash
# bge-m3 健康检查：连续测 3 次，慢/挂就记录
cd /ai/Memory-Gateway
TS=$(date +%s)
LOG=/var/log/mg_embedding_health.log
ALERT=/var/log/mg_embedding_alert.log

TOTAL=0
FAIL=0
MAX=0

for i in 1 2 3; do
  T=$(curl -s -o /dev/null -w "%{time_total}" \
    -X POST http://192.168.10.132:8003/embeddings \
    -H "Content-Type: application/json" \
    -d '{"model":"models/bge-m3","input":["health"]}' \
    --max-time 30 2>/dev/null)
  CODE=$?
  if [ "$CODE" != "0" ]; then
    FAIL=$((FAIL+1))
    T=30
  fi
  TOTAL=$(echo "$TOTAL + $T" | bc)
  MAX=$(echo "if ($T > $MAX) $T else $MAX" | bc)
done

AVG=$(echo "scale=3; $TOTAL / 3" | bc)
echo "[$(date '+%F %T')] avg=${AVG}s max=${MAX}s fail=$FAIL/3" >> $LOG

# 报警阈值：平均 > 2s 或 有失败
if [ "$FAIL" != "0" ] || [ "$(echo "$AVG > 2.0" | bc)" = "1" ]; then
  echo "[$(date '+%F %T')] ⚠️ bge-m3 慢/挂: avg=${AVG}s fail=$FAIL" >> $ALERT
  # 尝试重启 bge-m3（可选，默认关）
  if [ "${MG_AUTO_RESTART_EMB:-0}" = "1" ]; then
    docker restart M00_3BGE >> $LOG 2>&1
    echo "[$(date '+%F %T')] 🔄 已重启 M00_3BGE" >> $LOG
  fi
fi

# 保留 7 天日志
find /var/log -name "mg_embedding_health.log" -mtime +7 -exec truncate -s 0 {} \; 2>/dev/null || true
