#!/bin/bash
# 6 客户端协议回归测试
set -e
cd /ai/Memory-Gateway
source .env.g0 2>/dev/null
GW=http://127.0.0.1:9982
KEY=${PILOT_KEY_M00}

# ★ 动态选模型（不硬编码 qwen3_32b）
MODEL=$(cd /ai/Memory-Gateway && ./.venv/bin/python -c "
import sys
sys.path.insert(0, '/ai/Memory-Gateway')
try:
    from adapters.model_picker import pick_model
    print(pick_model())
except Exception:
    print('yy38_27b')
" 2>/dev/null | tail -1)
[ -z "$MODEL" ] && MODEL="yy38_27b"
echo "使用模型: $MODEL"
echo ""

PASS=0; FAIL=0

check() {
  if [ "$2" = "200" ]; then echo "✅ $1: HTTP 200"; PASS=$((PASS+1))
  else echo "❌ $1: HTTP $2"; FAIL=$((FAIL+1)); fi
}

echo "════════ 6 客户端协议回归 ════════"

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $GW/v1/chat/completions \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" -H "X-User-Id: reg1" \
  -d '{"model":"'"$MODEL"'","messages":[{"role":"system","content":"helpful"},{"role":"user","content":"hi"}],"max_tokens":10}')
check "1 Open WebUI" "$CODE"

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $GW/v1/chat/completions \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" -H "X-User-Id: reg2" \
  -d '{"model":"'"$MODEL"'","messages":[{"role":"user","content":"hi"}],"max_tokens":10,"stream":true}')
check "2 OpenClaw" "$CODE"

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $GW/v1/messages \
  -H "Content-Type: application/json" -H "x-api-key: $KEY" -H "X-User-Id: reg3" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"'"$MODEL"'","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}')
check "3 Claude Code" "$CODE"

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $GW/v1/chat/completions \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" -H "X-User-Id: reg4" \
  -d '{"model":"'"$MODEL"'","messages":[{"role":"user","content":"hi"},{"role":"system","content":"tools"}],"tools":[{"type":"function","function":{"name":"f","parameters":{"type":"object"}}}],"max_tokens":10}')
check "4 Cline" "$CODE"

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $GW/v1/chat/completions \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" -H "X-User-Id: reg5" \
  -d '{"model":"'"$MODEL"'","messages":[{"role":"user","content":"hi"}],"stream":true,"max_tokens":10}')
check "5 Continue" "$CODE"

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $GW/v1/responses \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" -H "X-User-Id: reg6" \
  -H "User-Agent: codex-cli/0.1" \
  -d '{"model":"'"$MODEL"'","input":"hi","max_output_tokens":10}')
check "6 Codex CLI" "$CODE"

echo ""
echo "结果: 通过 $PASS / 6"
LOG=logs/gateway_$(date +%Y%m%d).log
FAILS=$(grep -ac "pre-call 失败" "$LOG" 2>/dev/null | head -n1)
FAILS=${FAILS:-0}
echo "pre-call 失败次数: $FAILS （应为 0）"

if [ "$FAIL" = "0" ] && [ "$FAILS" = "0" ]; then echo "✅ 全部通过"; exit 0
else echo "❌ 有失败项"; exit 1; fi
