#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_bge_reranker_v2_m3.sh
# 停止模型: bge_reranker_v2_m3 (L0)

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_bge_reranker_v2_m3] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_bge_reranker_v2_m3] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始停止 bge_reranker_v2_m3 =========="

if ! acquire_model_lock "bge_reranker_v2_m3"; then
    log_error "获取模型锁失败"
    exit 1
fi

log_info "停止容器: M11_BGE_V2M3"
docker stop M11_BGE_V2M3 2>/dev/null || true
docker rm M11_BGE_V2M3 2>/dev/null || true
sleep 2

python3 << PYEOF
import json, os
state_file="/ai/ai_dxos/configs/state/state.json"
if os.path.exists(state_file):
    with open(state_file,'r') as f: state=json.load(f)
    if 'running_models' in state and 'bge_reranker_v2_m3' in state['running_models']:
        del state['running_models']['bge_reranker_v2_m3']
    with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF

release_model_lock "bge_reranker_v2_m3"
log_info "========== ✅ bge_reranker_v2_m3 停止完成 =========="
