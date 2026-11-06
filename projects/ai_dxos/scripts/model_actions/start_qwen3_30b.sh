#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_qwen3_30b.sh
# 启动模型: qwen3_30b (Pool-ALL, GPU: 0,1,2,3, SGLang)

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_qwen3_30b] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_qwen3_30b] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始启动 qwen3_30b =========="

acquire_global_lock || exit 1

POOL="Pool-ALL"

# 池互斥：停止所有其他池的模型（Pool-A, Pool-B）
for other_pool in Pool-A Pool-B; do
    RUNNING=$(get_pool_running_models "$other_pool" "")
    if [ -n "$RUNNING" ]; then
        log_info "停止池 $other_pool 中的模型: $RUNNING"
        for m in $RUNNING; do
            if [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ]; then
                /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
            fi
        done
        sleep 2
    fi
done

# 停止同池其他模型
RUNNING=$(get_pool_running_models "Pool-ALL" "qwen3_30b")
if [ -n "$RUNNING" ]; then
    log_info "停止同池模型: $RUNNING"
    for m in $RUNNING; do
        if [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ]; then
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
        fi
    done
    sleep 2
fi

release_global_lock


# ==========================================
# ★ 核心池互斥逻辑 (Pool-ALL - 独占)
# ==========================================
echo "[互斥] 正在清理所有冲突池 (Pool-ALL/A/B) 的模型..."
for target_pool in Pool-ALL Pool-A Pool-B; do
    for m in $(get_pool_running_models "$target_pool" "qwen3_30b"); do
        echo "[互斥] 停止冲突模型: $m (所在池: $target_pool)"
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
done
clean_gpu_pool "Pool-ALL"

acquire_model_lock "qwen3_30b" || exit 1

log_info "清理 GPU: 0,1,2,3"
clean_gpu_pool "Pool-ALL"
sleep 3

if ! wait_gpu_ready "0,1,2,3" 60; then
    log_error "GPU 未全部就绪"
    release_model_lock "qwen3_30b"
    exit 1
fi

if ss -tlnp | grep -q ":8009 "; then
    log_error "端口 8009 已被占用"
    release_model_lock "qwen3_30b"
    exit 1
fi

docker run -d \
  --name M08_30B \
  --restart unless-stopped \
  --gpus all \
  --shm-size 32g \
  -e CUDA_VISIBLE_DEVICES=0,1,2,3 \
  -e NCCL_P2P_DISABLE=1 \
  -e NCCL_IB_DISABLE=1 \
  -p 8009:8009 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  --entrypoint python3 \
  lmsysorg/sglang:v0.5.17-cu130-runtime \
  -m sglang.launch_server \
  --model-path /models/Qwen3-30B-A3B-Instruct-2507 \
  --served-model-name qwen3_30b \
  --port 8009 \
  --host 0.0.0.0 \
  --tp 4 \
  --trust-remote-code \
  --mem-fraction-static 0.75 \
  --context-length 262144 \
  --disable-custom-all-reduce \
  --cuda-graph-max-bs 32

if [ $? -ne 0 ]; then
    log_error "Docker 启动失败"
    release_model_lock "qwen3_30b"
    exit 1
fi

# 立即更新状态为 starting
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true

python3 << PYEOF
import json, datetime, os
state_file="/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    with open(state_file,'w') as f: json.dump({"version":"6.0","running_models":{}},f)
with open(state_file,'r') as f: state=json.load(f)
state['running_models']['qwen3_30b']={
    'status':'starting','container':'M08_30B','port':8009,
    'gpu':'0,1,2,3','pool':'Pool-ALL','engine':'sglang',
    'updated_at':datetime.datetime.now().isoformat(),'progress':0
}
with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF

log_info "等待健康检查 (端口 8009) - 超时 600 秒..."
if wait_health_check 8009 600 "M08_30B" "0,1,2,3" "Pool-ALL"; then
    log_info "✅ 健康检查通过"
else
    log_error "❌ 健康检查超时，但容器仍在运行，尝试手动验证..."
    if docker ps | grep -q M08_30B && ss -tlnp | grep -q ":8009 "; then
        log_info "✅ 端口已监听，容器运行中，视为启动成功"
        python3 << PYEOF
import json, datetime, os
state_file="/ai/ai_dxos/configs/state/state.json"
with open(state_file,'r') as f: state=json.load(f)
state['running_models']['qwen3_30b']={
    'status':'running','container':'M08_30B','port':8009,
    'gpu':'0,1,2,3','pool':'Pool-ALL','engine':'sglang',
    'updated_at':datetime.datetime.now().isoformat(),'progress':100
}
with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF
        release_model_lock "qwen3_30b"
        log_info "========== ✅ qwen3_30b 启动完成（强制通过） =========="
        exit 0
    else
        docker stop M08_30B 2>/dev/null || true
        docker rm M08_30B 2>/dev/null || true
        release_model_lock "qwen3_30b"
        exit 1
    fi
fi

python3 << PYEOF
import json, datetime, os
state_file="/ai/ai_dxos/configs/state/state.json"
with open(state_file,'r') as f: state=json.load(f)
state['running_models']['qwen3_30b']={
    'status':'running','container':'M08_30B','port':8009,
    'gpu':'0,1,2,3','pool':'Pool-ALL','engine':'sglang',
    'updated_at':datetime.datetime.now().isoformat(),'progress':100
}
with open(state_file,'w') as f: json.dump(state,f,indent=2)
PYEOF

release_model_lock "qwen3_30b"
log_info "========== ✅ qwen3_30b 启动完成 =========="
