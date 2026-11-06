#!/bin/bash
N=$(curl -s "http://127.0.0.1:3180/search?q=test&format=json&engines=duckduckgo" --max-time 30 | \
    python3 -c "import json,sys; print(len(json.load(sys.stdin).get('results',[])))" 2>/dev/null)
if [ "$N" -lt 3 ]; then
    echo "$(date) DDG 异常（$N 条），建议检查" >> /var/log/ddg-health.log
fi
