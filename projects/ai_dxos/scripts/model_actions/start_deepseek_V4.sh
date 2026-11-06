#!/bin/bash
# 启动模型：deepseek_V4 (Pool-B, GPU 2,3, Strata 引擎)
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="deepseek_V4"
CONTAINER_NAME="M18" 
PORT=8022
GPU_IDS="2,3"
MODEL_PATH="/ai/ai_dxos/volumes/models/deepseek-v4.1-flash-IQ2_XS"
CACHE_PATH="/ai/ai_dxos/volumes/cache"
STRATA_DIR="/ai/ai_dxos/Strata"
STRATA_BIN="${STRATA_DIR}/bin/strata"
DSV41_PKG="${STRATA_DIR}/strata-dsv41-0.1.52-linux-x86_64-cuda-cuda13.tar.gz"

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
PID_FILE="/ai/ai_dxos/scripts/model_actions/M18.pid"

log_info() { echo "[$(date '+%F %T')] [start_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

log_info "========== 启动 $MODEL_NAME (Pool-B, GPU 2,3) =========="

# 1. 核心池互斥逻辑
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

# 2. 获取锁与端口检查
if ! acquire_model_lock "$MODEL_NAME"; then
    log_info "获取模型锁失败"; exit 1
fi

if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
    log_info "端口 $PORT 已被占用"; release_model_lock "$MODEL_NAME"; exit 1
fi

# 3. 启动 Strata
log_info "启动 Strata 原生引擎 (GPU $GPU_IDS)..."
cd "$STRATA_DIR"
export CUDA_VISIBLE_DEVICES=$GPU_IDS

nohup "$STRATA_BIN" launch \
    --family deepseek41 \
    --model ist-das-2.25bpw \
    --gpu $GPU_IDS \
    --model-path "$MODEL_PATH" \
    --cache-path "$CACHE_PATH" \
    --api-port $PORT \
    --host 0.0.0.0 \
    --dsv41-package "$DSV41_PKG" \
    --no-tui \
    >> "/ai/ai_dxos/logs/strata_M18.log" 2>&1 &

echo $! > "$PID_FILE"

# 4. 健康检查
log_info "等待健康检查 (首次加载可能需要几分钟)..."
if ! wait_health_check_full "$PORT" "" "$GPU_IDS" "Pool-B" 600; then
    log_info "△ 健康检查超时，请手动查看日志: tail -f /ai/ai_dxos/logs/strata_M18.log"
else
    log_info "✅ 健康检查通过！"
fi

# 5. 更新 state.json
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
    'gpu': '2,3',
    'pool': 'Pool-B',
    'engine': 'strata',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}
with open(sf, 'w') as f: json.dump(s, f, indent=2)
PYEOF

release_model_lock "$MODEL_NAME"
log_info "========== $MODEL_NAME 启动完成 =========="
