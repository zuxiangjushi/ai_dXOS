# ai_dXOS — DXOS 平台备份归档

私有备份仓库，包含 DXOS（天枢）算力平台的三个核心项目及外部依赖配置。

## 目录结构

```
ai_dXOS/
├── projects/
│   ├── ai_dxos/            # 算力模型底座（483 文件, 18MB）
│   │   ├── configs/        #   模型池配置、LiteLLM 配置、状态管理
│   │   ├── docker/         #   Docker Compose 部署
│   │   ├── scripts/        #   模型启停脚本（start_*.sh）、同步工具
│   │   ├── Strata/         #   Strata 推理引擎（源码，二进制已排除）
│   │   └── docs/           #   项目文档
│   ├── dxos_pilot/         # 算力控制面板（32 文件, 396KB）
│   │   ├── backend/        #   FastAPI 后端（Flask）
│   │   ├── frontend/       #   Vue 3 前端（单文件）
│   │   └── logs/           #   运行时日志（已排除）
│   └── Memory-Gateway/     # 无限记忆网关（2071 文件, 43MB）
│       ├── adapters/       #   模型适配器（litellm_hooks, web_search, qdrant_rag 等）
│       ├── search_modules/ #   搜索模块（天气、新闻、股票、Wiki、地理）
│       ├── deploy/         #   Docker/Nginx 部署配置
│       ├── scripts/        #   运维脚本（同步、回归测试、日志轮转）
│       ├── vendor/         #   第三方依赖（mem0-main 等）
│       └── docs/           #   网关文档
├── external-dependencies/  # 外部系统依赖（80KB）
│   ├── docker/             #   Docker 相关配置
│   ├── systemd/            #   systemd 服务单元（13 个，已脱敏）
│   └── scripts/            #   外部脚本
├── docs/                   # 备份与审计文档
│   ├── security_audit.md   #   密钥扫描报告
│   ├── git_github_plan.md  #   GitHub 备份计划（Phase B）
│   ├── final_backup_report.md
│   └── git_archive_supplement_20261106.md
├── manifests/
│   └── SHA256SUMS.txt      # 全量文件 SHA256 校验和
├── scripts/                # 备份辅助脚本
└── .gitignore              # 排除规则
```

## 排除规则

以下文件类型/目录不纳入备份（见 `.gitignore`）：

- **模型权重 / 二进制**：`*.gguf`、`*.bin`、`*.so`、`Strata/data/`、`Strata/python/`
- **虚拟环境**：`venv/`、`.venv/`、`node_modules/`
- **运行时产物**：`__pycache__/`、`*.pyc`、`logs/`、`*.db`
- **敏感文件**：`.env`、`*.pem`、`*.key`（已脱敏）
- **手工备份**：`*.bak*`（源项目中的历史备份文件）
- **Strata 引擎二进制**：`strata`、`strata-dsv41`、`strata-vision`、`*.tar.gz`（约 4.6GB）

## 脱敏处理

以下文件中的真实密钥已替换为 `<REDACTED_*>` 占位符：

| 文件 | 脱敏内容 |
|------|---------|
| `projects/Memory-Gateway/claude_bridge.py` | LITELLM_KEY |
| `projects/Memory-Gateway/fastapi_gateway.py` | LITELLM_MASTER_KEY、PG_DSN、3× sk- model keys |
| `projects/ai_dxos/configs/litellm_config.yaml` | 7× api_key |
| `projects/ai_dxos/docker/docker-compose.yml` | LITELLM_MASTER_KEY |
| `external-dependencies/systemd/` (16 文件) | 各类 API key / token |

脱敏前的原始文件保留在 `/backup/github-backups/`（本地，不入仓库）。

## 恢复方法

```bash
# 1. 克隆
git clone git@github.com:zuxiangjushi/ai_dXOS.git
cd ai_dXOS

# 2. 校验完整性
sha256sum -c manifests/SHA256SUMS.txt

# 3. 将 projects/ 下的目录恢复到目标位置
#    （注意：模型权重、虚拟环境、Strata 二进制需单独恢复）
```

## 增量备份

```bash
cd /backup/github
git add -A
git commit -m "sync: <description>"
git push origin main
```

## 元信息

- **仓库**：`zuxiangjushi/ai_dXOS`（Private）
- **初始归档**：2026-11-06（commit 5551862）
- **最近同步**：2026-11-08（commit 9300d09，27 文件同步 + 4 文件脱敏）
- **文件总数**：2225
- **仓库大小**：~92MB（不含模型权重/二进制）
- **git 用户**：zuxiangjushi <zuxiangjushi@users.noreply.github.com>
