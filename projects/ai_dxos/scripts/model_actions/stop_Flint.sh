#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_Flint.sh
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [stop_Flint] $*" | tee -a "$LOG"; }

MODEL_NAME="Flint"
CONTAINER_NAME="M17"
POOL="Pool-ALL"

log "========== 停止 $MODEL_NAME =========="

acquire_model_lock "$MODEL_NAME" || true
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

log "清理池 $POOL 的 GPU 显存..."
clean_gpu_pool "$POOL"
sleep 2

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 -c "
import json, os
sf = '/ai/ai_dxos/configs/state/state.json'
if os.path.exists(sf):
    s = json.load(open(sf))
    s.get('running_models', {}).pop('$MODEL_NAME', None)
    json.dump(s, open(sf, 'w'), indent=2)
"
release_model_lock "$MODEL_NAME"
log "========== ✅ $MODEL_NAME 已停止 =========="
