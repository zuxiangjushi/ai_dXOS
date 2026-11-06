#!/bin/bash
# /ai/ai_dxos/scripts/common/state.sh
# 统一状态管理 - state.json 的唯一操作入口

set -euo pipefail

STATE_FILE="/ai/ai_dxos/configs/state/state.json"
STATE_TMP="/ai/ai_dxos/configs/state/state.json.tmp"

state_init() {
    mkdir -p "$(dirname "$STATE_FILE")"
    if [ ! -f "$STATE_FILE" ]; then
        cat > "$STATE_FILE" << 'INITEOF'
{
  "version": "6.0",
  "schema": 2,
  "running_models": {},
  "gpu_lock": {},
  "recovery_queue": []
}
INITEOF
    fi
}

state_write() {
    local content="$1"
    echo "$content" > "$STATE_TMP"
    sync "$STATE_TMP" 2>/dev/null || true
    mv "$STATE_TMP" "$STATE_FILE"
    sync "$(dirname "$STATE_FILE")" 2>/dev/null || true
}

state_set() {
    local model="$1"
    local status="$2"
    local container="$3"
    local port="$4"
    local gpu="$5"
    local pool="$6"
    local engine="$7"
    local progress="${8:-100}"

    python3 << PYEOF
import json
import datetime
import os

state_file = "$STATE_FILE"
with open(state_file, 'r') as f:
    state = json.load(f)

if 'running_models' not in state:
    state['running_models'] = {}

state['running_models']['$model'] = {
    'status': '$status',
    'container': '$container',
    'port': $port,
    'gpu': '$gpu',
    'pool': '$pool',
    'engine': '$engine',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': $progress
}

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF
}

state_remove() {
    local model="$1"
    python3 << PYEOF
import json
import os

state_file = "$STATE_FILE"
if not os.path.exists(state_file):
    exit(0)

with open(state_file, 'r') as f:
    state = json.load(f)

if 'running_models' in state and '$model' in state['running_models']:
    del state['running_models']['$model']

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF
}

state_get() {
    local model="$1"
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

state_list_running() {
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

state_reconcile() {
    echo "[INFO] 开始状态对账..."
    STATE_MODELS=$(state_list_running)
    DOCKER_CONTAINERS=$(docker ps --format "{{.Names}}" | grep -E "^M[0-9]{2}" | tr '\n' ' ')
    echo "[INFO] State 中的模型: $STATE_MODELS"
    echo "[INFO] Docker 中的容器: $DOCKER_CONTAINERS"
    for model in $STATE_MODELS; do
        container=$(python3 -c "
import json
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    print(data.get('running_models', {}).get('$model', {}).get('container', ''))
except:
    print('')
" 2>/dev/null)
        if [ -n "$container" ]; then
            if ! docker ps --format "{{.Names}}" | grep -q "^${container}$"; then
                echo "[WARN] 模型 $model 在 state 中为运行状态，但容器 $container 不存在"
                state_remove "$model"
            fi
        fi
    done
    for container in $DOCKER_CONTAINERS; do
        model=$(grep "$container" /ai/ai_dxos/configs/models.conf | cut -d'|' -f1 | head -1)
        if [ -n "$model" ]; then
            status=$(state_get "$model")
            if [ "$status" = "stopped" ]; then
                echo "[WARN] 容器 $container 正在运行，但 state 中 $model 为 stopped"
                info=$(grep "^${model}|" /ai/ai_dxos/configs/models.conf)
                port=$(echo "$info" | cut -d'|' -f4)
                gpu=$(echo "$info" | cut -d'|' -f5)
                pool=$(echo "$info" | cut -d'|' -f7)
                engine=$(echo "$info" | cut -d'|' -f6)
                state_set "$model" "running" "$container" "$port" "$gpu" "$pool" "$engine"
            fi
        fi
    done
    echo "[INFO] 状态对账完成"
}

state_init

# BASH_SOURCE guard (skip CLI when sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then

case "${1:-}" in
    set)
        shift
        state_set "$@"
        ;;
    remove)
        shift
        state_remove "$1"
        ;;
    get)
        shift
        state_get "$1"
        ;;
    list)
        state_list_running
        ;;
    reconcile)
        state_reconcile
        ;;
    *)
        echo "用法: $0 {set|remove|get|list|reconcile}"
        echo "  set <model> <status> <container> <port> <gpu> <pool> <engine> [progress]"
        echo "  remove <model>"
        echo "  get <model>"
        echo "  list"
        echo "  reconcile"
        exit 1
        ;;
esac

fi  # end of BASH_SOURCE guard
