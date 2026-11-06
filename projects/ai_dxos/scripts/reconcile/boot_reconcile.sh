#!/bin/bash
# /ai/ai_dxos/scripts/reconcile/boot_reconcile.sh
# 【R4】仅对账，不执行 restart

set -euo pipefail

source /ai/ai_dxos/configs/paths.conf
source /ai/ai_dxos/scripts/common/lock.sh

LOG_FILE="${LOG_DIR}/reconcile.log"
RECOVERY_QUEUE="${RECOVERY_QUEUE:-/run/dxos/recovery_queue}"

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*" | tee -a "$LOG_FILE"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

# 入队恢复
enqueue_recovery() {
    local model=$1
    with_state_lock bash -c "
        if [ ! -f \"$RECOVERY_QUEUE\" ]; then
            echo '[]' > \"$RECOVERY_QUEUE\"
        fi
        python3 -c '
import json
with open(\"$RECOVERY_QUEUE\") as f:
    queue = json.load(f)
if \"$model\" not in queue:
    queue.append(\"$model\")
with open(\"$RECOVERY_QUEUE\", \"w\") as f:
    json.dump(queue, f)
'
    "
}

# 主流程
log_info "===== 开机状态对账 (仅对账，不执行重启) ====="

# 1. 验证 state.json
validate_and_recover_state

# 2. GPU 锁对账
GPU_LOCKS=$(python3 -c "
import json
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    locks = data.get('gpu_lock', {})
    for gpu, info in locks.items():
        if info and isinstance(info, dict):
            print(f'{gpu}:{info.get(\"model\",\"unknown\")}:{info.get(\"pid\",0)}')
except:
    pass
" 2>/dev/null)

if [ -n "$GPU_LOCKS" ]; then
    echo "$GPU_LOCKS" | while IFS=':' read -r gpu model pid; do
        if nvidia-smi &>/dev/null; then
            real_pids=$(nvidia-smi --id="$gpu" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -d ' ')
            has_user_process=false
            for real_pid in $real_pids; do
                cmd=$(ps -p "$real_pid" -o comm= 2>/dev/null || echo "")
                if [[ "$cmd" != *"nvidia-persistenced"* ]] && [[ "$cmd" != *"nvidia-smi"* ]]; then
                    has_user_process=true
                    break
                fi
            done
            if [ "$has_user_process" = false ]; then
                log_warn "GPU $gpu 无真实计算进程，清除幽灵锁"
                # 通过 Python 更新 state
                python3 -c "
import json
with open('$STATE_FILE', 'r') as f:
    state = json.load(f)
if 'gpu_lock' in state and '$gpu' in state['gpu_lock']:
    state['gpu_lock']['$gpu'] = None
with open('$STATE_FILE', 'w') as f:
    json.dump(state, f, indent=2)
" 2>/dev/null || true
            fi
        fi
    done
fi

# 3. 检查运行状态与容器一致性
RUNNING_MODELS=$(python3 -c "
import json
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    models = []
    for model, info in data.get('running_models', {}).items():
        if info.get('status') in ['running', 'loading', 'starting']:
            models.append(model)
    print(' '.join(models))
except:
    print('')
" 2>/dev/null)

for model in $RUNNING_MODELS; do
    container=$(python3 -c "
import json
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    m = data.get('running_models', {}).get('$model', {})
    print(m.get('container', ''))
except:
    print('')
" 2>/dev/null)
    
    if [ -z "$container" ]; then
        log_warn "模型 $model 状态为运行但无容器，入队恢复"
        enqueue_recovery "$model"
        continue
    fi
    
    if docker ps -a --filter "name=^/${container}$" --format "{{.Names}}" | grep -q "^${container}$"; then
        if ! docker ps --filter "name=^/${container}$" --filter "status=running" --format "{{.Names}}" | grep -q "^${container}$"; then
            log_warn "模型 $model 容器已停止，入队恢复"
            enqueue_recovery "$model"
        fi
    else
        log_warn "模型 $model 容器不存在，入队恢复"
        enqueue_recovery "$model"
    fi
done

log_info "===== 开机对账完成 ====="
