#!/bin/bash
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="deepseek_v41_flash"
PORT=8022
GPU_IDS="2,3"
MODEL_PATH="/ai/ai_dxos/volumes/models/deepseek-v4.1-flash-IQ2_XS"
STRATA_DIR="/ai/ai_dxos/Strata"
STRATA_BIN="${STRATA_DIR}/bin/strata"
DSV41_PKG="${STRATA_DIR}/strata-dsv41-0.1.52-linux-x86_64-cuda-cuda13.tar.gz"
LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
STRATA_LOG="/ai/ai_dxos/logs/strata_M18.log"

log_info() { echo "[$(date '+%F %T')] [start_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

# 1. 池互斥
ALL_RUNNING=$(get_pool_running_models "Pool-ALL" "$MODEL_NAME")
if [ -n "$ALL_RUNNING" ]; then
    for m in $ALL_RUNNING; do /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true; done
    clean_gpu_pool "Pool-ALL"
else
    SAME_POOL_RUNNING=$(get_pool_running_models "Pool-B" "$MODEL_NAME")
    if [ -n "$SAME_POOL_RUNNING" ]; then
        for m in $SAME_POOL_RUNNING; do /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true; done
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

# 3. 启动
log_info "启动 Strata 原生引擎..."
cd "$STRATA_DIR"
unset CUDA_VISIBLE_DEVICES
export STRATA_NO_UPDATE=1
export STRATA_SKIP_CHECK=1
> "$STRATA_LOG"

nohup "$STRATA_BIN" launch \
    --family deepseek41 \
    --model ist-das-2.25bpw \
    --gpu $GPU_IDS \
    --model-path "$MODEL_PATH" \
    --port $PORT \
    --access lan \
    --api-key "sk-strata-DXOS-M18-Flash-2026" \
    --dsv41-package "$DSV41_PKG" \
    --no-tui \
    --yes \
    >> "$STRATA_LOG" 2>&1 &

# 4. 等待（只盯端口 8022）
log_info "等待端口 $PORT 监听..."
PORT_READY=false
for i in $(seq 1 900); do
    if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
        log_info "✅ 端口 $PORT 已监听，Strata 引擎已就绪！"
        PORT_READY=true
        break
    fi
    if [ $((i % 5)) -eq 0 ]; then
        PROGRESS=$(tail -n 1 "$STRATA_LOG" | sed 's/^[[:space:]]*//')
        log_info "[加载中] $((i*2))秒: $PROGRESS"
    fi
    sleep 2
done

if [ "$PORT_READY" = "false" ]; then
    log_info "❌ 端口未监听，启动失败。"
    pkill -9 -f "strata-dsv41" || true
    release_model_lock "$MODEL_NAME"
    exit 1
fi

# 5. 更新 state.json
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 << PYEOF
import json, datetime
sf = "/ai/ai_dxos/configs/state/state.json"
with open(sf, 'r') as f: s = json.load(f)
s.setdefault('running_models', {})['${MODEL_NAME}'] = {
    'status': 'running',
    'container': 'M18',
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
