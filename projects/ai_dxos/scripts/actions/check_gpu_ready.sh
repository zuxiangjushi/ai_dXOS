#!/bin/bash
# /ai/ai_dxos/scripts/actions/check_gpu_ready.sh
# 检查 GPU 显存是否足够

GPU_IDS="${1:-0,1}"
REQUIRED_MEM="${2:-18}"

for gpu in $(echo "$GPU_IDS" | tr ',' ' '); do
    FREE_MEM=$(nvidia-smi --id=$gpu --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
    if [ -z "$FREE_MEM" ] || [ "$FREE_MEM" -lt "$REQUIRED_MEM" ]; then
        echo "❌ GPU $gpu 显存不足 (需要 ${REQUIRED_MEM}GB, 可用 ${FREE_MEM:-0}GB)"
        exit 1
    fi
    echo "✅ GPU $gpu 显存充足 (${FREE_MEM}GB 可用)"
done
exit 0
