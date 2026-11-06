#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [stop_Holo_31] $*" | tee -a "$LOG"; }

log "========== 停止 Holo_31 (DP=2) =========="
acquire_model_lock "Holo_31" || log "获取锁失败，继续"

docker stop M02_Holo31 2>/dev/null || true
docker rm M02_Holo31 2>/dev/null || true
docker stop M02_Holo31_DP2 2>/dev/null || true
docker rm M02_Holo31_DP2 2>/dev/null || true
sleep 2

clean_gpu_pool "Pool-B"
sleep 2

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true

python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s.get('running_models',{}).pop('Holo_31', None)
json.dump(s,open(sf,'w'),indent=2)
"

release_model_lock "Holo_31"
log "========== ✅ Holo_31 停止完成 =========="
