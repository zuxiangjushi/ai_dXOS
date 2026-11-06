#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [start_MiniMax_H3] $*" | tee -a "${LOG}"; }

log "===============启动 MiniMax_H3 =============="

# 1. 池互斥
for pool in Pool-A; do
    for m in $(get_pool_running_models "$pool" ""); do     
        [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
    done
done

# 2. 获取锁、清理显存、等待就绪

# ==========================================


# ==========================================
# ★ 核心池互斥逻辑 (Pool-A - 非独占)
# ==========================================
ALL_RUNNING=$(get_pool_running_models "Pool-ALL" "MiniMax_H3")

if [ -n "$ALL_RUNNING" ]; then
    # 情况 1: 发现独占池 (Pool-ALL) 正在运行，清理全盘
    echo "[互斥] 发现 Pool-ALL 正在运行，正在停止并全盘清理..."
    for m in $ALL_RUNNING; do
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
    clean_gpu_pool "Pool-ALL"
else
    # 情况 2: 没有 ALL，只清理自己所在的池 (Pool-A)
    SAME_POOL_RUNNING=$(get_pool_running_models "Pool-A" "MiniMax_H3")
    if [ -n "$SAME_POOL_RUNNING" ]; then
        echo "[互斥] 发现 Pool-A 内存在冲突模型，正在停止..."
        for m in $SAME_POOL_RUNNING; do
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
        done
    fi
    clean_gpu_pool "Pool-A"
fi

acquire_model_lock "MiniMax_H3" || exit 1
clean_gpu_pool "Pool-A"
sleep 3
if ! wait_gpu_ready "0,1" 60; then
    log "[ERROR] GPU 0,1 未就绪"
    release_model_lock "MiniMax_H3"
    exit 1
fi

# 3. 端口检查
if ss -tlnp 2>/dev/null | grep -q ":8001"; then
    log "端口 8001 已被占用"
    release_model_lock "MiniMax_H3"
    exit 1
fi
docker rm -f M01_H3 2>/dev/null || true

# 4. 启动 ComfyUI 容器
log "启动 ComfyUI 容器"
docker run -d --name M01_H3 \
  --restart unless-stopped \
  --gpus '"device=0,1"' \
  --shm-size 16g \
  -e CUDA_VISIBLE_DEVICES=0,1 \
  -p 8001:8188 \
  -v /ai/ai_dxos/volumes/comfyui/output:/workspace/ComfyUI/output \
  -v /ai/ai_dxos/volumes/comfyui/input:/workspace/ComfyUI/input \
  -v /ai/ai_dxos/volumes/comfyui/custom_nodes:/workspace/ComfyUI/custom_nodes \
  -v /ai/ai_dxos/volumes/models/MiniMax_H3:/workspace/ComfyUI/models/MiniMax_H3:ro \
  yanwk/comfyui-boot:cu126-slim

# 5. 写入状态
python3 -c "
import json, datetime
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s.setdefault('running_models', {})['MiniMax_H3'] = {
    'status': 'starting',
    'container': 'M01_H3',
    'port': 8001,
    'gpu': '0,1',
    'pool': 'Pool-A',
    'engine': 'comfyui',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 0
}
json.dump(s, open(sf,'w'), indent=2)
"
# 6. 健康检查
log "等待健康检查"
for i in $(seq 1 90); do
    sleep 5
    if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 -m 5 "http://127.0.0.1:8001/" 2>/dev/null | grep -q "200"; then
        log "服务就绪（$((i*5))秒）"
        python3 -c "
import json, datetime
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s.setdefault('running_models', {})['MiniMax_H3'] = {
    'status': 'running',
    'container': 'M01_H3',
    'port': 8001,
    'gpu': '0,1',
    'pool': 'Pool-A',
    'engine': 'comfyui',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}
json.dump(s, open(sf,'w'), indent=2)
"
        release_model_lock "MiniMax_H3"
        log "=========== MiniMax_H3 启动完成 ==========="
        exit 0
    fi
    [ $((i%6)) -eq 0 ] && log "健康检查中...（$((i*5))秒）"
done

log "健康检查超时"
docker stop M01_H3 2>/dev/null || true
docker rm M01_H3 2>/dev/null || true
release_model_lock "MiniMax_H3"
exit 1
