#!/bin/bash
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="qwen2.5_3b"
CONTAINER_NAME="M19"
LOG_FILE="/ai/ai_dxos/logs/model_actions.log"

echo "[$(date '+%F %T')] [stop_${MODEL_NAME}] ========== 停止 $MODEL_NAME ==========" | tee -a "$LOG_FILE"

if ! acquire_model_lock "$MODEL_NAME"; then echo "获取锁失败"; exit 1; fi

docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true
sleep 2

# 清理 state.json
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 - << PYEOF > /tmp/state_new.json
import json
sf = "/ai/ai_dxos/configs/state/state.json"
with open(sf, 'r') as f: s = json.load(f)
s.get('running_models', {}).pop('${MODEL_NAME}', None)
print(json.dumps(s, indent=2))
PYEOF
update_state_safe "$(cat /tmp/state_new.json)"
rm -f /tmp/state_new.json

release_model_lock "$MODEL_NAME"
echo "[$(date '+%F %T')] [stop_${MODEL_NAME}] 停止完成" | tee -a "$LOG_FILE"
