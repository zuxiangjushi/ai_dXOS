#!/bin/bash
# ==============================================================================
# [FROZEN BASELINE 2026-11-08] 
# 此脚本为经过 4 卡并发压测、长文本穿透测试验证的最终版本。
# 已达成：上下文上限 211581 tokens，4并发 32t/s。
# 严禁随意修改参数，如需修改请先复制备份并重新跑压测！
# ==============================================================================
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="qwen38_27b"
CONTAINER_NAME="M07_38_27B"
PORT=8008
POOL="Pool-ALL"
GPU_IDS="0,1,2,3"
IMAGE="lmsysorg/sglang:v0.5.17-cu130-runtime"
LOG_FILE="/ai/ai_dxos/logs/model_actions.log"

log_info() { echo "[$(date '+%F %T')] [start_${MODEL_NAME}] $*" | tee -a "$LOG_FILE"; }

log_info "========== 启动 $MODEL_NAME (多模态保命版) =========="

# 1. 池互斥逻辑
ALL_RUNNING=$(get_pool_running_models "$POOL" "$MODEL_NAME")
if [ -n "$ALL_RUNNING" ]; then
    log_info "[互斥] 发现 Pool-ALL 内存在冲突模型，正在停止..."
    for m in $ALL_RUNNING; do
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
fi

# 2. 锁与端口检查
if ! acquire_model_lock "$MODEL_NAME"; then log_info "获取模型锁失败"; exit 1; fi
if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
    log_info "端口 $PORT 已被占用"; release_model_lock "$MODEL_NAME"; exit 1
fi

# 3. 清理旧容器
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# 4. 启动 SGLang 容器
log_info "启动 SGLang 容器"
docker run -d --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --gpus all \
    --shm-size 32g \
    -e CUDA_VISIBLE_DEVICES=$GPU_IDS \
    -e NCCL_P2P_DISABLE=1 \
    -e NCCL_IB_DISABLE=1 \
    -p $PORT:$PORT \
    -v /ai/ai_dxos/volumes/models:/models:ro \
    --entrypoint python3 \
    "$IMAGE" \
    -m sglang.launch_server \
    --model-path /models/Qwen3.8-27B \
    --served-model-name "$MODEL_NAME" \
    --port $PORT --host 0.0.0.0 --tp 4 \
    --trust-remote-code \
    --enable-metrics \
    --mem-fraction-static 0.83 \
    --context-length 262144 \
    --max-running-requests 8 \
    --disable-custom-all-reduce \
    --cuda-graph-max-bs 8 \
    --disable-prefill-cuda-graph \
    --mm-feature-transport cpu \
    --schedule-policy lpm \
    --enable-dynamic-chunking \
    --chunked-prefill-size 8192 \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_coder \
    --default-chat-template-kwargs '{"enable_thinking": true, "reasoning_effort": "medium"}' \
    --preferred-sampling-params '{"temperature": 0.6, "top_p": 0.9, "top_k": 20, "presence_penalty": 0.3}'

# 5. 健康检查
log_info "等待健康检查..."
if ! wait_health_check_full "$PORT" "$CONTAINER_NAME" "$GPU_IDS" "$POOL" 600; then
    log_info "△ 健康检查超时，请查看容器日志。"
fi

# 6. 更新 state.json
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 - << PYEOF > /tmp/state_new.json
import json, datetime
sf = "/ai/ai_dxos/configs/state/state.json"
with open(sf, 'r') as f: s = json.load(f)
s.setdefault('running_models', {})['${MODEL_NAME}'] = {
    'status': 'running', 'container': '${CONTAINER_NAME}',
    'port': ${PORT}, 'gpu': '${GPU_IDS}', 'pool': '${POOL}',
    'engine': 'sglang', 'updated_at': datetime.datetime.now().isoformat(), 'progress': 100
}
print(json.dumps(s, indent=2))
PYEOF
update_state_safe "$(cat /tmp/state_new.json)"
rm -f /tmp/state_new.json

release_model_lock "$MODEL_NAME"
log_info "========== $MODEL_NAME 启动完成 =========="
