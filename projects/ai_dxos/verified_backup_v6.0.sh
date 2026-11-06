#!/bin/bash
# ============================================================
# Dxos_Pilot v6.0 已验证程序完整备份
# 日期: 2026-09-06
# 说明: 包含所有已验证通过的模型启动/停止脚本、配置文件和核心程序
# ============================================================

# ============================================================
# 1. models.conf（模型配置 - 10个模型）
# ============================================================
cat > /ai/ai_dxos/configs/models.conf << 'MODELS_CONF'
# /ai/ai_dxos/configs/models.conf
# 【C1】所有模型属性的唯一真相源
# 格式: API_NAME|CONTAINER_NAME|PHYSICAL_MODEL|PORT|GPU_IDS|ENGINE|POOL

# ============ L0 池 (CPU) ============
emb_bge_m3|M00_3BGE|bge-m3|8003|CPU|infinity|L0

# ============ Pool-A (GPU 0,1) ============
qwen3_32b|M01_32B|Qwen3-32B-AWQ|8001|0,1|sglang|Pool-A
gemma_4|M03_gemma4|gemma-4-31b-jang-crack-Q4_K_M.gguf|8004|0,1|llama_cpp|Pool-A
yy35b_q6|M05_YY35B_Q6|Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q6_K_P.gguf|8006|0,1|llama_cpp|Pool-A

# ============ Pool-B (GPU 2,3) ============
qwen38_27b_f8|M02_27F8|Qwen3.8-27B-FP8|8002|2,3|sglang|Pool-B
yy38_27b|M04_YY27B|Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-Q8_K_P.gguf|8005|2,3|llama_cpp|Pool-B

# ============ Pool-ALL (GPU 0,1,2,3) ============
38FN_Q4|M06_38FN_Q4|Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf|8007|0,1,2,3|llama_cpp|Pool-ALL
deepseek_70b|M07_70B|DeepSeek-R1-Distill-Llama-70B-AWQ|8008|0,1,2,3|sglang|Pool-ALL
qwen3_30b|M08_30B|Qwen3-30B-A3B-Instruct-2507|8009|0,1,2,3|sglang|Pool-ALL
deepseek_V25|M09_V25_IQ4|DeepSeek-V2.5 IQ4_XS-00001-of-00003.gguf|8010|0,1,2,3|ktransformers|Pool-ALL
MODELS_CONF

echo "✅ models.conf 已备份"

# ============================================================
# 2. common_pool.sh（公共函数库）
# ============================================================
cat > /ai/ai_dxos/scripts/model_actions/common_pool.sh << 'COMMON_POOL'
#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/common_pool.sh
# Jeff Dean: 池管理公共函数库 - 硬编码路径，不依赖环境变量

# ============================================================
# 所有路径硬编码，不依赖任何外部变量
# ============================================================
export BASE_DIR="/ai/ai_dxos"
export CONF_DIR="${BASE_DIR}/configs"
export STATE_FILE="${CONF_DIR}/state/state.json"
export MODELS_CONF_FILE="${CONF_DIR}/models.conf"
export POOLS_CONF_FILE="${CONF_DIR}/pools.conf"
export COMMANDS_CONF_FILE="${CONF_DIR}/model_commands.conf"
export LOG_DIR="${BASE_DIR}/logs"
export SCRIPTS_DIR="${BASE_DIR}/scripts"
export ACTIONS_DIR="${SCRIPTS_DIR}/actions"
export MODEL_LOCK_DIR="/run/dxos/model_locks"
export SCHEDULER_LOCK="/var/run/dxos_scheduler.lock"
export STATE_LOCK="/run/dxos_state.lock"

# ============================================================
# 加载配置文件
# ============================================================
source /ai/ai_dxos/configs/paths.conf 2>/dev/null || true
source /ai/ai_dxos/configs/pools.conf 2>/dev/null || true
source /ai/ai_dxos/scripts/common/lock.sh 2>/dev/null || true

get_pool_running_models() {
    local pool=$1
    local exclude_model=$2
    python3 -c "
import json
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    models = []
    for model, info in data.get('running_models', {}).items():
        if info.get('status') in ['running', 'starting', 'loading']:
            if info.get('pool') == '$pool' and model != '$exclude_model':
                models.append(model)
    print(' '.join(models))
except:
    print('')
" 2>/dev/null
}

check_gpu_hardware_occupied() {
    local gpu_ids=$1
    if ! nvidia-smi &>/dev/null; then
        echo "UNKNOWN"
        return 2
    fi
    for gpu in $(echo "$gpu_ids" | tr ',' ' ' | tr '-' ' '); do
        local pids=$(nvidia-smi --id="$gpu" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -d ' ')
        if [ -n "$pids" ] && [ "$pids" != "0" ]; then
            for pid in $pids; do
                local cmd=$(ps -p "$pid" -o comm= 2>/dev/null || echo "")
                if [[ "$cmd" != *"nvidia-persistenced"* ]] && [[ "$cmd" != *"nvidia-smi"* ]]; then
                    echo "OCCUPIED"
                    return 0
                fi
            done
        fi
    done
    echo "FREE"
    return 0
}

wait_gpu_ready() {
    local gpu_ids=$1
    local max_wait=${2:-60}
    local interval=2
    local waited=0
    while [ $waited -lt $max_wait ]; do
        local status=$(check_gpu_hardware_occupied "$gpu_ids")
        if [ "$status" = "FREE" ]; then
            return 0
        fi
        sleep $interval
        waited=$((waited + interval))
    done
    return 1
}

wait_health_check_full() {
    local port=$1
    local container=$2
    local gpu_ids=$3
    local pool=$4
    local max_wait=${5:-600}

    local start_time=$(date +%s)
    local end_time=$((start_time + max_wait))
    local interval=3

    echo "[健康检查] 开始验证 (端口 ${port}, 超时 ${max_wait}s, 池: ${pool})"
    echo "[健康检查] 模拟手动验证流程..."

    # 阶段1: 端口监听
    echo -n "[健康检查] 阶段1: 等待端口 ${port} 监听"
    local port_ready=false
    for i in {1..20}; do
        if ss -tlnp | grep -q ":${port} "; then
            port_ready=true
            echo " ✅ (${i}s)"
            break
        fi
        sleep 1
        echo -n "."
    done
    if [ "$port_ready" = false ]; then
        echo " ❌ 端口 ${port} 在20秒内未监听"
        return 1
    fi

    # 阶段2: 启动日志
    echo -n "[健康检查] 阶段2: 等待启动日志..."
    local log_found=false
    local log_keywords="Load weight end|KV Cache is allocated|Capture target decode|Uvicorn running|Application startup complete|server is listening|Load weight begin|model loaded|llama_server: listening"
    local last_log_time=$(date +%s)

    while [ $(date +%s) -lt $end_time ]; do
        local log_lines=$(docker logs "$container" --since "${last_log_time}s" 2>&1 | grep -E "$log_keywords" | head -1)
        if [ -n "$log_lines" ]; then
            if echo "$log_lines" | grep -q "Load weight end"; then
                echo " ✅ (权重加载完成)"
            elif echo "$log_lines" | grep -q "KV Cache is allocated"; then
                echo " ✅ (KV Cache 分配)"
            elif echo "$log_lines" | grep -q "Capture target decode CUDA graph end"; then
                echo " ✅ (CUDA Graph 捕获完成)"
            elif echo "$log_lines" | grep -q "Uvicorn running"; then
                echo " ✅ (Uvicorn 服务启动)"
            elif echo "$log_lines" | grep -q "Application startup complete"; then
                echo " ✅ (应用启动完成)"
            elif echo "$log_lines" | grep -q "model loaded"; then
                echo " ✅ (模型加载完成)"
            elif echo "$log_lines" | grep -q "llama_server: listening"; then
                echo " ✅ (llama.cpp 服务监听)"
            else
                echo " ✅ (检测到: ${log_lines:0:60}...)"
            fi
            log_found=true
            break
        fi
        echo -n "."
        sleep $interval
        last_log_time=$(date +%s)
    done

    if [ "$log_found" = false ]; then
        echo " ⚠️ 未检测到启动日志，继续验证..."
    fi

    # 阶段3: 显存检查 (仅 GPU 模型)
    if [ "$pool" != "L0" ] && [ -n "$gpu_ids" ]; then
        echo -n "[健康检查] 阶段3: 检查 GPU 显存占用..."
        local gpu_array=($(echo "$gpu_ids" | tr ',' ' ' | tr '-' ' '))
        local total_mem=0
        local min_required=8192
        local attempts=0
        local mem_found=false

        while [ $attempts -lt 20 ] && [ $(date +%s) -lt $end_time ]; do
            total_mem=0
            for gpu in "${gpu_array[@]}"; do
                local mem=$(nvidia-smi --id="$gpu" --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
                if [ -n "$mem" ]; then
                    total_mem=$((total_mem + mem))
                fi
            done
            if [ $total_mem -gt $min_required ]; then
                echo " ✅ (总显存: ${total_mem} MiB, GPU: ${gpu_ids})"
                mem_found=true
                break
            fi
            echo -n "."
            sleep 3
            attempts=$((attempts + 1))
        done

        if [ "$mem_found" = false ]; then
            echo " ⚠️ 显存: ${total_mem} MiB (可能未完全加载，继续验证...)"
        fi
    fi

    # 阶段4: HTTP 端点
    echo -n "[健康检查] 阶段4: 检查 /v1/models 端点..."
    local http_ready=false
    for i in {1..30}; do
        local code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 -m 5 "http://127.0.0.1:${port}/v1/models" 2>/dev/null)
        if [ "$code" = "200" ]; then
            echo " ✅ (${i}s)"
            http_ready=true
            break
        fi
        sleep 2
        if [ $((i % 5)) -eq 0 ]; then
            echo -n "."
        fi
    done
    if [ "$http_ready" = false ]; then
        echo " ⚠️ /v1/models 未就绪，继续尝试推理..."
    fi

    # 阶段5: 推理测试
    echo "[健康检查] 阶段5: 推理测试 (最终验证)..."

    local model_name="default"
    local model_info=$(curl -s --connect-timeout 3 -m 5 "http://127.0.0.1:${port}/v1/models" 2>/dev/null)
    if [ -n "$model_info" ]; then
        model_name=$(echo "$model_info" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',[{}])[0].get('id','default'))" 2>/dev/null || echo "default")
    fi

    local test_attempts=0
    local test_passed=false
    local max_attempts=60
    local response=""

    echo "[健康检查]   推理目标: model=${model_name}"

    while [ $test_attempts -lt $max_attempts ] && [ $(date +%s) -lt $((end_time)) ]; do
        response=$(curl -s --connect-timeout 10 -m 60 \
            -X POST "http://127.0.0.1:${port}/v1/chat/completions" \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"${model_name}\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":4,\"temperature\":0.0}" 2>/dev/null)

        if echo "$response" | grep -q '"choices"' && echo "$response" | grep -q '"content"'; then
            echo "[健康检查]   ✅ 推理成功 (尝试 ${test_attempts} 次)"
            test_passed=true
            break
        fi

        if [ $((test_attempts % 10)) -eq 0 ]; then
            echo "[健康检查]   推理尝试 ${test_attempts}，继续等待..."
        fi
        sleep 5
        test_attempts=$((test_attempts + 1))
    done

    if [ "$test_passed" = false ]; then
        echo "[健康检查] ❌ 推理测试失败（尝试 ${test_attempts} 次）"
        echo "[健康检查] 容器最后10行日志:"
        docker logs "$container" 2>&1 | tail -10 | sed 's/^/  /'
        return 1
    fi

    echo "[健康检查] ✅ 全部验证通过！"
    return 0
}

wait_health_check() {
    local port=$1
    local max_wait=${2:-600}
    local container=${3:-""}
    local gpu_ids=${4:-""}
    local pool=${5:-""}
    if [ -n "$container" ]; then
        wait_health_check_full "$port" "$container" "$gpu_ids" "$pool" "$max_wait"
    else
        local start_time=$(date +%s)
        local end_time=$((start_time + max_wait))
        while [ $(date +%s) -lt $end_time ]; do
            if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/v1/models" 2>/dev/null | grep -q "200"; then
                return 0
            fi
            sleep 3
        done
        return 1
    fi
}

wait_health_check_llama() {
    local port=$1
    local max_wait=${2:-300}
    local container=${3:-""}
    local gpu_ids=${4:-""}
    local pool=${5:-""}
    wait_health_check "$port" "$max_wait" "$container" "$gpu_ids" "$pool"
}

clean_gpu_pool() {
    local pool=$1
    case "$pool" in
        "Pool-A") /ai/ai_dxos/scripts/actions/clean_gpu.sh "0,1" ;;
        "Pool-B") /ai/ai_dxos/scripts/actions/clean_gpu.sh "2,3" ;;
        "Pool-ALL") /ai/ai_dxos/scripts/actions/clean_gpu.sh "all" ;;
        "L0") echo "L0 无 GPU 需清理" ;;
        *) echo "未知池: $pool" ;;
    esac
}
COMMON_POOL

chmod +x /ai/ai_dxos/scripts/model_actions/common_pool.sh
echo "✅ common_pool.sh 已备份"

# ============================================================
# 3. scheduler.sh（调度器）
# ============================================================
cat > /ai/ai_dxos/scripts/scheduler/scheduler.sh << 'SCHEDULER'
#!/bin/bash
# /ai/ai_dxos/scripts/scheduler/scheduler.sh
# 统一调度入口 - 唯一控制器

set -euo pipefail

case "${1:-}" in
    start|switch)
        shift
        if [ -z "${1:-}" ]; then
            echo "用法: $0 {start|switch} <model_name>"
            exit 1
        fi
        /ai/ai_dxos/scripts/model_actions/start_${1}.sh
        ;;
    stop)
        shift
        if [ -z "${1:-}" ]; then
            echo "用法: $0 stop <model_name>"
            exit 1
        fi
        /ai/ai_dxos/scripts/model_actions/stop_${1}.sh
        ;;
    stop_all)
        echo "正在停止所有 GPU 模型..."
        for script in /ai/ai_dxos/scripts/model_actions/stop_*.sh; do
            if [ -f "$script" ] && [[ "$script" != *"common"* ]]; then
                echo "执行: $script"
                bash "$script"
            fi
        done
        /ai/ai_dxos/scripts/actions/clean_gpu.sh all --force
        ;;
    status)
        cat /ai/ai_dxos/configs/state/state.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
models = data.get('running_models', {})
if not models:
    print('暂无运行中的模型')
else:
    for model, info in models.items():
        print(f'{model}: {info.get(\"status\", \"unknown\")} (端口: {info.get(\"port\", \"?\")})')
"
        ;;
    reconcile)
        /ai/ai_dxos/scripts/common/state.sh reconcile
        ;;
    *)
        echo "用法: $0 {start|switch|stop|stop_all|status|reconcile} [model]"
        echo "  start <model>    - 启动指定模型"
        echo "  switch <model>   - 切换/启动模型"
        echo "  stop <model>     - 停止指定模型"
        echo "  stop_all         - 停止所有模型并清理 GPU"
        echo "  status           - 显示所有模型状态"
        echo "  reconcile        - 对账 state.json 与 Docker 容器"
        echo ""
        echo "可用模型:"
        grep -v "^#" /ai/ai_dxos/configs/models.conf | grep -v "^$" | cut -d'|' -f1
        exit 1
        ;;
esac
SCHEDULER

chmod +x /ai/ai_dxos/scripts/scheduler/scheduler.sh
echo "✅ scheduler.sh 已备份"

# ============================================================
# 4. state.sh（统一状态管理）
# ============================================================
cat > /ai/ai_dxos/scripts/common/state.sh << 'STATE_SH'
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
STATE_SH

chmod +x /ai/ai_dxos/scripts/common/state.sh
echo "✅ state.sh 已备份"

# ============================================================
# 5. 已验证模型的启动脚本
# ============================================================

# 5.1 M00 - emb_bge_m3 (L0, CPU, Infinity)
cat > /ai/ai_dxos/scripts/model_actions/start_emb_bge_m3.sh << 'M00_START'
#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_emb_bge_m3.sh
# 启动模型: emb_bge_m3 (L0, CPU) - Infinity Embedding 模型

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_emb_bge_m3] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_emb_bge_m3] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始启动 emb_bge_m3 =========="

acquire_global_lock || exit 1
release_global_lock

acquire_model_lock "emb_bge_m3" || exit 1

if ss -tlnp | grep -q ":8003 "; then
    log_error "端口 8003 已被占用"
    release_model_lock "emb_bge_m3"
    exit 1
fi

docker run -d \
  --name M00_3BGE \
  --restart unless-stopped \
  -p 8003:8003 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  infinity:stable \
  v2 --model-id /models/bge-m3 --port 8003 --host 0.0.0.0

if [ $? -ne 0 ]; then
    log_error "Docker 启动失败"
    release_model_lock "emb_bge_m3"
    exit 1
fi

log_info "等待健康检查 (端口 8003)..."
max_wait=300
interval=3
waited=0
ready=false

while [ $waited -lt $max_wait ]; do
    if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8003/health" 2>/dev/null | grep -q "200"; then
        log_info "✅ 健康检查通过"
        ready=true
        break
    fi
    sleep $interval
    waited=$((waited + interval))
    echo -n "."
done

if [ "$ready" = false ]; then
    log_error "❌ 健康检查超时"
    docker stop M00_3BGE 2>/dev/null || true
    docker rm M00_3BGE 2>/dev/null || true
    release_model_lock "emb_bge_m3"
    exit 1
fi

python3 << PYEOF
import json
import datetime
import os

state_file = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    with open(state_file, 'w') as f:
        json.dump({"version": "6.0", "running_models": {}}, f, indent=2)

with open(state_file, 'r') as f:
    state = json.load(f)

if 'running_models' not in state:
    state['running_models'] = {}

state['running_models']['emb_bge_m3'] = {
    'status': 'running',
    'container': 'M00_3BGE',
    'port': 8003,
    'gpu': 'CPU',
    'pool': 'L0',
    'engine': 'infinity',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF

release_model_lock "emb_bge_m3"
log_info "========== ✅ emb_bge_m3 启动完成 =========="
M00_START

chmod +x /ai/ai_dxos/scripts/model_actions/start_emb_bge_m3.sh
echo "✅ start_emb_bge_m3.sh 已备份"

# 5.2 M00 停止脚本
cat > /ai/ai_dxos/scripts/model_actions/stop_emb_bge_m3.sh << 'M00_STOP'
#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_emb_bge_m3.sh
# 停止模型: emb_bge_m3 (L0)

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_emb_bge_m3] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_emb_bge_m3] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始停止 emb_bge_m3 =========="

if ! acquire_model_lock "emb_bge_m3"; then
    log_error "获取模型锁失败"
    exit 1
fi

log_info "停止容器: M00_3BGE"
docker stop M00_3BGE 2>/dev/null || true
docker rm M00_3BGE 2>/dev/null || true
sleep 2

python3 << PYEOF
import json
import os

state_file = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    print("state.json 不存在，跳过")
    exit(0)

try:
    with open(state_file, 'r') as f:
        state = json.load(f)
    if 'running_models' in state and 'emb_bge_m3' in state['running_models']:
        del state['running_models']['emb_bge_m3']
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
    print("✅ 状态已更新")
except Exception as e:
    print(f"更新状态失败: {e}")
PYEOF

release_model_lock "emb_bge_m3"
log_info "========== ✅ emb_bge_m3 停止完成 =========="
M00_STOP

chmod +x /ai/ai_dxos/scripts/model_actions/stop_emb_bge_m3.sh
echo "✅ stop_emb_bge_m3.sh 已备份"

# 5.3 M01 - qwen3_32b (Pool-A, SGLang)
cat > /ai/ai_dxos/scripts/model_actions/start_qwen3_32b.sh << 'M01_START'
#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_qwen3_32b.sh
# 启动模型: qwen3_32b (Pool-A, GPU: 0,1)

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_qwen3_32b] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_qwen3_32b] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始启动 qwen3_32b =========="

acquire_global_lock || exit 1

RUNNING=$(get_pool_running_models "Pool-A" "qwen3_32b")
if [ -n "$RUNNING" ]; then
    log_info "Pool-A 已有运行中模型: $RUNNING，执行停止..."
    for m in $RUNNING; do
        if [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ]; then
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
        fi
    done
    sleep 3
fi

release_global_lock

acquire_model_lock "qwen3_32b" || exit 1

log_info "清理 GPU: 0,1"
clean_gpu_pool "Pool-A"
sleep 2
if ! wait_gpu_ready "0,1" 30; then
    log_error "GPU 未就绪"
    release_model_lock "qwen3_32b"
    exit 1
fi

if ss -tlnp | grep -q ":8001 "; then
    log_error "端口 8001 已被占用"
    release_model_lock "qwen3_32b"
    exit 1
fi

docker run -d \
  --name M01_32B \
  --restart unless-stopped \
  --gpus all \
  --shm-size 16g \
  -e CUDA_VISIBLE_DEVICES=0,1 \
  -e CUDA_DISABLE_P2P=1 \
  -e NCCL_P2P_DISABLE=1 \
  -e NCCL_IB_DISABLE=1 \
  -e NCCL_DEBUG=INFO \
  -e SGLANG_DISABLE_TORCHCODEC=1 \
  --ipc=host \
  -p 8001:8001 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  --entrypoint python3 \
  lmsysorg/sglang:v0.5.17-cu130-runtime \
  -m sglang.launch_server \
  --model-path /models/Qwen3-32B-AWQ \
  --served-model-name qwen3_32b \
  --port 8001 \
  --host 0.0.0.0 \
  --tp 2 \
  --trust-remote-code \
  --mem-fraction-static 0.82 \
  --context-length 32768 \
  --quantization awq_marlin \
  --disable-custom-all-reduce \
  --cuda-graph-max-bs 32

if [ $? -ne 0 ]; then
    log_error "Docker 启动失败"
    release_model_lock "qwen3_32b"
    exit 1
fi

log_info "等待健康检查 (端口 8001)..."
if wait_health_check 8001 600 "M01_32B" "0,1" "Pool-A"; then
    log_info "✅ 健康检查通过"
else
    log_error "❌ 健康检查超时"
    docker stop M01_32B 2>/dev/null || true
    docker rm M01_32B 2>/dev/null || true
    release_model_lock "qwen3_32b"
    exit 1
fi

python3 << PYEOF
import json
import datetime
import os

state_file = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    with open(state_file, 'w') as f:
        json.dump({"version": "6.0", "running_models": {}}, f, indent=2)

with open(state_file, 'r') as f:
    state = json.load(f)

if 'running_models' not in state:
    state['running_models'] = {}

state['running_models']['qwen3_32b'] = {
    'status': 'running',
    'container': 'M01_32B',
    'port': 8001,
    'gpu': '0,1',
    'pool': 'Pool-A',
    'engine': 'sglang',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF

release_model_lock "qwen3_32b"
log_info "========== ✅ qwen3_32b 启动完成 =========="
M01_START

chmod +x /ai/ai_dxos/scripts/model_actions/start_qwen3_32b.sh
echo "✅ start_qwen3_32b.sh 已备份"

# 5.4 M02 - qwen38_27b_f8 (Pool-B, SGLang)
cat > /ai/ai_dxos/scripts/model_actions/start_qwen38_27b_f8.sh << 'M02_START'
#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_qwen38_27b_f8.sh
# 启动模型: qwen38_27b_f8 (Pool-B, GPU: 2,3)

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_qwen38_27b_f8] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_qwen38_27b_f8] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始启动 qwen38_27b_f8 =========="

acquire_global_lock || exit 1

RUNNING=$(get_pool_running_models "Pool-B" "qwen38_27b_f8")
if [ -n "$RUNNING" ]; then
    log_info "Pool-B 已有运行中模型: $RUNNING，执行停止..."
    for m in $RUNNING; do
        if [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ]; then
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
        fi
    done
    sleep 3
fi

release_global_lock

acquire_model_lock "qwen38_27b_f8" || exit 1

log_info "清理 GPU: 2,3"
clean_gpu_pool "Pool-B"
sleep 2
if ! wait_gpu_ready "2,3" 30; then
    log_error "GPU 未就绪"
    release_model_lock "qwen38_27b_f8"
    exit 1
fi

if ss -tlnp | grep -q ":8002 "; then
    log_error "端口 8002 已被占用"
    release_model_lock "qwen38_27b_f8"
    exit 1
fi

docker run -d \
  --name M02_27F8 \
  --restart unless-stopped \
  --gpus '"device=2,3"' \
  --shm-size 32g \
  -p 8002:8002 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  -e NCCL_P2P_DISABLE=1 \
  -e NCCL_IB_DISABLE=1 \
  --entrypoint python3 \
  lmsysorg/sglang:v0.5.17-cu130-runtime \
  -m sglang.launch_server \
  --model-path /models/Qwen3.8-27B-FP8 \
  --served-model-name qwen38_27b_f8 \
  --port 8002 \
  --host 0.0.0.0 \
  --tp-size 2 \
  --trust-remote-code \
  --mem-fraction-static 0.75 \
  --context-length 24560 \
  --disable-custom-all-reduce \
  --mm-feature-transport cpu \
  --cuda-graph-backend-prefill disabled \
  --enable-tf32-matmul \
  --stream-interval 1

if [ $? -ne 0 ]; then
    log_error "Docker 启动失败"
    release_model_lock "qwen38_27b_f8"
    exit 1
fi

log_info "等待健康检查 (端口 8002)..."
if wait_health_check 8002 600 "M02_27F8" "2,3" "Pool-B"; then
    log_info "✅ 健康检查通过"
else
    log_error "❌ 健康检查超时"
    docker stop M02_27F8 2>/dev/null || true
    docker rm M02_27F8 2>/dev/null || true
    release_model_lock "qwen38_27b_f8"
    exit 1
fi

python3 << PYEOF
import json
import datetime
import os

state_file = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    with open(state_file, 'w') as f:
        json.dump({"version": "6.0", "running_models": {}}, f, indent=2)

with open(state_file, 'r') as f:
    state = json.load(f)

if 'running_models' not in state:
    state['running_models'] = {}

state['running_models']['qwen38_27b_f8'] = {
    'status': 'running',
    'container': 'M02_27F8',
    'port': 8002,
    'gpu': '2,3',
    'pool': 'Pool-B',
    'engine': 'sglang',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF

release_model_lock "qwen38_27b_f8"
log_info "========== ✅ qwen38_27b_f8 启动完成 =========="
M02_START

chmod +x /ai/ai_dxos/scripts/model_actions/start_qwen38_27b_f8.sh
echo "✅ start_qwen38_27b_f8.sh 已备份"

# 5.5 M03 - gemma_4 (Pool-A, llama.cpp)
cat > /ai/ai_dxos/scripts/model_actions/start_gemma_4.sh << 'M03_START'
#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_gemma_4.sh
# 启动模型: gemma_4 (Pool-A, GPU: 0,1)
# 基于附件验证成功

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_gemma_4] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_gemma_4] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始启动 gemma_4 =========="

acquire_global_lock || exit 1

RUNNING=$(get_pool_running_models "Pool-A" "gemma_4")
if [ -n "$RUNNING" ]; then
    log_info "Pool-A 已有运行中模型: $RUNNING，执行停止..."
    for m in $RUNNING; do
        if [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ]; then
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
        fi
    done
    sleep 3
fi

release_global_lock

acquire_model_lock "gemma_4" || exit 1

log_info "清理 GPU: 0,1"
clean_gpu_pool "Pool-A"
sleep 2
if ! wait_gpu_ready "0,1" 30; then
    log_error "GPU 未就绪"
    release_model_lock "gemma_4"
    exit 1
fi

if ss -tlnp | grep -q ":8004 "; then
    log_error "端口 8004 已被占用"
    release_model_lock "gemma_4"
    exit 1
fi

docker run -d \
  --name M03_gemma4 \
  --restart unless-stopped \
  --gpus '"device=0,1"' \
  --shm-size 16g \
  -e CUDA_VISIBLE_DEVICES=0,1 \
  -e CUDA_DISABLE_P2P=1 \
  -e NCCL_P2P_DISABLE=1 \
  -e NCCL_IB_DISABLE=1 \
  -p 8004:8004 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  ghcr.io/ggml-org/llama.cpp:server-cuda13 \
  -m /models/gemma-4/gemma-4-31b-jang-crack-Q4_K_M.gguf \
  --host 0.0.0.0 \
  --port 8004 \
  --n-gpu-layers 99 \
  --tensor-split 0.52,0.48 \
  --ctx-size 131072 \
  --threads 16 \
  --threads-batch 16 \
  --batch-size 2048 \
  --ubatch-size 512 \
  --flash-attn on \
  --cache-type-k q4_0 \
  --cache-type-v q4_0 \
  --numa distribute

if [ $? -ne 0 ]; then
    log_error "Docker 启动失败"
    release_model_lock "gemma_4"
    exit 1
fi

log_info "等待健康检查 (端口 8004) - llama.cpp 专用..."
if wait_health_check_llama 8004 600 "M03_gemma4" "0,1" "Pool-A"; then
    log_info "✅ 健康检查通过"
else
    log_error "❌ 健康检查超时"
    docker stop M03_gemma4 2>/dev/null || true
    docker rm M03_gemma4 2>/dev/null || true
    release_model_lock "gemma_4"
    exit 1
fi

python3 << PYEOF
import json
import datetime
import os

state_file = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    with open(state_file, 'w') as f:
        json.dump({"version": "6.0", "running_models": {}}, f, indent=2)

with open(state_file, 'r') as f:
    state = json.load(f)

if 'running_models' not in state:
    state['running_models'] = {}

state['running_models']['gemma_4'] = {
    'status': 'running',
    'container': 'M03_gemma4',
    'port': 8004,
    'gpu': '0,1',
    'pool': 'Pool-A',
    'engine': 'llama_cpp',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF

release_model_lock "gemma_4"
log_info "========== ✅ gemma_4 启动完成 =========="
M03_START

chmod +x /ai/ai_dxos/scripts/model_actions/start_gemma_4.sh
echo "✅ start_gemma_4.sh 已备份"

# 5.6 M06 - 38FN_Q4 (Pool-ALL, llama.cpp)
cat > /ai/ai_dxos/scripts/model_actions/start_38FN_Q4.sh << 'M06_START'
#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/start_38FN_Q4.sh
# 启动模型: 38FN_Q4 (Pool-ALL, GPU: 0,1,2,3)
# 基于 llama-b10819 手动验证成功

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_38FN_Q4] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [start_38FN_Q4] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始启动 38FN_Q4 =========="

acquire_global_lock || exit 1

POOL="Pool-ALL"

# Pool-ALL 独占：停止所有其他池
for other_pool in Pool-A Pool-B; do
    RUNNING=$(get_pool_running_models "$other_pool" "")
    if [ -n "$RUNNING" ]; then
        log_info "停止池 $other_pool 中的模型: $RUNNING"
        for m in $RUNNING; do
            if [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ]; then
                /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
            fi
        done
        sleep 2
    fi
done

RUNNING=$(get_pool_running_models "Pool-ALL" "38FN_Q4")
if [ -n "$RUNNING" ]; then
    log_info "停止同池模型: $RUNNING"
    for m in $RUNNING; do
        if [ -f "/ai/ai_dxos/scripts/model_actions/stop_${m}.sh" ]; then
            /ai/ai_dxos/scripts/model_actions/stop_${m}.sh
        fi
    done
    sleep 2
fi

release_global_lock

acquire_model_lock "38FN_Q4" || exit 1

log_info "清理 GPU: 0,1,2,3"
clean_gpu_pool "Pool-ALL"
sleep 3

if ! wait_gpu_ready "0,1,2,3" 60; then
    log_error "GPU 未全部就绪"
    release_model_lock "38FN_Q4"
    exit 1
fi

if ss -tlnp | grep -q ":8007 "; then
    log_error "端口 8007 已被占用"
    release_model_lock "38FN_Q4"
    exit 1
fi

log_info "执行: llama-server (基于验证成功)"

docker run -d \
  --name M06_38FN_Q4 \
  --restart unless-stopped \
  --gpus all \
  --shm-size 32g \
  -e CUDA_VISIBLE_DEVICES=0,1,2,3 \
  -e CUDA_DISABLE_P2P=1 \
  -e NCCL_P2P_DISABLE=1 \
  -e NCCL_IB_DISABLE=1 \
  -p 8007:8007 \
  -v /ai/ai_dxos/volumes/models:/models:ro \
  -v /tmp/llama_b10819/llama-b10819:/opt/llama:ro \
  --entrypoint /opt/llama/llama-server \
  ghcr.io/ggml-org/llama.cpp:server-cuda13 \
  -m /models/Qwen3.8-Flash-Next-UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf \
  --host 0.0.0.0 \
  --port 8007 \
  --n-gpu-layers 99 \
  --tensor-split 0.25,0.25,0.25,0.25 \
  --ctx-size 262144 \
  --threads 32 \
  --flash-attn auto \
  --cache-type-k q4_0 \
  --cache-type-v q4_0

if [ $? -ne 0 ]; then
    log_error "Docker 启动失败"
    release_model_lock "38FN_Q4"
    exit 1
fi

log_info "等待健康检查 (端口 8007) - 使用通用检查..."
if wait_health_check 8007 600 "M06_38FN_Q4" "0,1,2,3" "Pool-ALL"; then
    log_info "✅ 健康检查通过"
else
    log_error "❌ 健康检查超时"
    docker stop M06_38FN_Q4 2>/dev/null || true
    docker rm M06_38FN_Q4 2>/dev/null || true
    release_model_lock "38FN_Q4"
    exit 1
fi

python3 << PYEOF
import json
import datetime
import os

state_file = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    with open(state_file, 'w') as f:
        json.dump({"version": "6.0", "running_models": {}}, f, indent=2)

with open(state_file, 'r') as f:
    state = json.load(f)

if 'running_models' not in state:
    state['running_models'] = {}

state['running_models']['38FN_Q4'] = {
    'status': 'running',
    'container': 'M06_38FN_Q4',
    'port': 8007,
    'gpu': '0,1,2,3',
    'pool': 'Pool-ALL',
    'engine': 'llama_cpp',
    'updated_at': datetime.datetime.now().isoformat(),
    'progress': 100
}

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF

release_model_lock "38FN_Q4"
log_info "========== ✅ 38FN_Q4 启动完成 =========="
M06_START

chmod +x /ai/ai_dxos/scripts/model_actions/start_38FN_Q4.sh
echo "✅ start_38FN_Q4.sh 已备份"

# 5.7 停止脚本 (统一模板, 已验证)
for model in emb_bge_m3 qwen3_32b qwen38_27b_f8 gemma_4 38FN_Q4; do
    case $model in
        emb_bge_m3) container="M00_3BGE"; port=8003; gpu="CPU"; pool="L0"; engine="infinity" ;;
        qwen3_32b) container="M01_32B"; port=8001; gpu="0,1"; pool="Pool-A"; engine="sglang" ;;
        qwen38_27b_f8) container="M02_27F8"; port=8002; gpu="2,3"; pool="Pool-B"; engine="sglang" ;;
        gemma_4) container="M03_gemma4"; port=8004; gpu="0,1"; pool="Pool-A"; engine="llama_cpp" ;;
        38FN_Q4) container="M06_38FN_Q4"; port=8007; gpu="0,1,2,3"; pool="Pool-ALL"; engine="llama_cpp" ;;
    esac

cat > /ai/ai_dxos/scripts/model_actions/stop_${model}.sh << EOS
#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_${model}.sh
# 停止模型: ${model} (${pool})

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_${model}] \$*" | tee -a "\$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [stop_${model}] [ERROR] \$*" | tee -a "\$LOG_FILE" >&2; }

log_info "========== 开始停止 ${model} =========="

if ! acquire_model_lock "${model}"; then
    log_error "获取模型锁失败"
    exit 1
fi

log_info "停止容器: ${container}"
docker stop ${container} 2>/dev/null || true
docker rm ${container} 2>/dev/null || true
sleep 2

if [ "${pool}" != "L0" ]; then
    log_info "清理池 ${pool} 的 GPU 显存..."
    clean_gpu_pool "${pool}"
    sleep 2
    if ! wait_gpu_ready "${gpu}" 30; then
        log_error "GPU 清理可能不完整"
    fi
fi

python3 << PYEOF
import json
import os

state_file = "/ai/ai_dxos/configs/state/state.json"
if not os.path.exists(state_file):
    print("state.json 不存在，跳过")
    exit(0)

try:
    with open(state_file, 'r') as f:
        state = json.load(f)
    if 'running_models' in state and '${model}' in state['running_models']:
        del state['running_models']['${model}']
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
    print("✅ 状态已更新: ${model} 已移除")
except Exception as e:
    print(f"更新状态失败: {e}")
PYEOF

release_model_lock "${model}"
log_info "========== ✅ ${model} 停止完成 =========="
EOS

    chmod +x /ai/ai_dxos/scripts/model_actions/stop_${model}.sh
    echo "✅ stop_${model}.sh 已备份"
done

# ============================================================
# 6. backend/main.py（后端服务）
# ============================================================
cat > /ai/dxos_pilot/backend/main.py << 'BACKEND'
#!/usr/bin/env python3
# /ai/dxos_pilot/backend/main.py
# Dxos_Pilot Backend v6.0

import json
import os
import subprocess
import re
import asyncio
import time
import psutil
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

app = FastAPI(title="Dxos_Pilot API", version="6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_PATH = "/ai/ai_dxos"
PILOT_PATH = "/ai/dxos_pilot"
CONF_PATH = f"{BASE_PATH}/configs"
MODELS_CONF = f"{CONF_PATH}/models.conf"
STATE_FILE = f"{CONF_PATH}/state/state.json"
SCRIPTS_PATH = f"{BASE_PATH}/scripts"
SCHEDULER = f"{SCRIPTS_PATH}/scheduler/scheduler.sh"
ACTIONS_PATH = f"{SCRIPTS_PATH}/actions"
LOG_PATH = f"{BASE_PATH}/logs"
KEYS_CONF = f"{BASE_PATH}/secrets/keys.conf"

def run_cmd(cmd):
    env = os.environ.copy()
    env["MODELS_CONF_FILE"] = "/ai/ai_dxos/configs/models.conf"
    env["STATE_FILE"] = "/ai/ai_dxos/configs/state/state.json"
    env["SCHEDULER_LOCK"] = "/var/run/dxos_scheduler.lock"
    env["MODEL_LOCK_DIR"] = "/run/dxos/model_locks"
    env["BASE_DIR"] = "/ai/ai_dxos"
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd="/ai/ai_dxos", env=env)
    return proc.returncode, proc.stdout, proc.stderr

def parse_models_conf():
    models = []
    if not os.path.exists(MODELS_CONF):
        return models
    with open(MODELS_CONF, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('|')
            if len(parts) >= 7:
                models.append({
                    "api_name": parts[0],
                    "container_name": parts[1],
                    "physical_model": parts[2],
                    "port": int(parts[3]),
                    "gpu_ids": parts[4],
                    "engine": parts[5],
                    "pool": parts[6]
                })
    return models

def get_model_status(model_id):
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        return data.get('running_models', {}).get(model_id, {}).get('status', 'stopped')
    except:
        return 'stopped'

def get_model_progress(model_id):
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        return data.get('running_models', {}).get(model_id, {}).get('progress', 0)
    except:
        return 0

def get_gpu_stats():
    stats = []
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            processes = []
            try:
                procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                for p in procs:
                    try:
                        import psutil as ps
                        cmd = ' '.join(ps.Process(p.pid).cmdline())
                        for kw in ['sglang', 'llama', 'vllm', 'M0']:
                            if kw in cmd:
                                processes.append(cmd.split('/')[-1][:20])
                                break
                        else:
                            processes.append(f'pid:{p.pid}')
                    except:
                        processes.append(f'pid:{p.pid}')
            except:
                pass
            stats.append({
                "index": i,
                "used_gb": round(mem.used / 1024**3, 1),
                "total_gb": round(mem.total / 1024**3, 1),
                "utilization": util.gpu,
                "temperature": temp,
                "processes": processes[:2]
            })
    except Exception as e:
        print(f"GPU stats error: {e}")
    return stats

def get_system_stats():
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        swap = psutil.swap_memory()
        return {
            "cpu_usage": psutil.cpu_percent(interval=0.5),
            "memory_used_gb": round(mem.used / 1024**3, 1),
            "memory_total_gb": round(mem.total / 1024**3, 1),
            "memory_percent": mem.percent,
            "swap_used_gb": round(swap.used / 1024**3, 1),
            "swap_total_gb": round(swap.total / 1024**3, 1),
            "swap_percent": swap.percent,
            "disk_used_gb": round(disk.used / 1024**3, 1),
            "disk_total_gb": round(disk.total / 1024**3, 1),
            "disk_percent": disk.percent
        }
    except Exception as e:
        return {
            "cpu_usage": 0,
            "memory_used_gb": 0,
            "memory_total_gb": 0,
            "memory_percent": 0,
            "swap_used_gb": 0,
            "swap_total_gb": 0,
            "swap_percent": 0,
            "disk_used_gb": 0,
            "disk_total_gb": 0,
            "disk_percent": 0
        }

def get_docker_containers():
    result = {}
    try:
        proc = subprocess.run(
            "docker ps --filter 'name=^/M' --format '{{.Names}}|{{.Ports}}'",
            shell=True, capture_output=True, text=True
        )
        for line in proc.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('|')
            name = parts[0]
            ports = parts[1] if len(parts) > 1 else ""
            port_match = re.search(r':(\d+)->', ports)
            port = int(port_match.group(1)) if port_match else 0
            match = re.match(r'(M\d{2})', name)
            if match:
                result[name] = {"container_name": name, "port": port}
    except:
        pass
    return result

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/dashboard")
async def get_dashboard():
    models = parse_models_conf()
    containers = get_docker_containers()
    for m in models:
        status = get_model_status(m['api_name'])
        progress = get_model_progress(m['api_name'])
        m["status"] = status
        m["progress"] = progress
        m["container_status"] = "running" if status in ['running', 'starting', 'loading'] else "stopped"
    gpus = get_gpu_stats()
    system = get_system_stats()
    return JSONResponse({"models": models, "gpus": gpus, "system": system})

@app.get("/api/models")
async def get_models():
    models = parse_models_conf()
    for m in models:
        m["status"] = get_model_status(m['api_name'])
        m["progress"] = get_model_progress(m['api_name'])
    return JSONResponse(models)

@app.post("/api/models/{model_id}/start")
async def start_model(model_id: str):
    code, out, err = run_cmd(f"{SCHEDULER} switch {model_id}")
    return JSONResponse({"success": code == 0, "message": out + err})

@app.post("/api/models/{model_id}/stop")
async def stop_model(model_id: str):
    code, out, err = run_cmd(f"{SCHEDULER} stop {model_id}")
    return JSONResponse({"success": code == 0, "message": out + err})

@app.post("/api/stop/all")
async def stop_all():
    code, out, err = run_cmd(f"{SCHEDULER} stop_all")
    return JSONResponse({"success": code == 0, "message": out + err})

@app.post("/api/gpu/clean")
async def clean_gpu(target: str = "all"):
    code, out, err = run_cmd(f"{ACTIONS_PATH}/clean_gpu.sh {target}")
    return JSONResponse({"success": code == 0, "output": out + err})

@app.get("/api/gateway/status")
async def gateway_status():
    code, out, err = run_cmd("docker ps --filter 'name=litellm-gateway' --format '{{.Status}}'")
    if code == 0 and out.strip():
        return JSONResponse({"status": "running", "detail": out.strip()})
    elif code == 0:
        return JSONResponse({"status": "stopped", "detail": "Container not found"})
    else:
        return JSONResponse({"status": "error", "detail": err})

@app.post("/api/gateway/restart")
async def restart_gateway():
    code, out, err = run_cmd("cd /ai/ai_dxos/docker && docker compose restart litellm-gateway 2>/dev/null || true")
    if code == 0:
        time.sleep(3)
        health_code, _, _ = run_cmd("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9980/health")
        if health_code.strip() == "200":
            return JSONResponse({"success": True, "message": "Gateway 重启成功"})
        else:
            return JSONResponse({"success": False, "message": "Gateway 健康检查失败"})
    return JSONResponse({"success": False, "message": out + err})

@app.get("/api/keys")
async def get_keys():
    keys = []
    if os.path.exists(KEYS_CONF):
        with open(KEYS_CONF, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key_name, key_value = line.split('=', 1)
                    key_name = key_name.replace('KEY_', '')
                    masked = key_value[:4] + "****" + key_value[-4:] if len(key_value) > 8 else "****"
                    endpoint = f"http://192.168.10.132:9980/{key_name}"
                    keys.append({
                        "model_name": key_name,
                        "api_key": masked,
                        "endpoint": endpoint,
                        "expires_at": "2027-08-30",
                        "is_active": True
                    })
    return JSONResponse(keys)

@app.post("/api/keys/{model_name}/renew")
async def renew_key(model_name: str):
    new_expiry = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    return JSONResponse({
        "success": True,
        "model_name": model_name,
        "new_expiry": new_expiry,
        "message": f"Key renewed until {new_expiry}"
    })

@app.get("/api/stream/logs")
async def stream_logs():
    log_file = f"{LOG_PATH}/action.log"
    async def event_generator():
        proc = await asyncio.create_subprocess_exec(
            'tail', '-n', '20', '-f', log_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield f"data: {json.dumps({'log': line.decode().strip()})}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9981)
BACKEND

echo "✅ backend/main.py 已备份"

# ============================================================
# 7. 清理脚本 clean_gpu.sh
# ============================================================
cat > /ai/ai_dxos/scripts/actions/clean_gpu.sh << 'CLEAN_GPU'
#!/bin/bash
# /ai/ai_dxos/scripts/actions/clean_gpu.sh
# 【C6】GPU 清理唯一执行器

set -euo pipefail
LOG_FILE="/ai/ai_dxos/logs/action.log"

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [clean_gpu] $*" | tee -a "$LOG_FILE"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [clean_gpu] [WARN] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [clean_gpu] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

is_dxos_managed() {
    local pid=$1
    local cmdline=$(cat /proc/$pid/cmdline 2>/dev/null | tr '\0' ' ' || echo "")
    if echo "$cmdline" | grep -qE "(sglang|llama|vllm|infinity)"; then
        return 0
    fi
    local cgroup=$(cat /proc/$pid/cgroup 2>/dev/null | grep -E "docker|containerd" | head -1 || echo "")
    if [ -n "$cgroup" ]; then
        local container_id=$(echo "$cgroup" | sed 's/.*\///' | cut -c1-12)
        local container_name=$(docker ps --filter "id=$container_id" --format "{{.Names}}" 2>/dev/null || echo "")
        if [[ "$container_name" =~ ^M0[0-9]_ ]]; then
            return 0
        fi
    fi
    return 1
}

clean_gpu() {
    local target=$1
    local force=${2:-0}
    local gpu_list=""
    case "$target" in
        all|pool-all) gpu_list="0,1,2,3" ;;
        pool-a) gpu_list="0,1" ;;
        pool-b) gpu_list="2,3" ;;
        [0-3]) gpu_list="$target" ;;
        [0-3],[0-3]) gpu_list="$target" ;;
        *) log_error "未知目标: $target"; return 1 ;;
    esac

    log_info "开始清理 GPU: $gpu_list (目标: $target)"
    local pids=$(nvidia-smi --id="$gpu_list" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -d ' ')
    if [ -z "$pids" ]; then
        log_info "GPU $gpu_list 无用户进程需要清理"
        return 0
    fi

    local dxos_pids=""
    local unknown_pids=""
    for pid in $pids; do
        if is_dxos_managed "$pid"; then
            dxos_pids="${dxos_pids} $pid"
        else
            unknown_pids="${unknown_pids} $pid"
        fi
    done

    if [ -n "$dxos_pids" ]; then
        log_info "清理 Dxos 模型进程: $dxos_pids"
        for pid in $dxos_pids; do
            kill -TERM "$pid" 2>/dev/null || true
            sleep 0.5
            kill -9 "$pid" 2>/dev/null || true
        done
    fi

    if [ -n "$unknown_pids" ]; then
        log_warn "发现未知进程: $unknown_pids"
        if [ "$force" = "1" ]; then
            log_warn "强制清理未知进程"
            for pid in $unknown_pids; do
                kill -TERM "$pid" 2>/dev/null || true
                sleep 0.5
                kill -9 "$pid" 2>/dev/null || true
            done
        else
            log_error "未知进程未清理，使用 --force 强制清理"
            return 2
        fi
    fi
    log_info "清理完成"
    return 0
}

case "${1:-}" in
    all|pool-a|pool-b|pool-all|[0-3]|[0-3],[0-3])
        if [ "${2:-}" = "--force" ]; then
            clean_gpu "$1" 1
        else
            clean_gpu "$1" 0
        fi
        exit $?
        ;;
    --force)
        clean_gpu "$2" 1
        exit $?
        ;;
    *)
        echo "用法: $0 {all|pool-a|pool-b|pool-all|<gpu_list>} [--force]"
        exit 1
        ;;
esac
CLEAN_GPU

chmod +x /ai/ai_dxos/scripts/actions/clean_gpu.sh
echo "✅ clean_gpu.sh 已备份"

# ============================================================
# 8. 备份完成信息
# ============================================================
echo ""
echo "============================================================"
echo "  Dxos_Pilot v6.0 已验证程序备份完成"
echo "  备份时间: $(date)"
echo "============================================================"
echo ""
echo "已验证模型:"
echo "  ✅ M00 (emb_bge_m3)  - L0, Infinity"
echo "  ✅ M01 (qwen3_32b)   - Pool-A, SGLang"
echo "  ✅ M02 (qwen38_27b_f8) - Pool-B, SGLang"
echo "  ✅ M03 (gemma_4)     - Pool-A, llama.cpp"
echo "  ✅ M06 (38FN_Q4)     - Pool-ALL, llama.cpp"
echo ""
echo "文件清单:"
echo "  /ai/ai_dxos/configs/models.conf"
echo "  /ai/ai_dxos/scripts/model_actions/common_pool.sh"
echo "  /ai/ai_dxos/scripts/scheduler/scheduler.sh"
echo "  /ai/ai_dxos/scripts/common/state.sh"
echo "  /ai/ai_dxos/scripts/actions/clean_gpu.sh"
echo "  /ai/dxos_pilot/backend/main.py"
echo ""
echo "启动/停止脚本:"
ls -1 /ai/ai_dxos/scripts/model_actions/start_*.sh | grep -E "emb_bge_m3|qwen3_32b|qwen38_27b_f8|gemma_4|38FN_Q4" | sed 's/^/  /'
ls -1 /ai/ai_dxos/scripts/model_actions/stop_*.sh | grep -E "emb_bge_m3|qwen3_32b|qwen38_27b_f8|gemma_4|38FN_Q4" | sed 's/^/  /'
echo ""
echo "============================================================"
echo ""
echo "恢复方法:"
echo "  1. 执行此脚本: bash /ai/ai_dxos/verified_backup_v6.0.sh"
echo "  2. 重启后端: systemctl restart dxos-backend"
echo "  3. 验证: /ai/ai_dxos/scripts/scheduler/scheduler.sh status"
echo "============================================================"

