#!/bin/bash
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="yy38_27b"
CONTAINER_NAME="M04_YY27B"
PORT=8005
GPU_IDS="2,3"
MODEL_PATH="/models/YY/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-Q8_K_P.gguf"
IMAGE="ghcr.io/ggml-org/llama.cpp:server-cuda13"
LOG_FILE="/ai/ai_dxos/logs/model_actions.log"

log_info() { echo "[$(date '+%F %T')] [start_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

log_info "========== 启动 $MODEL_NAME (Pool-B, GPU $GPU_IDS) =========="

# 1. 核心池互斥逻辑 (Pool-B 非独占)
ALL_RUNNING=$(get_pool_running_models "Pool-ALL" "$MODEL_NAME")
if [ -n "$ALL_RUNNING" ]; then
    log_info "[互斥] 发现 Pool-ALL 正在运行，正在停止并全盘清理..."
    for m in $ALL_RUNNING; do
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
    clean_gpu_pool "Pool-ALL"
else
    SAME_POOL_RUNNING=$(get_pool_running_models "Pool-B" "$MODEL_NAME")
    if [ -n "$SAME_POOL_RUNNING" ]; then
        log_info "[互斥] 发现 Pool-B 内存在冲突模型，正在停止..."
        for m in $SAME_POOL_RUNNING; do
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
        done
    fi
    clean_gpu_pool "Pool-B"
fi

# 2. 锁与端口检查
if ! acquire_model_lock "$MODEL_NAME"; then
    log_info "获取模型锁失败"; exit 1
fi

if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
    log_info "端口 $PORT 已被占用"; release_model_lock "$MODEL_NAME"; exit 1
fi

# 3. 清理旧容器
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# 4. 启动 Docker 容器 (优化参数版)
log_info "启动 Docker 容器: $CONTAINER_NAME (优化参数: flash-attn, q8_0 KV, 64K ctx, 4 parallel)"
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --gpus '"device='"$GPU_IDS"'"' \
    --shm-size 16g \
    -p "$PORT:$PORT" \
    -v /ai/ai_dxos/volumes/models:/models:ro \
    --entrypoint /app/llama-server \
    "$IMAGE" \
    --model "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --n-gpu-layers 999 \
    --ctx-size 65536 \
    --flash-attn on \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --parallel 4 \
    --kv-unified \
    --cont-batching \
    --cache-prompt \
    --context-shift \
    --mlock \
    --threads 16 \
    --threads-batch 16 \
        --metrics \
    --slots \
    --jinja

# 5. 健康检查
log_info "等待健康检查..."
if ! wait_health_check_full "$PORT" "$CONTAINER_NAME" "$GPU_IDS" "Pool-B" 600; then
    log_info "△ 健康检查超时，请手动查看 docker logs $CONTAINER_NAME"
fi

# 6. 更新 state.json (原子写)
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 - << PYEOF > /tmp/state_new.json
import json, datetime
sf = "/ai/ai_dxos/configs/state/state.json"
with open(sf, 'r') as f: s = json.load(f)
s.setdefault('running_models', {})['${MODEL_NAME}'] = {
    'status': 'running', 'container': '${CONTAINER_NAME}',
    'port': ${PORT}, 'gpu': '${GPU_IDS}', 'pool': 'Pool-B',
    'engine': 'llama.cpp', 'updated_at': datetime.datetime.now().isoformat(), 'progress': 100
}
print(json.dumps(s, indent=2))
PYEOF
update_state_safe "$(cat /tmp/state_new.json)"
rm -f /tmp/state_new.json

release_model_lock "$MODEL_NAME"
log_info "========== $MODEL_NAME 启动完成 =========="
