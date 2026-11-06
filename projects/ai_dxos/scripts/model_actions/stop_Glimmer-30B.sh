#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [stop_Glimmer-30B] $*" | tee -a "$LOG"; }

log "========== 停止 Glimmer-30B =========="
acquire_model_lock "Glimmer-30B" || log "获取锁失败，继续"

docker stop M14--Glimmer-30B 2>/dev/null || true
docker rm M14--Glimmer-30B 2>/dev/null || true
sleep 2

clean_gpu_pool "Pool-ALL"
sleep 2

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s.get('running_models',{}).pop('Glimmer-30B', None)
json.dump(s,open(sf,'w'),indent=2)
"

release_model_lock "Glimmer-30B"
log "========== ✅ Glimmer-30B 停止完成 =========="
