#!/bin/bash
# 底座模型自动同步：按能力分级选最优模型
source /ai/Memory-Gateway/.env.g0 2>/dev/null
export MEM0_JWT_SECRET="${MEM0_JWT_SECRET:-hbSpi7cc6rGopw42ZaOJ7pjpPjVZ0L09xKY4/37kuYQoKnR9IJK/wr+qze2I1cEH}"
export MEM0_ADMIN_KEY="${MEM0_ADMIN_KEY:-sk-mem0-cc034cabecc3e8a56c3d2ca749c754a6}"

# ★ 能力分级（越大越强，适合记忆抽取）
# tier1: 70B+（最强，慢）
# tier2: 27-32B（平衡，首选）
# tier3: <10B（小模型，可用但质量一般）
TIER1=("deepseek_70b" "qwen38_70b")
TIER2=("qwen3_32b" "yy38_27b" "qwen38_27b_f8" "qwen3_30b")
TIER3=("gemma_4" "yy35b_q6" "38FN_Q4" "gemma2_9b")

# 拉在线模型
ONLINE=$(curl -s http://192.168.10.132:9980/v1/models \
  -H "Authorization: Bearer ${PILOT_KEY_M00}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(m['id'] for m in d.get('data', [])))" 2>/dev/null)

COMPOSE=/ai/Memory-Gateway/deploy/docker-compose.mem0.yml
CURRENT=$(grep -oP '^      OPENAI_MODEL: \K.*' $COMPOSE 2>/dev/null)

# 场景1：底座无模型
if [ -z "$ONLINE" ]; then
    echo "$(date) ⚠️  底座无在线模型，保留上次配置: $CURRENT"
    exit 0
fi

# 场景2：按能力分级选
SELECTED=""
for P in "${TIER1[@]}"; do
    if echo "$ONLINE" | grep -qw "$P"; then SELECTED="$P"; TIER="T1"; break; fi
done
if [ -z "$SELECTED" ]; then
    for P in "${TIER2[@]}"; do
        if echo "$ONLINE" | grep -qw "$P"; then SELECTED="$P"; TIER="T2"; break; fi
    done
fi
if [ -z "$SELECTED" ]; then
    for P in "${TIER3[@]}"; do
        if echo "$ONLINE" | grep -qw "$P"; then SELECTED="$P"; TIER="T3"; break; fi
    done
fi

# 场景3：都不在已知列表 → 用第一个在线（记警告）
if [ -z "$SELECTED" ]; then
    SELECTED=$(echo $ONLINE | awk '{print $1}')
    TIER="T?"
    echo "$(date) ⚠️  未知模型，用第一个在线: $SELECTED"
fi

# ★ 场景0：如果是 capability/* 前缀，跳过（能力代理接管）
if [[ "$CURRENT" == capability/* ]]; then
    echo "$(date) ℹ️  当前是能力代理模式（$CURRENT），跳过"
    exit 0
fi

# 场景4：无变化 → 跳过
if [ "$CURRENT" = "$SELECTED" ]; then
    echo "$(date) ℹ️  保持 $SELECTED ($TIER)"
    exit 0
fi

# 更新
echo "$(date) 切换: $CURRENT → $SELECTED ($TIER)"
sed -i "s/^      OPENAI_MODEL: .*$/      OPENAI_MODEL: $SELECTED/" $COMPOSE

# 同步 .env.g0
sed -i "s/^MEM0_OPENAI_MODEL=.*/MEM0_OPENAI_MODEL=$SELECTED/" /ai/Memory-Gateway/.env.g0

# 重建
cd /ai/Memory-Gateway/deploy
unset MEM0_OPENAI_MODEL
docker compose -f docker-compose.mem0.yml up -d --force-recreate mem0 2>&1 | tail -2
echo "$(date) ✅ 完成 ($TIER)"
