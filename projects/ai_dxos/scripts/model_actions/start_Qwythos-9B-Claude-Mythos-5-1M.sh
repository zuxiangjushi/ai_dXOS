#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_Qwythos-9B-Claude-Mythos-5-1M.sh
# 启动模型：Qwythos-9B-Claude-Mythos-5-1M（Pool-ALL，4 卡 tp=4，1M 上下文，MTP 投机解码）
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="Qwythos-9B-Claude-Mythos-5-1M"
CONTAINER_NAME="M15_Qwythos"
PORT=8019
POOL="Pool-ALL"
GPU_IDS="0,1,2,3"
MODEL_PATH="/models/Qwythos-9B-Claude-Mythos-5-1M"
IMAGE="lmsysorg/sglang:v0.5.17-cu130-runtime"

LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [start_${MODEL_NAME}] $*" | tee -a "$LOG"; }

cleanup() {
    echo "收到中断信号，清理 $CONTAINER_NAME ..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    release_model_lock "$MODEL_NAME" 2>/dev/null || true
    exit 1
}
trap cleanup SIGINT SIGTERM

log "========== 启动 $MODEL_NAME =========="

# ========== 池互斥：Pool-ALL 独占 4 卡，停止其他所有 GPU 池 ==========
for pool in Pool-A Pool-B Pool-EMB; do
    for m in $(get_pool_running_models "$pool"); do
        [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && \
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
done
for m in $(get_pool_running_models "Pool-ALL" "$MODEL_NAME"); do
    [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && \
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
done

# 获取锁 + 清理 GPU

# ==========================================
# ★ 核心池互斥逻辑 (Pool-ALL - 独占)
# ==========================================
echo "[互斥] 正在清理所有冲突池 (Pool-ALL/A/B) 的模型..."
for target_pool in Pool-ALL Pool-A Pool-B; do
    for m in $(get_pool_running_models "$target_pool" "Qwythos-9B-Claude-Mythos-5-1M"); do
        echo "[互斥] 停止冲突模型: $m (所在池: $target_pool)"
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
done
clean_gpu_pool "Pool-ALL"

acquire_model_lock "$MODEL_NAME" || exit 1
clean_gpu_pool "$POOL"
sleep 3

if ! wait_gpu_ready "$GPU_IDS" 60; then
    log "[ERROR] GPU $GPU_IDS 未就绪"
    release_model_lock "$MODEL_NAME"
    exit 1
fi

# 端口检查
if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then
    log "[ERROR] 端口 $PORT 已被占用"
    release_model_lock "$MODEL_NAME"
    exit 1
fi

# ========== 检查 chat_template.jinja 是否存在 ==========
HOST_MODEL_PATH="/ai/ai_dxos/volumes/models/Qwythos-9B-Claude-Mythos-5-1M"
if [ ! -f "$HOST_MODEL_PATH/chat_template.jinja" ]; then
    log "[WARN] 未找到 chat_template.jinja，可能影响 function call"
fi

# 清理旧容器
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# ========== 启动 SGLang 容器（1M 上下文 + MTP 投机解码）==========
log "启动 SGLang 容器（tp=4, ctx=1M, MTP 投机解码, fp16）"
docker run -d --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --gpus all \
    --shm-size 32g \
    -e CUDA_VISIBLE_DEVICES="$GPU_IDS" \
    -e NCCL_P2P_DISABLE=1 \
    -e NCCL_IB_DISABLE=1 \
    -e SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1 \
    -p "$PORT:$PORT" \
    -v /ai/ai_dxos/volumes/models:/models:ro \
    --entrypoint python3 \
    "$IMAGE" \
    -m sglang.launch_server \
    --model-path "$MODEL_PATH" \
    --served-model-name "$MODEL_NAME" \
    --tensor-parallel-size 4 \
    --context-length 1048576 \
    --dtype bfloat16 \
    --mem-fraction-static 0.85 \
    --host 0.0.0.0 \
    --port "$PORT" \
    --trust-remote-code \
    --disable-custom-all-reduce \
    --max-running-requests 2 \
    --cuda-graph-max-bs-decode 1 \
    --mm-feature-transport cpu \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_coder

if [ $? -ne 0 ]; then
    log "[ERROR] Docker 启动失败"
    release_model_lock "$MODEL_NAME"
    exit 1
fi

# ========== 写入初始状态 ==========
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 -c "
import json, datetime
sf = '/ai/ai_dxos/configs/state/state.json'
s = json.load(open(sf))
s.setdefault('running_models', {})['$MODEL_NAME'] = {
    'status': 'starting',
    'container': '$CONTAINER_NAME',
    'port': $PORT,
    'gpu': '$GPU_IDS',
    'pool': '$POOL',
    'engine': 'sglang',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 0
}
json.dump(s, open(sf, 'w'), indent=2)
"

# ========== 健康检查（1M 上下文加载慢，超时 20 分钟）==========
log "等待健康检查（最多 20 分钟，1M 上下文首次加载较慢）"
if ! wait_health_check_full "$PORT" "$CONTAINER_NAME" "$GPU_IDS" "$POOL" 600; then
    log "[ERROR] 健康检查失败"
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    release_model_lock "$MODEL_NAME"
    exit 1
fi

# ========== 更新为 running ==========
python3 -c "
import json, datetime
sf = '/ai/ai_dxos/configs/state/state.json'
s = json.load(open(sf))
s['running_models']['$MODEL_NAME']['status'] = 'running'
s['running_models']['$MODEL_NAME']['progress'] = 100
s['running_models']['$MODEL_NAME']['updated_at'] = datetime.datetime.now().isoformat()
json.dump(s, open(sf, 'w'), indent=2)
"

release_model_lock "$MODEL_NAME"
log "========== ✅ $MODEL_NAME 启动完成 =========="
