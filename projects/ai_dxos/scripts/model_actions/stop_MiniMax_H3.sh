#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
source /ai/ai_dxos/scripts/common/state.sh

LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [stop_MiniMax_H3] $*" | tee -a "${LOG}"; }

log "===============停止 MiniMax_H3 =============="

acquire_model_lock "MiniMax_H3" || log "获取锁失败，继续"

docker stop M01_H3 2>/dev/null || true
docker rm M01_H3 2>/dev/null || true
sleep 2

log "清理 Pool-A 的 GPU 显存..."
clean_gpu_pool "Pool-A"
sleep 2

python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s.get('running_models',{}).pop('MiniMax_H3', None)
json.dump(s,open(sf,'w'),indent=2)
"

release_model_lock "MiniMax_H3"
log "=========== MiniMax_H3 停止完成 ==========="
