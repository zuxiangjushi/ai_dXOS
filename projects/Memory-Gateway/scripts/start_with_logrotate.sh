#!/bin/bash
LOG_DIR="/ai/Memory-Gateway/logs"
mkdir -p "$LOG_DIR"
find "$LOG_DIR" -name "gateway_*.log" -mtime +7 -delete

LOG_FILE="$LOG_DIR/gateway_$(date +%Y%m%d).log"
cd /ai/Memory-Gateway
source .env.g0
export PILOT_KEY_M00="${PILOT_KEY_M00}"
export MEILISEARCH_API_KEY="${MEILISEARCH_API_KEY}"
export MEILI_URL="http://127.0.0.1:7700"
export LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY}"
export LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY}"
export LANGFUSE_HOST="${LANGFUSE_HOST}"
export LANGFUSE_ENABLED=true
export PYTHONPATH=/ai/Memory-Gateway:$PYTHONPATH
export UPSTREAM_BASE="http://192.168.10.132:9980"
export GATEWAY_PORT=9982
export MEMORY_INJECT_ENABLED=true
export MEMORY_WRITEBACK_ENABLED=true
export MEMORY_BACKEND=mem0
export MEM0_URL=http://127.0.0.1:8888
export MEM0_ADMIN_KEY="${MEM0_ADMIN_KEY}"

nohup ./.venv/bin/python fastapi_gateway.py > "$LOG_FILE" 2>&1 &
echo "✅ 网关已启动 → $LOG_FILE (PID=$!)"
