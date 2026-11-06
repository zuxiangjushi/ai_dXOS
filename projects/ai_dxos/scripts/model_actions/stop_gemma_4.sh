#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_gemma_4.sh
# 停止模型: gemma_4 (DP=2, 容器 M03_gemma4 和 M03_gemma4_DP2)

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_gemma_4] $*" | tee -a "$LOG_FILE"; }

log_info "========== 停止 gemma_4 (DP=2) =========="

if ! acquire_model_lock "gemma_4"; then
    log_info "获取模型锁失败"
    exit 1
fi

for container in M03_gemma4 M03_gemma4_DP2; do
    log_info "停止容器: $container"
    docker stop "$container" 2>/dev/null || true
    docker rm "$container" 2>/dev/null || true
done
sleep 2

log_info "清理池 Pool-A 的 GPU 显存..."
clean_gpu_pool "Pool-A"
sleep 2

python3 << PYEOF
import json, os
state_file="/ai/ai_dxos/configs/state/state.json"
if os.path.exists(state_file):
    with open(state_file,'r') as f: state=json.load(f)
    if 'running_models' in state and 'gemma_4' in state['running_models']:
        del state['running_models']['gemma_4']
    with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF

release_model_lock "gemma_4"
log_info "========== ✅ gemma_4 (DP=2) 停止完成 =========="
