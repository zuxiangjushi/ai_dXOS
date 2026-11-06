#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_gemma_4.sh
# 启动模型: gemma_4 (DP=2, GPU 0 和 1, 端口 8004 和 8013)

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_gemma_4] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_gemma_4] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始启动 gemma_4 (DP=2) =========="

acquire_global_lock || exit 1

RUNNING=$(get_pool_running_models "Pool-A" "gemma_4")
if [ -n "$RUNNING" ]; then
    log_info "Pool-A 已有运行中模型: $RUNNING，执行停止..."
    for m in $RUNNING; do
        if [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ]; then
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
        fi
    done
    sleep 3
fi

release_global_lock

# ==========================================


# ==========================================
# ★ 核心池互斥逻辑 (Pool-A - 非独占)
# ==========================================
ALL_RUNNING=$(get_pool_running_models "Pool-ALL" "gemma_4")

if [ -n "$ALL_RUNNING" ]; then
    # 情况 1: 发现独占池 (Pool-ALL) 正在运行，清理全盘
    echo "[互斥] 发现 Pool-ALL 正在运行，正在停止并全盘清理..."
    for m in $ALL_RUNNING; do
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
    clean_gpu_pool "Pool-ALL"
else
    # 情况 2: 没有 ALL，只清理自己所在的池 (Pool-A)
    SAME_POOL_RUNNING=$(get_pool_running_models "Pool-A" "gemma_4")
    if [ -n "$SAME_POOL_RUNNING" ]; then
        echo "[互斥] 发现 Pool-A 内存在冲突模型，正在停止..."
        for m in $SAME_POOL_RUNNING; do
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
        done
    fi
    clean_gpu_pool "Pool-A"
fi

acquire_model_lock "gemma_4" || exit 1

log_info "清理 GPU: 0,1"
clean_gpu_pool "Pool-A"
sleep 5

for i in $(seq 1 30); do
    if wait_gpu_ready "0,1" 5; then
        log_info "GPU 0,1 已就绪"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "GPU 未就绪（等待 150 秒后）"
        release_model_lock "gemma_4"
        exit 1
    fi
    sleep 5
done

for port in 8004 8013; do
    if ss -tlnp | grep -q ":${port} "; then
        log_error "端口 ${port} 已被占用"
        release_model_lock "gemma_4"
        exit 1
    fi
done

# ---------- 启动实例1 (GPU 0, 端口 8004) ----------
log_info "启动实例1: M03_gemma4 (GPU 0, 端口 8004)"
docker run -d \
  --name M03_gemma4 \
  --restart unless-stopped \
  --gpus '"device=0"' \
  --shm-size 16g \
  -p 8004:8004 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  ghcr.io/ggml-org/llama.cpp:server-cuda13 \
  -m /models/Gemma-4/gemma-4-31b-jang-crack-Q4_K_M.gguf \
  --host 0.0.0.0 \
  --port 8004 \
  --n-gpu-layers 999 \
  --ctx-size 131072 \
  --threads 4 \
  --threads-batch 4 \
  --ubatch-size 512 \
  --flash-attn on \
  --cache-type-k q4_0 \
  --cache-type-v q4_0

if [ $? -ne 0 ]; then
    log_error "实例1 启动失败"
    release_model_lock "gemma_4"
    exit 1
fi

# ---------- 启动实例2 (GPU 1, 端口 8013) ----------
log_info "启动实例2: M03_gemma4_DP2 (GPU 1, 端口 8013)"
docker run -d \
  --name M03_gemma4_DP2 \
  --restart unless-stopped \
  --gpus '"device=1"' \
  --shm-size 16g \
  -p 8013:8013 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  ghcr.io/ggml-org/llama.cpp:server-cuda13 \
  -m /models/Gemma-4/gemma-4-31b-jang-crack-Q4_K_M.gguf \
  --host 0.0.0.0 \
  --port 8013 \
  --n-gpu-layers 999 \
  --ctx-size 131072 \
  --threads 4 \
  --threads-batch 4 \
  --ubatch-size 512 \
  --flash-attn on \
  --cache-type-k q4_0 \
  --cache-type-v q4_0

if [ $? -ne 0 ]; then
    log_error "实例2 启动失败，清理实例1"
    docker stop M03_gemma4 2>/dev/null || true
    docker rm M03_gemma4 2>/dev/null || true
    release_model_lock "gemma_4"
    exit 1
fi

# 更新状态为 starting
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true

python3 << PYEOF
import json, datetime, os
state_file="/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    with open(state_file,'w') as f: json.dump({"version":"6.0","running_models":{}},f)
with open(state_file,'r') as f: state=json.load(f)
if 'running_models' not in state:
    state['running_models']={}
state['running_models']['gemma_4']={
    'status':'starting','container':'M03_gemma4','port':8004,
    'gpu':'0,1','pool':'Pool-A','engine':'llama_cpp',
    'updated_at':datetime.datetime.now().isoformat(),'progress':0
}
with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF

log_info "等待实例1 (端口 8004) 健康检查..."
if ! wait_health_check_llama 8004 600 "M03_gemma4" "0" "Pool-A"; then
    log_error "实例1 健康检查超时"
    docker stop M03_gemma4 M03_gemma4_DP2 2>/dev/null || true
    docker rm M03_gemma4 M03_gemma4_DP2 2>/dev/null || true
    release_model_lock "gemma_4"
    exit 1
fi

log_info "等待实例2 (端口 8013) 健康检查..."
if ! wait_health_check_llama 8013 600 "M03_gemma4_DP2" "1" "Pool-A"; then
    log_error "实例2 健康检查超时"
    docker stop M03_gemma4 M03_gemma4_DP2 2>/dev/null || true
    docker rm M03_gemma4 M03_gemma4_DP2 2>/dev/null || true
    release_model_lock "gemma_4"
    exit 1
fi

python3 << PYEOF
import json, datetime
state_file="/ai/ai_dxos/configs/state/state.json"
with open(state_file,'r') as f: state=json.load(f)
state['running_models']['gemma_4']={
    'status':'running','container':'M03_gemma4','port':8004,
    'gpu':'0,1','pool':'Pool-A','engine':'llama_cpp',
    'updated_at':datetime.datetime.now().isoformat(),'progress':100
}
with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF

release_model_lock "gemma_4"
log_info "========== ✅ gemma_4 (DP=2) 启动完成 =========="
