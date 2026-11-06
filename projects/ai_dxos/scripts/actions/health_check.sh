#!/bin/bash
# /ai/ai_dxos/scripts/actions/health_check.sh
# HTTP 健康检查

URL="${1:-http://127.0.0.1:8001/v1/models}"
TIMEOUT="${2:-10}"

curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$URL" 2>/dev/null | grep -q "200"
exit $?
