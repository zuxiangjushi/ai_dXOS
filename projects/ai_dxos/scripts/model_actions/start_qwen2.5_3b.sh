#!/bin/bash
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="qwen2.5_3b"
CONTAINER_NAME="M19"
PORT=8023
MODEL_PATH="/models/qwen2.5-3b/qwen2.5-3b-instruct-q5_k_m.gguf"
IMAGE="ghcr.io/ggml-org/llama.cpp:server-cuda13"
LOG_FILE="/ai/ai_dxos/logs/model_actions.log"

log_info() { echo "[$(date '+%F %T')] [start_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

log_info "========== 启动 $MODEL_NAME (L0, CPU) =========="

# 1. 获取模型锁
if ! acquire_model_lock "$MODEL_NAME"; then log_info "获取模型锁失败"; exit 1; fi

# 2. 端口检查
if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
    log_info "端口 $PORT 已被占用"; release_model_lock "$MODEL_NAME"; exit 1
fi

# 3. 清理旧容器
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# 4. 启动容器 (限制 0 层 GPU，纯 CPU 运行)
log_info "启动 Docker 容器: $CONTAINER_NAME"
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$PORT:$PORT" \
    -v /ai/ai_dxos/volumes/models:/models:ro \
    --entrypoint /app/llama-server \
    "$IMAGE" \
    --model "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --n-gpu-layers 0 \
    --ctx-size 32768 \
        --metrics \
    --slots \
    --jinja

# 5. 健康检查
log_info "等待健康检查..."
if ! wait_health_check_full "$PORT" "$CONTAINER_NAME" "" "L0" 120; then
    log_info "△ 健康检查超时，但保留容器运行"
fi

# 6. 更新 state.json (原子写)
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 - << PYEOF > /tmp/state_new.json
import json, datetime
sf = "/ai/ai_dxos/configs/state/state.json"
with open(sf, 'r') as f: s = json.load(f)
s.setdefault('running_models', {})['${MODEL_NAME}'] = {
    'status': 'running',
    'container': '${CONTAINER_NAME}',
    'port': ${PORT},
    'gpu': 'CPU',
    'pool': 'L0',
    'engine': 'llama.cpp',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}
print(json.dumps(s, indent=2))
PYEOF
update_state_safe "$(cat /tmp/state_new.json)"
rm -f /tmp/state_new.json

release_model_lock "$MODEL_NAME"
log_info "========== $MODEL_NAME 启动完成 =========="
