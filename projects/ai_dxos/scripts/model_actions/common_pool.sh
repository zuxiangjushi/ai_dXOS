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
    local exclude_model=${2:-}
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

        "Pool-EMB") /ai/ai_dxos/scripts/actions/clean_gpu.sh "0,1" ;;
        "L0") echo "L0 无 GPU 需清理" ;;
        *) echo "未知池: $pool" ;;
    esac
}

# ========== Infinity 专用健康检查（v3.1.1） ==========
wait_health_check_infinity() {
    local port=$1
    local max_wait=${2:-300}
    local container=${3:-""}
    local start_time=$(date +%s)
    local end_time=$((start_time + max_wait))

    echo "[健康检查] Infinity 模式：端口 $port，超时 ${max_wait}s"
    for i in $(seq 1 20); do
        if ss -tlnp | grep -q ":$port "; then
            echo "[健康检查] 端口 $port 监听 ✅ (${i}s)"
            break
        fi
        sleep 1
        if [ $i -eq 20 ]; then
            echo "[健康检查] ❌ 端口 $port 20 秒内未监听"
            return 1
        fi
    done

    while [ $(date +%s) -lt $end_time ]; do
        code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 -m 5 "http://127.0.0.1:${port}/health" 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            echo "[健康检查] /health 返回 200 ✅"
            return 0
        fi
        code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 -m 5 "http://127.0.0.1:${port}/v1/models" 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            echo "[健康检查] /v1/models 返回 200 ✅"
            return 0
        fi
        echo -n "."
        sleep 3
    done

    echo "[健康检查] ❌ Infinity 健康检查超时"
    if [ -n "$container" ]; then
        docker logs "$container" --tail 20 2>&1 | sed 's/^/  /'
    fi
    return 1
}
