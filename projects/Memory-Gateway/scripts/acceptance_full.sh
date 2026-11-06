#!/bin/bash
# Memory-Gateway 综合验收（全绿 = 生产就绪）
cd /ai/Memory-Gateway
source .env.g0 2>/dev/null

PASS=0; FAIL=0; WARN=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
warn() { echo "  ⚠️  $1"; WARN=$((WARN+1)); }
chk()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got=$2 want=$3)"; fi; }

echo "═══════════════════════════════════════════"
echo " Memory-Gateway 综合验收 $(date '+%F %T')"
echo "═══════════════════════════════════════════"

echo ""
echo "【1/10】进程与服务"
pgrep -f fastapi_gateway >/dev/null && ok "网关进程" || bad "网关进程"
for svc in mg-g0-langfuse-1 mem0-api mg-g0-qdrant-1 mg-g0-pg_ssd-1 embed-proxy; do
  docker ps --format '{{.Names}}' | grep -q "^$svc$" && ok "$svc" || bad "$svc"
done

echo ""
echo "【2/10】端口"
for p in 9982 3001 8888 6333 5433 7700 3101; do
  ss -tlnp 2>/dev/null | grep -q ":$p " && ok ":$p" || bad ":$p"
done

echo ""
echo "【3/10】健康检查"
R=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9982/healthz)
chk "GET /healthz" "$R" "200"

echo ""
echo "【4/10】端点清单（应 12 个）"
N=$(grep -c "@app\." fastapi_gateway.py)
if [ "$N" -ge 12 ]; then ok "端点数 $N"; else bad "端点数 $N (want >=12)"; fi

echo ""
echo "【5/10】6 客户端协议回归"
bash scripts/regression_clients.sh > /tmp/regr.log 2>&1
if grep -q "全部通过" /tmp/regr.log; then ok "6 客户端全绿"; else bad "客户端失败"; fi

echo ""
echo "【6/10】RAG 语义检索"
U="accept_$(date +%s)"
curl -s -X POST http://127.0.0.1:9982/v1/rag/documents \
  -H "Content-Type: application/json" -H "Authorization: Bearer ${PILOT_KEY_M00}" \
  -H "X-User-Id: $U" \
  -d '{"title":"t","content":"验收测试文档：主库 PostgreSQL，向量库 Qdrant"}' > /dev/null
sleep 3
HITS=$(./.venv/bin/python -c "
import asyncio, os, sys
sys.path.insert(0, '/ai/Memory-Gateway')
for line in open('/ai/Memory-Gateway/.env.g0'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())
from adapters.qdrant_rag import get_rag
async def main():
    hits = await get_rag().search('项目用什么向量库', user_id='$U', limit=3)
    print(len(hits))
asyncio.run(main())
" 2>/dev/null)
if [ "$HITS" -ge 1 ]; then ok "RAG 语义命中 $HITS 条"; else bad "RAG 语义 0 条"; fi

echo ""
echo "【7/10】记忆召回"
curl -s -X POST http://127.0.0.1:9982/v1/chat/completions \
  -H "Content-Type: application/json" -H "Authorization: Bearer ${PILOT_KEY_M00}" \
  -H "X-User-Id: zhangsan" \
  -d '{"model":"qwen3_32b","messages":[{"role":"user","content":"我住在哪"}],"max_tokens":20}' > /dev/null
sleep 2
RECALL=$(curl -s http://127.0.0.1:9982/metrics | grep -E 'memory_recall_total\{.*hit' | head -1)
if [ -n "$RECALL" ]; then ok "记忆召回 hit"; else warn "记忆召回无 hit（新用户正常）"; fi

echo ""
echo "【8/10】metrics 持久化"
N=$(docker exec mg-g0-pg_ssd-1 psql -U probe -d probe -t -c \
  "SELECT count(*) FROM metrics_snapshots;" 2>/dev/null | tr -d ' ')
if [ "$N" -ge 1 ]; then ok "metrics 快照 $N 条"; else bad "metrics 快照 0"; fi

echo ""
echo "【9/10】日志健康"
LOG=logs/gateway_$(date +%Y%m%d).log
FAILS=$(grep -ac "pre-call 失败" "$LOG" 2>/dev/null | head -1)
FAILS=${FAILS:-0}
if [ "$FAILS" = "0" ]; then ok "pre-call 失败 = 0"; else bad "pre-call 失败 $FAILS 次"; fi
if grep -aqE 'sk-[A-Za-z0-9_-]{10,}' "$LOG"; then bad "日志有明文密钥"; else ok "日志无明文密钥"; fi

echo ""
echo "【10/10】cron 任务"
CRON=$(crontab -l 2>/dev/null)
echo "$CRON" | grep -q "daily_report" && ok "日报 cron" || bad "日报 cron"
echo "$CRON" | grep -q "snapshot_metrics" && ok "metrics cron" || bad "metrics cron"
echo "$CRON" | grep -q "check_embedding" && ok "embedding cron" || bad "embedding cron"

echo ""
echo "═══════════════════════════════════════════"
echo " 结果: ✅ $PASS / ❌ $FAIL / ⚠️  $WARN"
echo "═══════════════════════════════════════════"

if [ "$FAIL" = "0" ]; then
  echo "🎉 全部通过"
  exit 0
else
  echo "❌ 有 $FAIL 项失败"
  exit 1
fi
