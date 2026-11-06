# Git 归档补充报告 — 本轮 (2026-11-06)

本文件是 `final_backup_report.md` (11-05) 的增量记录，不覆盖原报告。

## 1. 完整性复核 (11-06 实际执行)
- `sha256sum -c manifests/SHA256SUMS.txt`: 2580 成功 + 1 特殊文件 (尾换行文件名)
  无法经 sha256sum 解析 → 直接 Python 哈希: MATCH (8d4655be…cdf)
- 磁盘 vs 清单差异 (与 11-05 报告一致, 无漂移):
  - 磁盘有/清单无: 5 个 = docs/*.md ×3 + manifests/SHA256SUMS.txt 自身 + 特殊尾换行文件
  - 清单有/磁盘无: 0 (清单行中的 `\\n` 为转义写法, 实际文件存在)
- 结论: 归档内容自 11-05 起零漂移。

## 2. 敏感信息复扫 (11-06 实际执行, 非 vendor)
发现并脱敏 4 个文件 (Phase A 扫描遗漏, 均为归档副本, 源 /ai 未动):

| # | 文件 | 内容 | 处理 |
|---|------|------|------|
| 1 | projects/Memory-Gateway/scripts/sync_all_models.sh | MEM0_JWT_SECRET 默认值(64字符) + MEM0_ADMIN_KEY (sk-mem0-…) | → «redacted:…» |
| 2 | projects/Memory-Gateway/docs/user_onboarding.md | LLM-gateway API Key (sk-HRu…eFVg, 文档内示例) | → 占位说明 |
| 3 | projects/ai_dxos/scripts/model_actions/start_deepseek_v41_flash.sh | Strata --api-key (sk-strata-…) | → «redacted:strata-api-key» |
| 4 | projects/ai_dxos/docker/docker-compose.yml | LITELLM_MASTER_KEY + OPENAI_API_KEY (sk-master-key-change-me, 弱默认值) ×2 | → «redacted:litellm-master-key» |

- 修改前备份: /backup/github-backups/*.bak_20261106-223910 (4 个, cmp 验证一致)
- 复扫结果: 非 vendor 0 真实密钥。剩余命中均为良性:
  - litellm_config.yaml ×8: `sk-REP…AULT` 占位符 (Phase A 脱敏产物)
  - safe_switch.sh: `Bearer ***` 无值占位
  - docs/*.md ×5: 审计报告对脱敏事件的文字描述
  - admin@example.com: 虚构示例邮箱 (LANGFUSE 初始化变量), 非真实账号
- 注意: 4 个被脱敏文件的哈希与 11-05 清单不再一致 (预期内, 脱敏在清单之后)。
  该文件列表即为差异全集; git 仓库以当前脱敏后内容为权威。

## 3. Git 本地准备 (11-06 已执行)
- git init (/backup/github, 仓库局部)
- .gitignore: 按 B3.2 最终建议写入 (仅排除可再生噪声, 不排除任何项目内容)
- core.filemode: 默认 true (保真, 按 B3.2 建议)
- committer 身份: 仓库局部 user.name/user.email (值见 git log; 未改全局配置)
- 首次 commit: B3.4 草案信息

## 4. 状态
- 本地: 完成 (init + commit + 验收见 task_records/task2_github_backup_checkpoint.md)
- 远端: 未配置, 未 push — 等待用户授权 (账号 zuxiangjushi, 私有仓库 ai-dxos-backup,
  按 B3.5 流程: 建库 → remote add → 非 force push; 凭证不入任何文件)
