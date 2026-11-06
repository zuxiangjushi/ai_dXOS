#!/bin/bash
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="jev_decision"
CONTAINER_NAME="M16_Jev"
LOG_FILE="/ai/ai_dxos/logs/model_actions.log"

echo "[$(date '+%F %T')] [stop_${MODEL_NAME}] ========== 停止 $MODEL_NAME ==========" | tee -a "$LOG_FILE"

if ! acquire_model_lock "$MODEL_NAME"; then
    echo "[$(date '+%F %T')] 获取锁失败" | tee -a "$LOG_FILE"
    exit 1
fi

docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true
sleep 2

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 -c "
import json, os
sf = '/ai/ai_dxos/configs/state/state.json'
if os.path.exists(sf):
    with open(sf, 'r') as f: s = json.load(f)
    s.get('running_models', {}).pop('${MODEL_NAME}', None)
    with open(sf, 'w') as f: json.dump(s, f, indent=2)
"

release_model_lock "$MODEL_NAME"
echo "[$(date '+%F %T')] [stop_${MODEL_NAME}] ========== 停止完成 ==========" | tee -a "$LOG_FILE"
