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
