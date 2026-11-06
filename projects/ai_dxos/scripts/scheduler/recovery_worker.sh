#!/bin/bash
set -uo pipefail
echo "[$(date '+%F %T')] [RECOVERY] 自动恢复已安全暂停。"
echo "[RECOVERY] 队列消费、重启逻辑等待下一步修复。"

trap 'echo "[RECOVERY] 收到退出信号"; exit 0;' SIGINT SIGTERM
# 使用长 sleep 且可被信号打断
while true; do
    sleep 3600 & wait $!
done
