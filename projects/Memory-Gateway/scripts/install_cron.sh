#!/bin/bash
# 幂等安装 cron
CRON_LINE="0 9 * * * /bin/bash /ai/Memory-Gateway/scripts/daily_report.sh >> /backup/Memory-Gateway-backups/daily_reports/\$(date +\%Y\%m\%d).txt 2>&1"

# 检查是否已存在
if crontab -l 2>/dev/null | grep -qF "daily_report.sh"; then
  echo "ℹ️ cron 已存在，跳过"
else
  (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
  echo "✅ cron 已安装"
fi

echo ""
echo "=== 当前 crontab ==="
crontab -l 2>/dev/null || echo "(空)"
