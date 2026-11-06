#!/bin/bash
set -euo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

MODEL_NAME="deepseek_V4"
PORT=8022
PID_FILE="/ai/ai_dxos/scripts/model_actions/M18.pid"
LOG_FILE="/ai/ai_dxos/logs/model_actions.log"

echo "[$(date '+%F %T')] [stop_${MODEL_NAME}] ========== 停止 $MODEL_NAME ==========" | tee -a "$LOG_FILE"

if ! acquire_model_lock "$MODEL_NAME"; then
    echo "[$(date '+%F %T')] 获取锁失败" | tee -a "$LOG_FILE"
    exit 1
fi

# 1. 尝试使用官方命令停止
cd /ai/ai_dxos/Strata
./bin/strata launch --stop 2>/dev/null || true

# 2. 清理 PID 文件及进程
if [ -f "$PID_FILE" ]; then
    kill $(cat "$PID_FILE") 2>/dev/null || true
    rm -f "$PID_FILE"
fi

# 3. 兜底杀进程树
pkill -9 -f "strata launch.*--api-port $PORT" 2>/dev/null || true
sleep 2

# 清理显存
clean_gpu_pool "Pool-B"

# 4. 清理 state
chattr -i /ai/ai_dxos/configs/state/state.json 2>/dev/null || true
python3 -c "
import json, os
sf = '/ai/ai_dxos/configs/state/state.json'
if os.path.exists(sf):
    with open(sf, 'r') as f: s = json.load(f)
    s.get('running_models', {}).pop('${MODEL_NAME}', None)
    with open(sf, 'w') as f: json.dump(s, f, indent=2)
"

release_model_lock "$MODEL_NAME"
echo "[$(date '+%F %T')] [stop_${MODEL_NAME}] ========== 停止完成 ==========" | tee -a "$LOG_FILE"
