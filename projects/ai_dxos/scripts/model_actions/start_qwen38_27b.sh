#!/bin/bash
set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh
LOG="/ai/ai_dxos/logs/model_actions.log"
log() { echo "[$(date '+%F %T')] [start_qwen38_27b] $*" | tee -a "$LOG"; }

log "========== 启动 qwen38_27b (多模态保命版) =========="

# 互斥清理
for target_pool in Pool-ALL Pool-A Pool-B; do
    for m in $(get_pool_running_models "$target_pool" "qwen38_27b"); do
        /ai/ai_dxos/scripts/model_actions/stop_${m}.sh || true
    done
done
clean_gpu_pool "Pool-ALL"

acquire_model_lock "qwen38_27b" || exit 1
clean_gpu_pool "Pool-ALL"
sleep 3
if ! wait_gpu_ready "0,1,2,3" 60; then
  echo "[ERROR] GPU 0,1,2,3 未就绪"
  exit 1
fi
sleep 3
docker rm -f M07_38_27B 2>/dev/null || true
log "启动 SGLang 容器"

# 核心修正：保留多模态，但强制走 CPU 内存传输，防止显存死锁
docker run -d --name M07_38_27B --restart unless-stopped --gpus all --shm-size 32g \
  -e CUDA_VISIBLE_DEVICES=0,1,2,3 -e NCCL_P2P_DISABLE=1 -e NCCL_IB_DISABLE=1 \
  -p 8008:8008 -v /ai/ai_dxos/volumes/models:/models:ro \
  --entrypoint python3 lmsysorg/sglang:v0.5.17-cu130-runtime \
  -m sglang.launch_server --model-path /models/Qwen3.8-27B \
  --served-model-name qwen38_27b --port 8008 --host 0.0.0.0 --tp 4 \
  --trust-remote-code --mem-fraction-static 0.83 --context-length 262144 \
  --max-running-requests 8 --disable-custom-all-reduce --cuda-graph-max-bs 8 \
  --disable-prefill-cuda-graph \
  --mm-feature-transport cpu \
  --schedule-policy lpm \
  --enable-dynamic-chunking \
  --chunked-prefill-size 8192 \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_coder \
  --speculative-algorithm nextn \
  --speculative-num-steps 3 \
  --speculative-num-draft-tokens 3 \
  --speculative-eagle-topk 1 \
  --default-chat-template-kwargs '{"enable_thinking": true, "reasoning_effort": "low"}'

chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 -c "
import json,datetime
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['qwen38_27b']={'status':'starting','container':'M07_38_27B','port':8008,'gpu':'0,1,2,3','pool':'Pool-ALL','engine':'sglang','updated_at':datetime.datetime.now().isoformat(),'progress':0}
json.dump(s,open(sf,'w'),indent=2)
"

log "等待健康检查"
for i in $(seq 1 90); do
  sleep 10
  if curl -s --max-time 3 http://127.0.0.1:8008/v1/models 2>/dev/null | grep -q qwen38_27b; then
    log "✅ 服务就绪（$((i*10)) 秒）"
    python3 -c "
import json
sf='/ai/ai_dxos/configs/state/state.json'
s=json.load(open(sf))
s['running_models']['qwen38_27b']['status']='running'
s['running_models']['qwen38_27b']['progress']=100
json.dump(s,open(sf,'w'),indent=2)
"
    release_model_lock "qwen38_27b"
    log "========== ✅ qwen38_27b 启动完成 =========="
    exit 0
  fi
  [ $((i % 6)) -eq 0 ] && log "健康检查中... ($((i*10)) 秒)"
done
log "健康检查超时"
docker stop M07_38_27B 2>/dev/null || true
docker rm M07_38_27B 2>/dev/null || true
release_model_lock "qwen38_27b"
exit 1
