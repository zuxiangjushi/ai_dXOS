#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_Qwen3_Embedding_06B.sh
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="Qwen3_Embedding_06B"
CONTAINER_NAME="M-WIN-BGE"
WIN11_IP="192.168.10.208"
WIN11_USER="ypb"
WIN11_PASSWORD='738104'
WSL_DISTRO="Ubuntu-22.04"

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

log_info "========== 停止 ${MODEL_NAME} =========="

cat > /tmp/_stop_container.sh <<STOP_EOF
docker stop ${CONTAINER_NAME} 2>/dev/null || true
docker rm -f ${CONTAINER_NAME} 2>/dev/null || true
echo STOPPED
STOP_EOF

sshpass -p "$WIN11_PASSWORD" ssh -o StrictHostKeyChecking=no \
    "${WIN11_USER}@${WIN11_IP}" \
    "wsl -d ${WSL_DISTRO} -e bash -s" < /tmp/_stop_container.sh 2>&1 | tail -2

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 << PYEOF
import json, os
sf = "/ai/ai_dxos/configs/state/state.json"
if os.path.exists(sf):
    s = json.load(open(sf))
    s.get('running_models', {}).pop('${MODEL_NAME}', None)
    json.dump(s, open(sf, 'w'), indent=2)
PYEOF

log_info "========== ✅ ${MODEL_NAME} 已停止 =========="
