#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [start_gemma_4_31B] $*" | tee -a "$LOG"; }
log "========== 启动 gemma_4_31B =========="

for pool in Pool-A Pool-B; do
  for m in $(get_pool_running_models "$pool" ""); do
    [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
  done
done
for m in $(get_pool_running_models "Pool-ALL" "gemma_4_31B"); do
  [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
done


# ==========================================
# ★ 核心池互斥逻辑 (Pool-ALL - 独占)
# ==========================================
echo "[互斥] 正在清理所有冲突池 (Pool-ALL/A/B) 的模型..."
for target_pool in Pool-ALL Pool-A Pool-B; do
    for m in $(get_pool_running_models "$target_pool" "gemma_4_31B"); do
        echo "[互斥] 停止冲突模型: $m (所在池: $target_pool)"
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
done
clean_gpu_pool "Pool-ALL"

acquire_model_lock "gemma_4_31B" || exit 1
clean_gpu_pool "Pool-ALL"
sleep 3
if ! wait_gpu_ready "0,1,2,3" 60; then
  echo "[ERROR] GPU 0,1,2,3 未就绪"
  exit 1
fi
sleep 3
docker rm -f M13_gemma_4_31B 2>/dev/null || true
log "启动 SGLang 容器"
docker run -d --name M13_gemma_4_31B --restart unless-stopped --gpus all --shm-size 32g \
  -e CUDA_VISIBLE_DEVICES=0,1,2,3 -e NCCL_P2P_DISABLE=1 -e NCCL_IB_DISABLE=1 \
  -p 8017:8017 -v /ai/ai_dxos/volumes/models:/models:ro \
  --entrypoint python3 lmsysorg/sglang:v0.5.17-cu130-runtime \
  -m sglang.launch_server --model-path /models/Gemma-4-31B-it \
  --served-model-name gemma_4_31B --port 8017 --host 0.0.0.0 --tp 4 \
  --trust-remote-code --mem-fraction-static 0.85 --context-length 16384 \
  --max-running-requests 4 --disable-custom-all-reduce --cuda-graph-max-bs 2 \
  --mm-feature-transport cpu \
  --reasoning-parser gemma4 \
  --tool-call-parser gemma4 \
  --default-chat-template-kwargs '{"enable_thinking": false}'

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true

python3 -c "
import json,datetime
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['gemma_4_31B']={'status':'starting','container':'M13_gemma_4_31B','port':8017,'gpu':'0,1,2,3','pool':'Pool-ALL','engine':'sglang','updated_at':datetime.datetime.now().isoformat(),'progress':0}
json.dump(s,open(sf,'w'),indent=2)
"
log "等待健康检查"
for i in $(seq 1 90); do
  sleep 10
  if curl -s --max-time 3 http://127.0.0.1:8017/v1/models 2>/dev/null | grep -q gemma_4_31B; then
    log "✅ 服务就绪（$((i*10)) 秒）"
    python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['gemma_4_31B']['status']='running'
s['running_models']['gemma_4_31B']['progress']=100
json.dump(s,open(sf,'w'),indent=2)
"
    release_model_lock "gemma_4_31B"
    log "========== ✅ gemma_4_31B 启动完成 =========="
    exit 0
  fi
  [ $((i % 6)) -eq 0 ] && log "健康检查中... ($((i*10)) 秒)"
done
log "健康检查超时"
docker stop M13_gemma_4_31B 2>/dev/null || true
docker rm M13_gemma_4_31B 2>/dev/null || true
release_model_lock "gemma_4_31B"
exit 1
