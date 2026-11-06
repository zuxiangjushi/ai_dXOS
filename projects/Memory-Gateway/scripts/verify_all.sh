#!/bin/bash
# 全功能验证（11 块）
cd /ai/Memory-Gateway
echo "═══════════════════════════════════════════"
echo " Memory-Gateway 全功能验证 $(date '+%F %T')"
echo "═══════════════════════════════════════════"

bash scripts/acceptance_full.sh  # L1 综合验收

# 其余 10 块按需调用
echo ""
echo "如需深度验证，按需手动跑以下块："
echo "  块 1-2:  基础健康 + 三协议"
echo "  块 3-5:  四大功能打指纹"
echo "  块 6-9:  参数/观测/一致性/安全"
echo "  块 10-11: 自动化 + 性能"
