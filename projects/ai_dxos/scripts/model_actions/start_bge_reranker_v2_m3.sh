#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_bge_reranker_v2_m3.sh
# 启动模型: bge_reranker_v2_m3 (L0, CPU, Infinity)
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_bge_reranker_v2_m3] $*" | tee -a "$LOG_FILE"; }
log_warn()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_bge_reranker_v2_m3] [WARN] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_bge_reranker_v2_m3] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

MODEL_NAME="bge_reranker_v2_m3"
CONTAINER_NAME="M11_BGE_V2M3"
PORT=8012

cleanup() {
    echo "收到中断信号，清理 $CONTAINER_NAME ..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    release_model_lock "$MODEL_NAME" 2>/dev/null || true
    exit 1
}
trap cleanup SIGINT SIGTERM

log_info "========== 开始启动 $MODEL_NAME =========="

acquire_global_lock || exit 0
release_global_lock
acquire_model_lock "$MODEL_NAME" || exit 0

if ss -tlnp | grep -q ":$PORT "; then
    log_warn "端口 $PORT 已被占用，退出"
    release_model_lock "$MODEL_NAME"
    exit 0
fi

if ! docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p "$PORT:$PORT" \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  --entrypoint /bin/sh \
  michaelf34/infinity:0.0.77 \
  -c "infinity_emb v2 --model-id /models/bge-reranker-v2-m3 --port $PORT --host 0.0.0.0"; then
    log_error "Docker 启动失败"
    release_model_lock "$MODEL_NAME"
    exit 1
fi

if wait_health_check_infinity "$PORT" 300 "$CONTAINER_NAME"; then
    log_info "健康检查通过"
else
    log_warn "△ 健康检查超时，容器保持运行"
fi

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 << PYEOF
import json, datetime, os
state_file = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    with open(state_file, 'w') as f:
        json.dump({"version": "6.0", "running_models": {}}, f, indent=2)
with open(state_file, 'r') as f:
    state = json.load(f)
state.setdefault('running_models', {})['$MODEL_NAME'] = {
    'status': 'running',
    'container': '$CONTAINER_NAME',
    'port': $PORT,
    'gpu': 'CPU',
    'pool': 'L0',
    'engine': 'infinity',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}
with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF

release_model_lock "$MODEL_NAME"
log_info "=========== $MODEL_NAME 启动完成 ==========="
