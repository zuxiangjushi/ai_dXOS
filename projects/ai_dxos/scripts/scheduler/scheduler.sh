#!/bin/bash
set -euo pipefail

BASE="/ai/ai_dxos"
MODELS="$BASE/configs/models.conf"
STATE="$BASE/configs/state/state.json"
ACTIONS="$BASE/scripts/model_actions"
LOCK="/var/run/dxos_scheduler.lock"

die() { echo "[ERROR] $*" >&2; exit 1; }

get_model_record() {
    local model="$1"
    awk -F'|' -v m="$model" '$1 == m && $1 !~ /^#/ {print; found=1} END {if (!found) exit 1}' "$MODELS"
}

get_state_status() {
    python3 - "$STATE" "$1" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    print(data.get("running_models", {}).get(sys.argv[2], {}).get("status", "unknown"))
except Exception:
    print("STATE_ERROR")
    sys.exit(1)
PY
}

case "${1:-}" in
    status)
        python3 -c "
import json
with open('$STATE') as f: data = json.load(f)
for name, info in data.get('running_models', {}).items():
    print(f\"{name:28} | {info.get('status','?'):10} | {str(info.get('port','?')):6} | {info.get('pool','?')} | {info.get('engine','?')}\")
"
        exit 0
        ;;

    start|switch)
        MODEL="${2:-}"
        [ -n "$MODEL" ] || die "用法: scheduler.sh start <model>"
        RECORD="$(get_model_record "$MODEL")" || die "模型不在注册表中：$MODEL"
        
        IFS='|' read -r NAME CONTAINER MODEL_ID PORT GPU ENGINE POOL <<< "$RECORD"
        SCRIPT="$ACTIONS/start_${MODEL}.sh"
        [ -f "$SCRIPT" ] || die "启动脚本不存在：$SCRIPT"

        exec 9>"$LOCK"
        flock -w 30 9 || die "获取全局调度锁超时"
        
        # 检查现有状态（如果已 running 就拒绝）
        STATUS="$(get_state_status "$MODEL")" || die "state.json 无法读取"
        if [ "$STATUS" = "running" ]; then
            echo "[SAFE] $MODEL 已登记为 running，拒绝重复启动。"
            exit 0
        fi

        # 端口预检
        if ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q .; then
            die "端口 $PORT 已被占用，拒绝启动 $MODEL"
        fi

        echo "[SCHEDULER] 启动：$MODEL (Engine=$ENGINE, Port=$PORT)"
        "$SCRIPT"
        ;;

    stop)
        MODEL="${2:-}"
        [ -n "$MODEL" ] || die "用法: scheduler.sh stop <model>"
        RECORD="$(get_model_record "$MODEL")" || die "模型不在注册表中：$MODEL"
        
        # Jeff Dean 优化：拒绝硬编码，改为白名单或配置拦截
        # 这里仍默认保护 M18，但通过环境变量允许解禁
        if [ "$MODEL" = "deepseek_v41_flash" ] && [ "${DXOS_ALLOW_M18_STOP:-0}" != "1" ]; then
            die "M18 受到保护，请设置 DXOS_ALLOW_M18_STOP=1 再试。"
        fi

        SCRIPT="$ACTIONS/stop_${MODEL}.sh"
        [ -f "$SCRIPT" ] || die "停止脚本不存在：$SCRIPT"

        exec 9>"$LOCK"
        flock -w 30 9 || die "获取全局调度锁超时"
        "$SCRIPT"
        ;;

    restart|stop_all|reconcile)
        die "该操作已安全禁用。请等待下一步接口对齐。"
        ;;
    *)
        echo "用法: $0 {status|start|switch|stop} <model>"
        exit 1
        ;;
esac
