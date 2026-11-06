#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_qwen36_35b.sh

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_qwen36_35b] $*" | tee -a "$LOG_FILE"; }

log_info "========== 停止 qwen36_35b =========="

acquire_model_lock "qwen36_35b" || log_info "获取锁失败，继续"

docker stop M06_36_35B 2>/dev/null || true
docker rm M06_36_35B 2>/dev/null || true
sleep 2

log_info "清理 Pool-ALL 的 GPU 显存..."
clean_gpu_pool "Pool-ALL"
sleep 2

python3 << PYEOF
import json, os
state_file = "/ai/ai_dxos/configs/state/state.json"
if os.path.exists(state_file):
    with open(state_file, 'r') as f:
        state = json.load(f)
    if 'running_models' in state:
        state['running_models'].pop('qwen36_35b', None)
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
PYEOF

release_model_lock "qwen36_35b"
log_info "========== ✅ qwen36_35b 停止完成 =========="
