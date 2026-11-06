#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_Qwythos-9B-Claude-Mythos-5-1M.sh
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="Qwythos-9B-Claude-Mythos-5-1M"
CONTAINER_NAME="M15_Qwythos"

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

log_info "========== 停止 $MODEL_NAME =========="

if ! acquire_model_lock "$MODEL_NAME"; then
    log_info "获取模型锁失败"
    exit 1
fi

docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true
sleep 2

log_info "清理池 Pool-ALL 的 GPU 显存..."
clean_gpu_pool "Pool-ALL"
sleep 2

# 清理 state.json
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 << PYEOF
import json, os
state_file = "/ai/ai_dxos/configs/state/state.json"
if os.path.exists(state_file):
    with open(state_file, 'r') as f:
        state = json.load(f)
    if 'running_models' in state and '$MODEL_NAME' in state['running_models']:
        del state['running_models']['$MODEL_NAME']
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
PYEOF

release_model_lock "$MODEL_NAME"
log_info "========== ✅ $MODEL_NAME 停止完成 =========="
