#!/bin/bash
# /ai/ai_dxos/scripts/common/lock.sh - 完整版
set -euo pipefail
source /ai/ai_dxos/configs/paths.conf

STATE_LOCK="${STATE_LOCK:-/run/dxos_state.lock}"
STATE_FILE="${STATE_FILE:-/ai/ai_dxos/configs/state/state.json}"
STATE_HISTORY_DIR="${STATE_HISTORY:-/ai/ai_dxos/configs/state/history}"
STATE_TMP_FILE="${STATE_TMP:-/ai/ai_dxos/configs/state/state.json.tmp}"
RESERVATION_DIR="${RESERVATION_DIR:-/ai/ai_dxos/configs/state/reservations}"
LOCK_TIMEOUT=10
MAX_HISTORY=20

init_state_system() {
    mkdir -p "$STATE_HISTORY_DIR" 2>/dev/null || true
    mkdir -p "$RESERVATION_DIR" 2>/dev/null || true
    if [ ! -f "$STATE_FILE" ]; then
        echo '{"version":"6.0","schema":2,"running_models":{},"gpu_lock":{},"recovery_queue":[]}' > "$STATE_FILE"
    fi
}

with_state_lock() {
    (
        if ! flock -w "$LOCK_TIMEOUT" 200; then
            echo "[ERROR] 获取 state 锁超时 (${LOCK_TIMEOUT}s)" >&2
            return 1
        fi
        "$@"
    ) 200>"$STATE_LOCK"
}

update_state_safe() {
    local content="$1"
    local tmp_file="${STATE_TMP_FILE}"
    echo "$content" > "$tmp_file"
    sync "$tmp_file" 2>/dev/null || true
    mv "$tmp_file" "$STATE_FILE"
    local history_file="${STATE_HISTORY_DIR}/state.$(date +%Y%m%d_%H%M%S).json"
    echo "$content" > "$history_file"
    cd "$STATE_HISTORY_DIR" 2>/dev/null && {
        ls -t state.*.json 2>/dev/null | tail -n +$((MAX_HISTORY + 1)) | xargs rm -f 2>/dev/null || true
    }
}

create_reservation() {
    local operation_id="$1"
    local target_model="$2"
    local pool="$3"
    local gpu_ids="$4"
    local conflicts="$5"
    local reservation_file="${RESERVATION_DIR}/${operation_id}.json"
    cat > "$reservation_file" <<EOR
{
  "operation_id": "$operation_id",
  "target": "$target_model",
  "pool": "$pool",
  "reserved_gpus": "$gpu_ids",
  "conflicts": "$conflicts",
  "state": "PLANNED",
  "created_at": "$(date -Iseconds)"
}
EOR
    sync "$reservation_file" 2>/dev/null || true
}

release_reservation() {
    local operation_id="$1"
    rm -f "${RESERVATION_DIR}/${operation_id}.json" 2>/dev/null || true
}

get_active_reservations() {
    ls -1 "${RESERVATION_DIR}"/*.json 2>/dev/null | while read -r f; do
        cat "$f"
    done | python3 -c "
import json, sys
reservations = []
for line in sys.stdin:
    try:
        if line.strip():
            reservations.append(json.loads(line))
    except:
        pass
print(json.dumps(reservations))
" 2>/dev/null || echo "[]"
}

get_model_status() {
    local model=$1
    python3 -c "
import json
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    m = data.get('running_models', {}).get('$model', {})
    print(m.get('status', 'stopped'))
except:
    print('stopped')
" 2>/dev/null
}

get_running_models() {
    python3 -c "
import json
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    models = []
    for model, info in data.get('running_models', {}).items():
        if info.get('status') in ['running', 'starting', 'loading']:
            models.append(model)
    print(' '.join(models))
except:
    print('')
" 2>/dev/null
}

acquire_global_lock() {
    local timeout=30
    exec {SCHEDULER_FD}>"$SCHEDULER_LOCK"
    if ! flock -w "$timeout" "$SCHEDULER_FD"; then
        exec {SCHEDULER_FD}>&-
        echo "[ERROR] 获取全局调度锁超时 (${timeout}s)" >&2
        return 1
    fi
    return 0
}

release_global_lock() {
    if [ -n "${SCHEDULER_FD:-}" ]; then
        exec {SCHEDULER_FD}>&-
    fi
}

acquire_model_lock() {
    local model=$1
    local container_name=$(grep "^${model}|" "$MODELS_CONF_FILE" | cut -d'|' -f2 | head -1)
    if [ -z "$container_name" ]; then
        echo "[ERROR] 未找到模型 ${model} 的容器名" >&2
        return 1
    fi
    local lock_file="${MODEL_LOCK_DIR}/${container_name}.lock"
    local timeout=5
    mkdir -p "$MODEL_LOCK_DIR"
    
    # 使用动态文件描述符持久持锁
    exec {MODEL_FD}>"$lock_file"
    if ! flock -w "$timeout" "$MODEL_FD"; then
        exec {MODEL_FD}>&-
        echo "[ERROR] 模型 ${model} 正被其他操作占用，超时 ${timeout}s" >&2
        return 1
    fi
    eval "LOCK_FD_${container_name}=$MODEL_FD"
    return 0
}

release_model_lock() {
    local model=$1
    local container_name=$(grep "^${model}|" "$MODELS_CONF_FILE" | cut -d'|' -f2 | head -1)
    [ -z "$container_name" ] && return 0
    
    eval "local fd=\$LOCK_FD_${container_name}"
    if [ -n "$fd" ]; then
        exec {fd}>&-
    fi
}

validate_and_recover_state() {
    if [ -f "$STATE_FILE" ]; then
        if ! python3 -c "import json; json.load(open('$STATE_FILE'))" 2>/dev/null; then
            echo "[WARN] state.json 损坏，尝试从历史版本恢复" >&2
            local latest_backup=$(ls -t ${STATE_HISTORY_DIR}/state.*.json 2>/dev/null | head -1)
            if [ -n "$latest_backup" ] && [ -f "$latest_backup" ]; then
                cp "$latest_backup" "$STATE_FILE"
                echo "[INFO] 已从 $latest_backup 恢复" >&2
                return 0
            else
                echo "[ERROR] 无可用历史版本，创建初始 state" >&2
                echo '{"version":"6.0","schema":2,"running_models":{},"gpu_lock":{},"recovery_queue":[]}' > "$STATE_FILE"
                return 1
            fi
        fi
    else
        echo '{"version":"6.0","schema":2,"running_models":{},"gpu_lock":{},"recovery_queue":[]}' > "$STATE_FILE"
    fi
    return 0
}

init_state_system
validate_and_recover_state
