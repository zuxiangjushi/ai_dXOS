# 端口变更记录

## 2026-09-12 迁移

| 服务 | 旧端口 | 新端口 | 原因 |
|---|---|---|---|
| Langfuse | 3001 | 3108 | 与底座面板冲突 |
| embed-proxy | 8012 | 3101 | 8012 被 M011 模型占用 |

## 同步修改位置

- `deploy/docker-compose.g0.yml`（Langfuse 端口映射 + NEXTAUTH_URL）
- `deploy/nginx-embed/nginx.conf`（listen 端口）
- `.env.g0`（LANGFUSE_HOST）
- `vendor/mem0-main/server/.env`（EMBEDDING_BASE_URL）
- `adapters/qdrant_rag.py`（EMBED_URL 默认值）
- `scripts/acceptance_full.sh`（端口检查列表）

## 重启命令（改配置后）

Langfuse:   docker compose -f deploy/docker-compose.g0.yml up -d langfuse
embed-proxy: docker rm -f embed-proxy && docker run ...（见 README）
Mem0:       docker rm -f mem0-api && docker run ...（--env-file 变更必须 rm+run）
