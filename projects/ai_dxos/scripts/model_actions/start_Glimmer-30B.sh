#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [start_Glimmer-30B] $*" | tee -a "$LOG"; }
log "========== 启动 Glimmer-30B =========="

# 池互斥：停 Pool-A/Pool-B/Pool-ALL 的其它模型
for pool in Pool-A Pool-B; do
  for m in $(get_pool_running_models "$pool" ""); do
    [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
  done
done
for m in $(get_pool_running_models "Pool-ALL" "Glimmer-30B"); do
  [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
done


# ==========================================
# ★ 核心池互斥逻辑 (Pool-ALL - 独占)
# ==========================================
echo "[互斥] 正在清理所有冲突池 (Pool-ALL/A/B) 的模型..."
for target_pool in Pool-ALL Pool-A Pool-B; do
    for m in $(get_pool_running_models "$target_pool" "Glimmer-30B"); do
        echo "[互斥] 停止冲突模型: $m (所在池: $target_pool)"
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
done
clean_gpu_pool "Pool-ALL"

acquire_model_lock "Glimmer-30B" || exit 1
clean_gpu_pool "Pool-ALL"
sleep 3
if ! wait_gpu_ready "0,1,2,3" 60; then
  log "[ERROR] GPU 0,1,2,3 未就绪"
  release_model_lock "Glimmer-30B"
  exit 1
fi
sleep 3

# 端口检查
if ss -tlnp 2>/dev/null | grep -q ":8018 "; then
    log "[ERROR] 端口 8018 已被占用"
    release_model_lock "Glimmer-30B"
    exit 1
fi

docker rm -f M14--Glimmer-30B 2>/dev/null || true
log "启动 SGLang 容器（dev-muse-glimmer 专用镜像）"
docker run -d --name M14--Glimmer-30B --restart unless-stopped --gpus all --shm-size 32g \
  -e CUDA_VISIBLE_DEVICES=0,1,2,3 -e NCCL_P2P_DISABLE=1 -e NCCL_IB_DISABLE=1 \
  -p 8018:8018 -v /ai/ai_dxos/volumes/models:/models:ro \
  --entrypoint python3 lmsysorg/sglang:dev-muse-glimmer \
  -m sglang.launch_server --model-path /models/Muse-Glimmer-30B \
  --served-model-name Glimmer-30B --port 8018 --host 0.0.0.0 --tp 4 \
  --trust-remote-code --mem-fraction-static 0.85 --context-length 131072 \
  --max-running-requests 4 --disable-custom-all-reduce --cuda-graph-max-bs 2 \
  --mm-feature-transport cpu \
  --reasoning-parser muse \
  --tool-call-parser muse

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true

python3 -c "
import json,datetime
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['Glimmer-30B']={'status':'starting','container':'M14--Glimmer-30B','port':8018,'gpu':'0,1,2,3','pool':'Pool-ALL','engine':'sglang','updated_at':datetime.datetime.now().isoformat(),'progress':0}
json.dump(s,open(sf,'w'),indent=2)
"

log "等待健康检查"
for i in $(seq 1 90); do
  sleep 10
  if curl -s --max-time 3 http://127.0.0.1:8018/v1/models 2>/dev/null | grep -q "Glimmer-30B"; then
    log "✅ 服务就绪（$((i*10)) 秒）"
    python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['Glimmer-30B']['status']='running'
s['running_models']['Glimmer-30B']['progress']=100
json.dump(s,open(sf,'w'),indent=2)
"
    release_model_lock "Glimmer-30B"
    log "========== ✅ Glimmer-30B 启动完成 =========="
    exit 0
  fi
  [ $((i % 6)) -eq 0 ] && log "健康检查中... ($((i*10)) 秒)"
done

log "健康检查超时"
docker stop M14--Glimmer-30B 2>/dev/null || true
docker rm M14--Glimmer-30B 2>/dev/null || true
release_model_lock "Glimmer-30B"
exit 1
