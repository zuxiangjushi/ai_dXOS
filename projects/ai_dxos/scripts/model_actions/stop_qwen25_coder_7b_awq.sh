#!/bin/bash
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="qwen25_coder_7b_awq"
CONTAINER_NAME="vllm-qwen-coder"
WIN11_IP="192.168.10.208"
WIN11_USER="ypb"
WIN11_PASSWORD='738104'

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

remote_ssh() {
    sshpass -p "$WIN11_PASSWORD" ssh -o StrictHostKeyChecking=no \
        -o ConnectTimeout=10 "${WIN11_USER}@${WIN11_IP}" "$@"
}

log_info "========== 停止 WSL2 远程模型 ${MODEL_NAME} =========="

# 检查容器状态
CONTAINER_STATE=$(remote_ssh "docker inspect -f '{{.State.Status}}' ${CONTAINER_NAME} 2>/dev/null" 2>/dev/null || echo "not_exists")
log_info "容器当前状态: ${CONTAINER_STATE}"

if [ "$CONTAINER_STATE" = "running" ]; then
    log_info "停止容器..."
    remote_ssh "docker stop ${CONTAINER_NAME}" 2>&1 || true
else
    log_info "容器未运行，跳过停止"
fi

# 清理 state.json
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 << PYEOF
import json
sf = "/ai/ai_dxos/configs/state/state.json"
s = json.load(open(sf))
s.get('running_models', {}).pop('${MODEL_NAME}', None)
json.dump(s, open(sf, 'w'), indent=2)
PYEOF

log_info "========== ${MODEL_NAME} 停止完成 =========="
