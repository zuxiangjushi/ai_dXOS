#!/bin/bash
# /ai/ai_dxos/scripts/actions/wait.sh
# 等待命令执行成功

TIMEOUT="${1:-300}"
shift
CMD="$*"

echo "⏳ 等待命令执行 (超时 ${TIMEOUT}s): $CMD"

ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    if eval "$CMD" 2>/dev/null; then
        echo "✅ 命令执行成功 (耗时 ${ELAPSED}s)"
        exit 0
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

echo "❌ 命令执行超时 (${TIMEOUT}s)"
exit 1
