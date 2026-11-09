#!/bin/bash
# 启动模型：jev_decision (L0, CPU, llama.cpp, 常驻)
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="jev_decision"
CONTAINER_NAME="M16_Jev"
PORT=8021
MODEL_PATH="/models/QWen3.5_4B/Qwen3.5-4B-Q4_K_M.gguf"
# 使用本地现成的镜像，绝不触发网络拉取
IMAGE="ghcr.io/ggml-org/llama.cpp:server-cuda13"

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%F %T')] [start_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

log_info "========== 开始启动 $MODEL_NAME (L0) =========="

# 1. 获取模型锁（L0 池不需要清 GPU 互斥）
if ! acquire_model_lock "$MODEL_NAME"; then
    log_info "获取模型锁失败"; exit 1
fi

# 2. 端口检查
if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
    log_info "端口 $PORT 已被占用"; release_model_lock "$MODEL_NAME"; exit 1
fi

# 3. 清理旧容器
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# 4. 启动容器（--restart unless-stopped 保证常驻）
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

# 5. 健康检查（复用 common_pool.sh 里的通用检查）
log_info "等待健康检查..."
if ! wait_health_check_full "$PORT" "$CONTAINER_NAME" "" "L0" 120; then
    log_info "△ 健康检查超时，但保留容器运行（可能模型加载较慢）"
fi

# 6. 更新 state.json（标准的解锁-写入-锁定流程）
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 << PYEOF
import json, datetime, os
sf = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(sf):
    with open(sf, 'w') as f: json.dump({"version": "6.0", "running_models": {}}, f, indent=2)
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
with open(sf, 'w') as f: json.dump(s, f, indent=2)
PYEOF

# 7. 释放锁
release_model_lock "$MODEL_NAME"
log_info "========== $MODEL_NAME 启动完成 =========="
