#!/bin/bash
# /ai/ai_dxos/scripts/actions/check_port.sh
# 检查端口是否可用

PORT="$1"
if netstat -tlnp 2>/dev/null | grep -q ":${PORT} "; then
    echo "❌ 端口 $PORT 已被占用"
    exit 1
fi
echo "✅ 端口 $PORT 可用"
exit 0
