# Memory-Gateway

给不可改造的 Agent 客户端加"无限记忆 + 无限上下文 + 文档检索"的透明网关。

## 架构

客户端层（9 个）
  Open WebUI / OpenClaw / Claude Code / Cline / Continue
  Codex CLI / Hermes / ComfyUI / Cursor / Aider
       │  HTTP (3 协议)
       ▼
Memory-Gateway :9982
  ├ 协议适配: OpenAI / Anthropic / Responses
  ├ pre-call:  身份 → 记忆 → RAG → 上下文组装
  ├ post-call: 写回队列
  └ 12 端点
       │
       ├──▶ 底座 :9980（模型推理）
       ├──▶ Mem0  :8888（长期记忆）
       ├──▶ Qdrant:6333（语义检索）
       ├──▶ Meili :7700（关键词检索）
       ├──▶ PG    :5433（元数据）
       └──▶ bge-m3:8003（embedding）

## 快速启动

    cd /ai/Memory-Gateway
    bash scripts/start_with_logrotate.sh
    bash scripts/acceptance_full.sh

## 核心能力

| 能力 | 实现 | 状态 |
|---|---|---|
| 无限记忆 | Mem0 + Qdrant + PG | OK |
| 无限上下文 | tiktoken + 摘要 + 智能截断 | OK |
| 搜索引擎 | Qdrant 语义 + Meili 关键词 | OK |
| 参数优化 | 池感知路由 | OK |
| 协议兼容 | OpenAI / Anthropic / Responses | OK |
| 可观测 | Langfuse + Prometheus + 日报 | OK |

## 端点清单（12 个）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /healthz | 综合健康检查 |
| GET | /metrics | Prometheus 指标 |
| GET | /v1/models | 模型列表 |
| GET | /v1/pools | 池配置 |
| POST | /v1/chat/completions | OpenAI 协议 |
| POST | /v1/messages | Anthropic 协议 |
| POST | /v1/responses | OpenAI Responses |
| POST | /v1/rag/documents | 上传文档 |
| GET | /v1/rag/documents | 列出文档 |
| DELETE | /v1/rag/documents/{id} | 删除文档 |
| GET | /v1/users/{uid}/memories | 用户记忆列表 |
| DELETE | /v1/users/{uid}/memories/{mid} | 删除记忆 |

## 运维命令

    bash scripts/acceptance_full.sh      # 综合验收
    bash scripts/regression_clients.sh   # 6 客户端回归
    bash scripts/stress_test.sh 20       # 压测
    bash scripts/daily_report.sh         # 日报
    bash scripts/snapshot_metrics.sh     # metrics 快照
    bash scripts/check_embedding.sh      # bge-m3 健康

## 目录

- fastapi_gateway.py  — 主入口
- adapters/           — 适配器（hooks / mem0 / qdrant_rag / meili / langfuse）
- app/use_cases/      — 用例（context_engine / model_router）
- app/workers/        — worker（writeback / index_reconciler / rag_indexer）
- contracts/          — 契约（零第三方依赖）
- scripts/            — 运维脚本
- docs/               — 文档
