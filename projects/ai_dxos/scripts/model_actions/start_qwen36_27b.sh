#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [start_qwen36_27b] $*" | tee -a "$LOG"; }
log "========== 启动 qwen36_27b =========="

for pool in Pool-A Pool-B; do
  for m in $(get_pool_running_models "$pool" ""); do
    [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
  done
done
for m in $(get_pool_running_models "Pool-ALL" "qwen36_27b"); do
  [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ] && /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
done


# ==========================================
# ★ 核心池互斥逻辑 (Pool-ALL - 独占)
# ==========================================
echo "[互斥] 正在清理所有冲突池 (Pool-ALL/A/B) 的模型..."
for target_pool in Pool-ALL Pool-A Pool-B; do
    for m in $(get_pool_running_models "$target_pool" "qwen36_27b"); do
        echo "[互斥] 停止冲突模型: $m (所在池: $target_pool)"
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
done
clean_gpu_pool "Pool-ALL"

acquire_model_lock "qwen36_27b" || exit 1
clean_gpu_pool "Pool-ALL"
sleep 3
if ! wait_gpu_ready "0,1,2,3" 60; then
  echo "[ERROR] GPU 0,1,2,3 未就绪"
  exit 1
fi
sleep 3
docker rm -f M12_36_27B 2>/dev/null || true
log "启动 SGLang 容器"
docker run -d --name M12_36_27B --restart unless-stopped --gpus all --shm-size 32g \
  -e CUDA_VISIBLE_DEVICES=0,1,2,3 -e NCCL_P2P_DISABLE=1 -e NCCL_IB_DISABLE=1 \
  -p 8016:8016 -v /ai/ai_dxos/volumes/models:/models:ro \
  --entrypoint python3 lmsysorg/sglang:v0.5.17-cu130-runtime \
  -m sglang.launch_server --model-path /models/Qwen3.6-27B \
  --served-model-name qwen36_27b --port 8016 --host 0.0.0.0 --tp 4 \
  --trust-remote-code \
    --enable-metrics \ --mem-fraction-static 0.75 --context-length 262144 \
  --max-running-requests 8 --disable-custom-all-reduce --cuda-graph-max-bs 4 \
  --mm-feature-transport cpu \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_coder \
  --default-chat-template-kwargs '{"enable_thinking": false}'

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true

python3 -c "
import json,datetime
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['qwen36_27b']={'status':'starting','container':'M12_36_27B','port':8016,'gpu':'0,1,2,3','pool':'Pool-ALL','engine':'sglang','updated_at':datetime.datetime.now().isoformat(),'progress':0}
json.dump(s,open(sf,'w'),indent=2)
"
log "等待健康检查"
for i in $(seq 1 90); do
  sleep 10
  if curl -s --max-time 3 http://127.0.0.1:8016/v1/models 2>/dev/null | grep -q qwen36_27b; then
    log "✅ 服务就绪（$((i*10)) 秒）"
    python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['qwen36_27b']['status']='running'
s['running_models']['qwen36_27b']['progress']=100
json.dump(s,open(sf,'w'),indent=2)
"
    release_model_lock "qwen36_27b"
    log "========== ✅ qwen36_27b 启动完成 =========="
    exit 0
  fi
  [ $((i % 6)) -eq 0 ] && log "健康检查中... ($((i*10)) 秒)"
done
log "健康检查超时"
docker stop M12_36_27B 2>/dev/null || true
docker rm M12_36_27B 2>/dev/null || true
release_model_lock "qwen36_27b"
exit 1
