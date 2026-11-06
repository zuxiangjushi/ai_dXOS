#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_qwen3_30b] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_qwen3_30b] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }
log_info "========== 停止 qwen3_30b =========="
acquire_model_lock "qwen3_30b" || exit 1
docker stop M08_30B 2>/dev/null || true
docker rm M08_30B 2>/dev/null || true
clean_gpu_pool "Pool-ALL"
sleep 2
if ! wait_gpu_ready "0,1,2,3" 30; then
    log_error "GPU 清理可能不完整"
fi
python3 << PYEOF
import json, os
state_file="/ai/ai_dxos/configs/state/state.json"
if os.path.exists(state_file):
    with open(state_file,'r') as f: state=json.load(f)
    if 'running_models' in state and 'qwen3_30b' in state['running_models']:
        del state['running_models']['qwen3_30b']
    with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF
release_model_lock "qwen3_30b"
log_info "========== ✅ 停止完成 =========="
