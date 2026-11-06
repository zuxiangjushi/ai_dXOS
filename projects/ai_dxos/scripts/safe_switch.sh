#!/bin/bash
# 安全切换模型守卫脚本
TARGET_MODEL=$1
POOL_NAME=$2
CHECK_MODEL_NAME=$3
MAX_WAIT=120 # 最多等 120 秒

if [ -z "$TARGET_MODEL" ]; then
    echo "用法: safe_switch.sh <启动脚本名> <池名> <就绪检查名>"
    exit 1
fi

echo "🛑 [1/3] 正在停止旧模型并启动新模型：$TARGET_MODEL ..."
/ai/ai_dxos/scripts/scheduler/scheduler.sh start $TARGET_MODEL > /dev/null 2>&1

echo "🔄 [2/3] 更新网关池配置..."
sed -i "s/^POOL_ALL_MODELS=.*/POOL_ALL_MODELS=${POOL_NAME}/" /ai/Memory-Gateway/.env.g0
systemctl restart memory-gateway.service

echo "⏳ [3/3] 正在等待模型加载就绪（最高等待 ${MAX_WAIT}秒）..."
for ((i=1; i<=MAX_WAIT/2; i++)); do
    # 使用常驻的 LiteLLM 接口检查模型是否真的活了
    if curl -s http://127.0.0.1:9980/v1/models | grep -q "$CHECK_MODEL_NAME"; then
        # 进一步，发一个极小的对话测试，确保模型真能吐字
        TEST_RESULT=$(curl -s -X POST http://127.0.0.1:9980/v1/chat/completions \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer sk-8d4d78f8c17d0d42a2b986e70d119bf5063da6b8d124e2d0" \
            -d "{\"model\": \"memory-llm\", \"messages\": [{\"role\": \"user\", \"content\": \"hi\"}], \"max_tokens\": 1}")
        
        if echo "$TEST_RESULT" | grep -q "choices"; then
            echo "✅ 模型 $CHECK_MODEL_NAME 已彻底就绪，允许 Agent 继续！"
            exit 0
        fi
    fi
    sleep 2
done

echo "❌ 模型启动超时！"
exit 1
