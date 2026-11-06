#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_Qwen3_Embedding_06B.sh
# 启动模型: Qwen3_Embedding_06B (Pool-WIN, Win11 WSL2 vLLM)
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="Qwen3_Embedding_06B"
CONTAINER_NAME="M-WIN-BGE"
WIN11_IP="192.168.10.208"
WIN11_USER="ypb"
WIN11_PASSWORD='738104'
WSL_DISTRO="Ubuntu-22.04"
REMOTE_PORT=8002
CONTAINER_PORT=8000
MODEL_PATH="/root/models/Qwen3-Embedding-0.6B"
IMAGE="vllm/vllm-openai:v0.19.0"

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_${MODEL_NAME}] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

remote_ssh() {
    sshpass -p "$WIN11_PASSWORD" ssh -o StrictHostKeyChecking=no \
        -o ConnectTimeout=10 -o ServerAliveInterval=30 \
        "${WIN11_USER}@${WIN11_IP}" \
        "wsl -d ${WSL_DISTRO} -e bash -s"
}

log_info "========== 启动 WSL2 远程模型 ${MODEL_NAME} =========="

# 1. 检查 SSH 连通性
cat > /tmp/_ping.sh <<'PING_EOF'
echo SSH_OK
PING_EOF
if ! remote_ssh < /tmp/_ping.sh 2>/dev/null | grep -q SSH_OK; then
    log_error "无法 SSH 到 ${WIN11_IP}"
    exit 1
fi

# 2. Pool-WIN 池内互斥：停止 vllm-qwen-coder
log_info "Pool-WIN 池内互斥：检查 vllm-qwen-coder..."
cat > /tmp/_check_qwen.sh <<'CHECK_EOF'
docker ps --filter name=vllm-qwen-coder --format '{{.Names}}'
CHECK_EOF
QWEN_RUNNING=$(remote_ssh < /tmp/_check_qwen.sh 2>/dev/null | tr -d '\r\n' | tr -d '[:space:]')
if [ -n "$QWEN_RUNNING" ]; then
    log_info "发现 vllm-qwen-coder 正在运行，停止它..."
    cat > /tmp/_stop_qwen.sh <<'STOPQ_EOF'
docker stop vllm-qwen-coder 2>/dev/null || true
docker wait vllm-qwen-coder 2>/dev/null || true
sleep 3
echo STOP_DONE
STOPQ_EOF
    remote_ssh < /tmp/_stop_qwen.sh >/dev/null 2>&1 || true

    chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
    python3 << PYEOF
import json
sf = "/ai/ai_dxos/configs/state/state.json"
s = json.load(open(sf))
s.get('running_models', {}).pop('qwen25_coder_7b_awq', None)
json.dump(s, open(sf, 'w'), indent=2)
PYEOF
    log_info "vllm-qwen-coder 已停止"
fi

# 3. 清理旧容器
log_info "清理旧容器..."
cat > /tmp/_clean.sh <<CLEAN_EOF
docker rm -f ${CONTAINER_NAME} 2>/dev/null || true
sleep 2
echo CLEANED
CLEAN_EOF
remote_ssh < /tmp/_clean.sh >/dev/null 2>&1 || true

# 4. 检查模型路径
log_info "检查模型路径..."
cat > /tmp/_check_model.sh <<CHECKM_EOF
if [ -f "${MODEL_PATH}/config.json" ]; then
    echo MODEL_OK
else
    echo MODEL_MISSING
fi
CHECKM_EOF
MODEL_EXISTS=$(remote_ssh < /tmp/_check_model.sh 2>/dev/null | tr -d '\r\n' | tr -d '[:space:]')
if [ "$MODEL_EXISTS" != "MODEL_OK" ]; then
    log_error "❌ 模型路径不存在: ${MODEL_PATH}"
    exit 1
fi
log_info "✅ 模型路径已就绪"

# 5. 启动 vLLM 容器
log_info "启动 vLLM 容器..."
cat > /tmp/_run_container.sh <<RUN_EOF
docker run -d \
    --name ${CONTAINER_NAME} \
    --gpus all \
    --restart unless-stopped \
    -p ${REMOTE_PORT}:${CONTAINER_PORT} \
    -v ${MODEL_PATH}:/models/Qwen3-Embedding-0.6B:ro \
    --entrypoint /bin/bash \
    ${IMAGE} \
    -c "vllm serve /models/Qwen3-Embedding-0.6B --served-model-name ${MODEL_NAME} --host 0.0.0.0 --port ${CONTAINER_PORT} --gpu-memory-utilization 0.85 --max-model-len 8192 --trust-remote-code"
RUN_EOF

if ! remote_ssh < /tmp/_run_container.sh; then
    log_error "docker run 失败"
    exit 1
fi

# 6. 快速失败检查（15 秒）
log_info "容器已启动，等待 15 秒检查..."
sleep 15

cat > /tmp/_state.sh <<ST_EOF
docker inspect --format '{{.State.Status}}' ${CONTAINER_NAME} 2>/dev/null || echo "not_found"
ST_EOF
CONTAINER_STATE=$(remote_ssh < /tmp/_state.sh 2>/dev/null | tr -d '\r\n' | tr -d '[:space:]')
log_info "容器状态: [${CONTAINER_STATE}]"

if [ "$CONTAINER_STATE" != "running" ]; then
    log_error "❌ 容器启动后立即退出"
    cat > /tmp/_logs.sh <<LOG_EOF
docker logs ${CONTAINER_NAME} --tail 50 2>&1
LOG_EOF
    remote_ssh < /tmp/_logs.sh 2>&1 | sed 's/^/  /'
    cat > /tmp/_rm.sh <<RM_EOF
docker rm -f ${CONTAINER_NAME} 2>/dev/null || true
RM_EOF
    remote_ssh < /tmp/_rm.sh >/dev/null 2>&1 || true
    exit 1
fi

# 7. 健康检查（5 分钟）
log_info "等待健康检查（最多 5 分钟）..."
healthy=false
for i in $(seq 1 60); do
    if [ $((i % 5)) -eq 0 ]; then
        state=$(remote_ssh < /tmp/_state.sh 2>/dev/null | tr -d '\r\n' | tr -d '[:space:]')
        if [ "$state" != "running" ]; then
            log_error "❌ 容器已崩溃（状态: $state）"
            remote_ssh < /tmp/_logs.sh 2>&1 | sed 's/^/  /'
            remote_ssh < /tmp/_rm.sh >/dev/null 2>&1 || true
            exit 1
        fi
    fi

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
    remote_ssh < /tmp/_logs.sh 2>&1 | sed 's/^/  /'
    exit 1
fi

# 8. 更新 state.json
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

log_info "========== ✅ ${MODEL_NAME} 启动完成 =========="
