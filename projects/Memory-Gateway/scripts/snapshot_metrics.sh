#!/bin/bash
# 把 /metrics 快照存到 PG 和本地（弥补 Counter 无持久化）
set -e
cd /ai/Memory-Gateway
source .env.g0 2>/dev/null

TS=$(date +%s)
OUT_DIR="/ai/Memory-Gateway/data/metrics_snapshots"
mkdir -p "$OUT_DIR"

# 1. 抓 /metrics
curl -s http://127.0.0.1:9982/metrics -o "$OUT_DIR/metrics_$TS.txt"

# 2. 归档到 PG（建表 + 插入 JSONB）
docker exec -i mg-g0-pg_ssd-1 psql -U probe -d probe <<'SQL' >/dev/null 2>&1 || true
CREATE TABLE IF NOT EXISTS metrics_snapshots (
  id BIGSERIAL PRIMARY KEY,
  ts BIGINT NOT NULL,
  raw TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_metrics_snap_ts ON metrics_snapshots(ts);
SQL

# 3. 写入快照
RAW=$(cat "$OUT_DIR/metrics_$TS.txt" | head -c 100000 | sed "s/'/''/g")
docker exec -i mg-g0-pg_ssd-1 psql -U probe -d probe <<SQL >/dev/null 2>&1 || true
INSERT INTO metrics_snapshots (ts, raw) VALUES ($TS, '$RAW');
SQL

# 4. 保留 7 天本地 + 30 天 PG
find "$OUT_DIR" -name "metrics_*.txt" -mtime +7 -delete 2>/dev/null || true
docker exec -i mg-g0-pg_ssd-1 psql -U probe -d probe \
  -c "DELETE FROM metrics_snapshots WHERE ts < $(($TS - 30*86400));" >/dev/null 2>&1 || true

echo "✅ 快照 $TS 已存"
