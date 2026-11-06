"""能力边界契约：定义系统对每一类问题的行为约束

核心问题：系统应该对什么问题做什么？

五类问题：
- realtime:      今天天气、股价、新闻   → 必须有引用
- factual:       什么是 X、X 的版本     → 必须有引用
- howto:         怎么装 Docker          → 不该强制引用（用模型知识）
- compare:       A vs B                 → 引用可选
- unanswerable:  2027 诺奖              → 必须拒答

用法：
    from contracts.capability import get_rule, CAPABILITY_MATRIX
    rule = get_rule("realtime")
    assert rule.behavior == "must_cite"
    assert rule.citation_min == 0.95
"""
from dataclasses import dataclass, field
from typing import Literal


QueryCategory = Literal[
    "realtime",       # 今天天气、股价、新闻
    "factual",        # 什么是 X、X 的版本
    "howto",          # 怎么装 Docker
    "compare",        # A vs B
    "unanswerable",   # 2027 诺奖
]

SystemBehavior = Literal[
    "must_cite",      # 必须有引用
    "may_cite",       # 引用可选
    "no_cite",        # 不该引用（用模型知识）
    "must_refuse",    # 必须拒答
]


@dataclass
class CapabilityRule:
    """单类问题的行为约束"""
    category: QueryCategory
    behavior: SystemBehavior
    citation_target: float          # 期望引用率（理想值）
    citation_min: float             # 最低可接受引用率
    reason: str                     # 为什么这样定义（人类可读）
    refusal_target: float = 0.0     # 期望拒答率


CAPABILITY_MATRIX: dict = {
    "realtime": CapabilityRule(
        category="realtime",
        behavior="must_cite",
        citation_target=1.0,
        citation_min=0.95,
        reason="实时数据必须有来源，否则用户无法验证时效性",
    ),
    "factual": CapabilityRule(
        category="factual",
        behavior="must_cite",
        citation_target=1.0,
        citation_min=0.90,
        reason="事实性陈述应可追溯到来源",
    ),
    "howto": CapabilityRule(
        category="howto",
        behavior="no_cite",
        citation_target=0.0,
        citation_min=0.0,
        reason="操作指南用模型知识即可，强制引用降低可读性",
    ),
    "compare": CapabilityRule(
        category="compare",
        behavior="may_cite",
        citation_target=0.5,
        citation_min=0.0,
        reason="对比分析可引用也可不引用，取决于问题具体内容",
    ),
    "unanswerable": CapabilityRule(
        category="unanswerable",
        behavior="must_refuse",
        citation_target=0.0,
        citation_min=0.0,
        refusal_target=1.0,
        reason="未来/不存在的问题应明确拒答，不应强行生成",
    ),
}


def get_rule(category: str) -> CapabilityRule:
    """取某类别的行为约束（未知类别 → factual 兜底）"""
    return CAPABILITY_MATRIX.get(category, CAPABILITY_MATRIX["factual"])


def all_categories() -> list:
    return list(CAPABILITY_MATRIX.keys())


__all__ = [
    "QueryCategory", "SystemBehavior",
    "CapabilityRule", "CAPABILITY_MATRIX",
    "get_rule", "all_categories",
]
