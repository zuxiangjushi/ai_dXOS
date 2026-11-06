
#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [stop_qwen36_27b] $*" | tee -a "$LOG"; }
log "========== 停止 qwen36_27b =========="
acquire_model_lock "qwen36_27b" || log "获取锁失败，继续"
docker stop M12_36_27B 2>/dev/null || true
docker rm M12_36_27B 2>/dev/null || true
sleep 2
clean_gpu_pool "Pool-ALL"
sleep 2
python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s.get('running_models',{}).pop('qwen36_27b', None)
json.dump(s,open(sf,'w'),indent=2)
"
release_model_lock "qwen36_27b"
log "========== ✅ qwen36_27b 停止完成 =========="
