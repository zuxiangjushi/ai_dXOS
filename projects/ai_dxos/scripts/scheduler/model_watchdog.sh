#!/bin/bash
set -uo pipefail

BASE="/ai/ai_dxos"
STATE="$BASE/configs/state/state.json"
INTERVAL=30
TRAP_EXIT=0

trap 'echo "[WATCHDOG] 收到退出信号"; TRAP_EXIT=1; exit 0;' SIGINT SIGTERM

log() { echo "[$(date '+%F %T')] [WATCHDOG] $*"; }

get_models() {
    python3 - "$STATE" <<'PY'
import json, sys
with open(sys.argv[1]) as f: data = json.load(f)
for name, info in data.get("running_models", {}).items():
    if info.get("status") == "running":
        print("|".join([name, str(info.get("container","")), str(info.get("port","")), str(info.get("engine","")), str(info.get("gpu","")), str(info.get("pool",""))]))
PY
}

check_one() {
    local model="$1" container="$2" port="$3" engine="$4" gpu="$5" pool="$6"
    
    # 远程模型：跳过本机检查
    if [ "$gpu" = "REMOTE" ] || [ "$pool" = "Pool-WIN" ]; then
        log "REMOTE_UNVERIFIED model=$model"; return
    fi

    # Strata 原生引擎：401/403 也算存活（服务端已响应）
    if [ "$engine" = "strata" ]; then
        local code=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 4 "http://127.0.0.1:$port/v1/models" 2>/dev/null || echo "ERR")
        if [[ "$code" =~ ^(200|401|403)$ ]]; then
            log "HEALTHY model=$model engine=strata http=$code"
        else
            log "WARNING model=$model engine=strata http=${code}"
        fi
        return
    fi

    # Docker 引擎：查容器状态或 API
    if docker ps --filter "name=^/${container}$" --filter "status=running" --format '{{.Names}}' 2>/dev/null | grep -Fxq "$container"; then
        log "HEALTHY model=$model engine=$engine container=$container"
    else
        log "WARNING model=$model engine=$engine container=$container"
    fi
}

log "只读监控启动 (间隔 ${INTERVAL}s)"

while [ $TRAP_EXIT -eq 0 ]; do
    if [ ! -r "$STATE" ]; then
        log "ERROR state.json 不可读取"
        sleep "$INTERVAL" & wait $!
        continue
    fi

    while IFS='|' read -r model container port engine gpu pool; do
        [ -z "$model" ] && continue
        check_one "$model" "$container" "$port" "$engine" "$gpu" "$pool"
    done < <(get_models 2>/dev/null)

    sleep "$INTERVAL" & wait $!
done
