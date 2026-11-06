#!/bin/bash
# /ai/ai_dxos/scripts/model_actions/stop_emb_bge_m3.sh
# 停止模型: emb_bge_m3 (L0)

set -Eeuo pipefail
source /ai/ai_dxos/scripts/model_actions/common_pool.sh

LOG_FILE="/ai/ai_dxos/logs/model_actions.log"
log_info() { echo "[2026-09-07 08:43:17] [stop_emb_bge_m3] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[2026-09-07 08:43:17] [stop_emb_bge_m3] [ERROR] $*" | tee -a "$LOG_FILE" >&2; }

log_info "========== 开始停止 emb_bge_m3 =========="

if ! acquire_model_lock "emb_bge_m3"; then
    log_error "获取模型锁失败"
    exit 1
fi

log_info "停止容器: M00_3BGE"
docker stop M00_3BGE 2>/dev/null || true
docker rm M00_3BGE 2>/dev/null || true
sleep 2

if [ "L0" != "L0" ]; then
    log_info "清理池 L0 的 GPU 显存..."
    clean_gpu_pool "L0"
    sleep 2
    if ! wait_gpu_ready "CPU" 30; then
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
    if 'running_models' in state and 'emb_bge_m3' in state['running_models']:
        del state['running_models']['emb_bge_m3']
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
    print("✅ 状态已更新: emb_bge_m3 已移除")
except Exception as e:
    print(f"更新状态失败: {e}")
PYEOF

release_model_lock "emb_bge_m3"
log_info "========== ✅ emb_bge_m3 停止完成 =========="
