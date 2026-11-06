#!/bin/bash
set +e

# 从 Dxos 面板或 nvidia-smi 抓取当前活动的模型
# 这里以读取 Dxos 的内部状态文件为例（请根据你的实际路径调整）
DXOS_STATE="/ai/ai_dxos/configs/state/state.json"

if [ ! -f "$DXOS_STATE" ]; then
    exit 0
fi

# 解析出当前跑在 Pool-A 和 Pool-B 的模型名
# 假设 state.json 里有类似 {"Pool-A": "Qwen", "Pool-B": "Llama"} 的结构
POOL_A=$(python3 -c "import json; print(json.load(open('$DXOS_STATE')).get('Pool-A', ''))" 2>/dev/null)
POOL_B=$(python3 -c "import json; print(json.load(open('$DXOS_STATE')).get('Pool-B', ''))" 2>/dev/null)

ENV_FILE="/ai/Memory-Gateway/.env.g0"
NEED_RESTART=0

# 检查 A 池
if [ -n "$POOL_A" ] && ! grep -q "^POOL_A_MODELS=$POOL_A" "$ENV_FILE"; then
    sed -i "s|^POOL_A_MODELS=.*|POOL_A_MODELS=$POOL_A|" "$ENV_FILE"
    NEED_RESTART=1
fi

# 检查 B 池
if [ -n "$POOL_B" ] && ! grep -q "^POOL_B_MODELS=$POOL_B" "$ENV_FILE"; then
    sed -i "s|^POOL_B_MODELS=.*|POOL_B_MODELS=$POOL_B|" "$ENV_FILE"
    NEED_RESTART=1
fi

# 如果有更新，触发网关热重启（耗时 3 秒）
if [ "$NEED_RESTART" -eq 1 ]; then
    echo "$(date) 检测到池状态变更，正在重启网关..." >> /ai/Memory-Gateway/logs/pool_sync.log
    systemctl restart memory-gateway
fi
