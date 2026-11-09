#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [start_Flint] $*" | tee -a "$LOG"; }

MODEL_NAME="Flint"
CONTAINER_NAME="M17"
PORT=8014
POOL="Pool-ALL"
GPU_IDS="0,1,2,3"
IMAGE="flint-awq-g128-gptq-final:latest"
MODEL_PATH="/models/Flint-AWQ-g128-v2"

log "========== 启动 $MODEL_NAME (满血调优版) =========="

# 1. 池互斥
for pool in Pool-A Pool-B; do
    for m in $(get_pool_running_models "$pool"); do
        [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
done
for m in $(get_pool_running_models "Pool-ALL" "$MODEL_NAME"); do
    [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
done

# 2. 获取锁与清理
acquire_model_lock "$MODEL_NAME" || exit 1
clean_gpu_pool "$POOL"
sleep 3
if ! wait_gpu_ready "$GPU_IDS" 60; then
  log "[ERROR] GPU $GPU_IDS 未就绪"
  release_model_lock "$MODEL_NAME"
  exit 1
fi
sleep 3

# 3. 清理旧容器并启动
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
log "启动 SGLang 容器 (Flint 满血定制版 + LPM 调度)"

docker run -d --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --entrypoint python3 \
  --gpus all \
  --shm-size 32g \
  -p "$PORT:$PORT" \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -e SGLANG_DISABLE_TP_MEMORY_INBALANCE_CHECK=1 \
  -e SGLANG_EXTERNAL_MODEL_PACKAGE=flint_sglang \
  -e FLASHINFER_USE_CUDA_NORM=1 \
  -e FLINT_STRICT_TOOLS=1 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  "$IMAGE" \
  -m sglang.launch_server \
  --model-path "$MODEL_PATH" \
  --served-model-name "$MODEL_NAME" \
  --quantization moe_wna16 \
  --tp 4 \
  --trust-remote-code \
    --enable-metrics \ \
  --dtype bfloat16 \
  --enable-fp32-lm-head \
  --attention-backend triton \
  --host 0.0.0.0 \
  --port "$PORT" \
  --mem-fraction-static 0.85 \
  --context-length 262144 \
  --max-running-requests 8 \
  --cuda-graph-max-bs 8 \
  --schedule-policy lpm \
  --enable-dynamic-chunking \
  --chunked-prefill-size 8192 \
  --max-prefill-tokens 16384 \
  --grammar-backend flint \
  --tool-call-parser flint \
  --reasoning-parser flint \

if [ $? -ne 0 ]; then
    log "[ERROR] Docker 启动失败"
    release_model_lock "$MODEL_NAME"
    exit 1
fi

# 4. 写入 state.json
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 -c "
import json, datetime
sf = '/ai/ai_dxos/configs/state/state.json'
s = json.load(open(sf))
s.setdefault('running_models', {})['$MODEL_NAME'] = {
    'status': 'starting', 'container': '$CONTAINER_NAME', 'port': $PORT,
    'gpu': '$GPU_IDS', 'pool': '$POOL', 'engine': 'sglang',
    'updated_at': datetime.datetime.now().isoformat(), 'progress': 0
}
json.dump(s, open(sf, 'w'), indent=2)
"

# 5. 健康检查
log "等待健康检查"
for i in $(seq 1 60); do
  sleep 10
  if curl -s --max-time 3 http://127.0.0.1:$PORT/v1/models 2>/dev/null | grep -q "$MODEL_NAME"; then
    log "✅ 服务就绪（$((i*10)) 秒）"
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
    exit 0
  fi
  [ $((i % 3)) -eq 0 ] && log "健康检查中... ($((i*10)) 秒)"
done

log "健康检查超时"
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true
release_model_lock "$MODEL_NAME"
exit 1
