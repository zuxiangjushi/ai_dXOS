# ADR-0001 写入侧职责划分（依据 G0 实测 2026-09-08）
- 决策：op 裁决归 T0 规则层；LLM 仅抽取 content/entity_key/confidence；取代由网关按 entity_key 执行
- 依据：G0 实测 38FN_Q4 op 正确率 50%，DELETE 意图被丢弃返回空数组；T0 规则层 95%
- 影响：V4.9 "使用 LLM 提取记忆" [1] 拆分为 规则裁决 + 模型抽取 两步
- 依赖：需底座提供常驻小模型（7B~8B）以提升抽取语义质量；38FN_Q4 属 Pool-ALL 独占四卡，不宜用于后台判定
- 关联缺陷：V4.9 将 finish_reason 硬编码为 stop、usage 用 len//3 估算 [1]，
  会掩盖本次发现的截断问题，M1 实现时必须透传 finish_reason
- 关联缺口：V4.9 memories 表无 entity_key / valid_from / valid_until / supersedes 字段 [1]，
  M1 建表时按新契约补齐，否则取代机制无法落地
