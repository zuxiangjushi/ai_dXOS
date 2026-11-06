#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_yy35b_q6.sh

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_yy35b_q6] $*" | tee -a "$LOG_FILE"; }

log_info "========== 停止 yy35b_q6 (DP=2) =========="

if ! acquire_model_lock "yy35b_q6"; then
    log_info "获取模型锁失败"
    exit 1
fi

for container in M05_YY35B_Q6 M05_YY35B_Q6_DP2; do
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
    if 'running_models' in state and 'yy35b_q6' in state['running_models']:
        del state['running_models']['yy35b_q6']
    with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF

release_model_lock "yy35b_q6"
log_info "========== ✅ yy35b_q6 (DP=2) 停止完成 =========="
