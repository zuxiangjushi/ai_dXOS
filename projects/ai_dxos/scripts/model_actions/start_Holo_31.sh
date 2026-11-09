#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [start_Holo_31] $*" | tee -a "$LOG"; }
log "========== 启动 Holo_31 (DP=2) =========="

for pool in Pool-ALL; do
  for m in $(get_pool_running_models "$pool" ""); do
    [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
  done
done
for m in $(get_pool_running_models "Pool-B" "Holo_31"); do
  [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
done


# ==========================================
# ★ 核心池互斥逻辑 (Pool-B - 非独占)
# ==========================================
ALL_RUNNING=$(get_pool_running_models "Pool-ALL" "Holo_31")

if [ -n "$ALL_RUNNING" ]; then
    # 情况 1: 发现独占池 (Pool-ALL) 正在运行，清理全盘
    echo "[互斥] 发现 Pool-ALL 正在运行，正在停止并全盘清理..."
    for m in $ALL_RUNNING; do
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
    clean_gpu_pool "Pool-ALL"
else
    # 情况 2: 没有 ALL，只清理自己所在的池 (Pool-B)
    SAME_POOL_RUNNING=$(get_pool_running_models "Pool-B" "Holo_31")
    if [ -n "$SAME_POOL_RUNNING" ]; then
        echo "[互斥] 发现 Pool-B 内存在冲突模型，正在停止..."
        for m in $SAME_POOL_RUNNING; do
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
        done
    fi
    clean_gpu_pool "Pool-B"
fi

acquire_model_lock "Holo_31" || exit 1
clean_gpu_pool "Pool-B"
sleep 3
if ! wait_gpu_ready "2,3" 60; then
  log "[ERROR] GPU 2,3 未就绪"
  release_model_lock "Holo_31"
  exit 1
fi


# ==========================================

# 端口检查
for port in 8002 8010; do
  if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
    log "[ERROR] 端口 ${port} 已被占用"
    release_model_lock "Holo_31"
    exit 1
  fi
done

docker rm -f M02_Holo31 M02_Holo31_DP2 2>/dev/null || true

# ---------- 实例1 (GPU 2, 端口 8002) ----------
log "启动实例1: M02_Holo31 (GPU 2, 端口 8002)"
docker run -d \
  --name M02_Holo31 \
  --restart unless-stopped \
  --gpus '"device=2"' \
  --shm-size 16g \
  -p 8002:8002 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  ghcr.io/ggml-org/llama.cpp:server-cuda13 \
  -m "/models/Holo_3,1/q4_k_m.gguf" \
  --mmproj "/models/Holo_3,1/mmproj.f16.gguf" \
  --host 0.0.0.0 \
      --metrics \
    --slots \
    --port 8002 \
  --n-gpu-layers 999 \
  --ctx-size 65536 \
  --threads 8 \
  --threads-batch 8 \
  --ubatch-size 512 \
  --flash-attn on \
  --cache-type-k q4_0 \
  --cache-type-v q4_0 \

# ---------- 实例2 (GPU 3, 端口 8010) ----------
log "启动实例2: M02_Holo31_DP2 (GPU 3, 端口 8010)"
docker run -d \
  --name M02_Holo31_DP2 \
  --restart unless-stopped \
  --gpus '"device=3"' \
  --shm-size 16g \
  -p 8010:8010 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  ghcr.io/ggml-org/llama.cpp:server-cuda13 \
  -m "/models/Holo_3,1/q4_k_m.gguf" \
  --mmproj "/models/Holo_3,1/mmproj.f16.gguf" \
  --host 0.0.0.0 \
  --port 8010 \
  --n-gpu-layers 999 \
  --ctx-size 65536 \
  --threads 8 \
  --threads-batch 8 \
  --ubatch-size 512 \
  --flash-attn on \
  --cache-type-k q4_0 \
  --cache-type-v q4_0 \

# 写 state.json 初始状态
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 -c "
import json,datetime
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['Holo_31']={'status':'starting','container':'M02_Holo31','port':8002,'gpu':'2,3','pool':'Pool-B','engine':'llama.cpp','updated_at':datetime.datetime.now().isoformat(),'progress':0}
json.dump(s,open(sf,'w'),indent=2)
"

# 健康检查
log "等待健康检查 (端口 8002)"
for i in $(seq 1 90); do
  sleep 10
  if curl -s --max-time 3 http://127.0.0.1:8002/v1/models 2>/dev/null | grep -q "q4_k_m"; then
    log "✅ 服务就绪（$((i*10)) 秒）"
    python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['Holo_31']['status']='running'
s['running_models']['Holo_31']['progress']=100
json.dump(s,open(sf,'w'),indent=2)
"
    release_model_lock "Holo_31"
    log "========== ✅ Holo_31 启动完成 =========="
    exit 0
  fi
  [ $((i % 6)) -eq 0 ] && log "健康检查中... ($((i*10)) 秒)"
done

log "健康检查超时"
docker stop M02_Holo31 M02_Holo31_DP2 2>/dev/null || true
docker rm M02_Holo31 M02_Holo31_DP2 2>/dev/null || true
release_model_lock "Holo_31"
exit 1
