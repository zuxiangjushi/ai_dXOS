#!/usr/bin/env bash
echo "== 端口占用检查（必须全部空闲）=="
for p in 5433 5434 6333 7700 6379 9982; do
  if ss -ltn "( sport = :$p )" | grep -q LISTEN; then echo "  占用! $p"; else echo "  空闲  $p"; fi
done
echo "== 底座存活检查（只读探测，不重启不干预）=="
for u in 9980 9981; do
  curl -s -o /dev/null -m 3 -w "  底座 $u -> %{http_code}\n" http://192.168.10.132:$u/ || echo "  底座 $u 不可达"
done
echo "== 盘位与权限 =="
df -h /ai /backup | awk 'NR==1||/\/ai|\/backup/'
sudo mkdir -p /backup/mg_g0/pg && sudo chown -R $USER:$USER /backup/mg_g0 && echo "  /backup/mg_g0 可写 OK"
