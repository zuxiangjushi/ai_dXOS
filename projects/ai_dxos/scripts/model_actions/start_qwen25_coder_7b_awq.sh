#!/bin/bash
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="qwen25_coder_7b_awq"
CONTAINER_NAME="vllm-qwen-coder"
WIN11_IP="192.168.10.208"
WIN11_USER="ypb"
WIN11_PASSWORD='738104'
REMOTE_PORT=8001

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_${MODEL_NAME}] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

# 关键修复：避免 {{}} 被远程 shell 解析
remote_ssh() {
    sshpass -p "$WIN11_PASSWORD" ssh -o StrictHostKeyChecking=no \
        -o ConnectTimeout=10 -o ServerAliveInterval=30 \
        "${WIN11_USER}@${WIN11_IP}" "$@"
}

log_info "========== 启动 WSL2 远程模型 ${MODEL_NAME} =========="

# 1. 检查 SSH 连通性
if ! remote_ssh "echo SSH_OK" 2>/dev/null | grep -q SSH_OK; then
    log_error "无法 SSH 到 ${WIN11_IP}"
    exit 1
fi

# ★ Pool-WIN 池内互斥：停止 Qwen3_Embedding_06B
log_info "Pool-WIN 池内互斥：检查 Qwen3_Embedding_06B 是否运行..."
BGE_RUNNING=$(remote_ssh "docker ps --filter name=M-WIN-BGE --format '{{.Names}}'" 2>/dev/null | tr -d '\r\n' | tr -d '[:space:]')
if [ -n "$BGE_RUNNING" ]; then
    log_info "发现 Qwen3_Embedding_06B 正在运行，停止它..."
    remote_ssh "docker stop M-WIN-BGE" >/dev/null 2>&1 || true
    sleep 3

    chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
    python3 << 'PYEOF'
import json
sf = "/ai/ai_dxos/configs/state/state.json"
s = json.load(open(sf))
s.get('running_models', {}).pop('Qwen3_Embedding_06B', None)
json.dump(s, open(sf, 'w'), indent=2)
PYEOF
    log_info "Qwen3_Embedding_06B 已停止"
fi

# 2. 检查容器状态（用最简单的命令，避免模板转义）
CONTAINER_EXISTS=$(remote_ssh "docker ps -a --filter name=${CONTAINER_NAME} --format '{{.Names}}'" 2>/dev/null | tr -d '\r')
log_info "容器是否存在: [${CONTAINER_EXISTS}]"

if [ -z "$CONTAINER_EXISTS" ]; then
    # 容器不存在，创建
    log_info "容器不存在，创建并启动..."
    remote_ssh "docker run -d --name ${CONTAINER_NAME} --gpus all --restart unless-stopped -p ${REMOTE_PORT}:8000 -v /models/qwen:/models/qwen:ro vllm/vllm-openai:v0.19.0 --model /models/qwen --served-model-name ${MODEL_NAME} --host 0.0.0.0 --port 8000 --max-model-len 8192 --gpu-memory-utilization 0.75 --quantization awq_marlin" || {
        log_error "docker run 失败"
        exit 1
    }
else
    # 容器已存在，检查是否在跑
    CONTAINER_STATE=$(remote_ssh "docker inspect --format '{{.State.Status}}' ${CONTAINER_NAME}" 2>/dev/null | tr -d '\r')
    log_info "容器当前状态: [${CONTAINER_STATE}]"
    
    if [ "$CONTAINER_STATE" = "running" ]; then
        log_info "容器已在运行，跳过启动"
    else
        log_info "启动已存在的容器..."
        remote_ssh "docker start ${CONTAINER_NAME}" || { log_error "docker start 失败"; exit 1; }
    fi
fi

# 3. 健康检查
log_info "等待健康检查（最多 5 分钟）..."
healthy=false
for i in $(seq 1 60); do
    if curl -s --connect-timeout 3 -m 5 "http://${WIN11_IP}:${REMOTE_PORT}/v1/models" 2>/dev/null | grep -q "${MODEL_NAME}"; then
        log_info "✅ 健康检查通过（${i}×5 秒）"
        healthy=true
        break
    fi
    echo -n "."
    sleep 5
done

if [ "$healthy" = "false" ]; then
    log_error "❌ 健康检查超时"
    exit 1
fi

# 4. 更新 state.json
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 << PYEOF
import json, datetime
sf = "/ai/ai_dxos/configs/state/state.json"
s = json.load(open(sf))
s.setdefault('running_models', {})['${MODEL_NAME}'] = {
    'status': 'running',
    'container': '${CONTAINER_NAME}',
    'port': ${REMOTE_PORT},
    'gpu': 'RTX 3080 Ti (WSL2)',
    'pool': 'Pool-WIN',
    'engine': 'vllm',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}
json.dump(s, open(sf, 'w'), indent=2)
PYEOF

log_info "========== ${MODEL_NAME} 启动完成 =========="
