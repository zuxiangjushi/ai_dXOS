"""轻量问题分类器：关键词 + 规则，不上 LLM

设计纪律：
- 不上 LLM（成本高、慢、不稳定）
- 规则可解释、可调整、可单元测试
- 优先级：unanswerable > realtime > compare > howto > factual > 兜底
"""
import re
import sys
from typing import Optional

if "/ai/Memory-Gateway" not in sys.path:
    sys.path.insert(0, "/ai/Memory-Gateway")

from contracts.capability import QueryCategory, get_rule, CapabilityRule


# ===== 关键词规则（按优先级从上到下） =====

# 1. 不可答（最高优先级）
_UNANSWERABLE = [
    r"20(?:2[7-9]|[3-9]\d)\s*年",        # 未来年份（2027-2099，容忍空格）
    r"20(?:2[7-9]|[3-9]\d).*(?:诺奖|诺贝尔|冠军|当选|发生)",
    r"(?:预测|推算|测算).*(?:结果|走势|冠军|涨跌|输赢)",
    r"明天.*(?:股价|彩票|彩票号|开奖)",
    r"下(?:一|几)?期.*(?:开奖|彩票|号码)",
]

# 2. 实时（时间敏感）
_REALTIME = [
    r"今天|今日|现在|此刻|实时|当前",
    r"(?:天气|气温|温度|股价|汇率|油价|汇率)",
    r"最新|刚刚|最近.{0,4}(?:新闻|动态|消息)",
    r"20\d{2}年\d{1,2}月\d{1,2}日",
]

# 3. 对比
_COMPARE = [
    r"\bvs\b|\bVS\b|对比|比较|区别|差异",
    r"哪个更(?:好|快|强|优)|优缺点|优劣",
    r"(?:与|和).*相比",
]

# 4. 操作指南
_HOWTO = [
    r"怎么|如何|怎样",
    r"安装|配置|部署|搭建|接入|使用|编写",
    r"步骤|教程|指南|入门",
]

# 5. 事实
_FACTUAL = [
    r"什么是|是什么|定义|含义|介绍",
    r"(?:的)?版本|发布于|基于|采用",
    r"谁|哪里|什么时候|为什么",
]


def _matches(patterns: list, text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def classify(query: str) -> QueryCategory:
    """按优先级分类问题

    优先级：unanswerable > realtime > compare > howto > factual > factual(兜底)
    """
    if not query or not query.strip():
        return "factual"
    q = query.strip()

    if _matches(_UNANSWERABLE, q):
        return "unanswerable"
    if _matches(_REALTIME, q):
        return "realtime"
    if _matches(_COMPARE, q):
        return "compare"
    if _matches(_HOWTO, q):
        return "howto"
    if _matches(_FACTUAL, q):
        return "factual"
    # 兜底：当作 factual（最保守）
    return "factual"


def classify_freshness(query: str) -> str:
    """时效性分级：realtime / recent / normal / historical

    驱动检索策略：
    - realtime:   只走 SearXNG（不查索引，索引再新也是旧的）
    - recent:     SearXNG + Meili（索引 7 天内）
    - normal:     SearXNG + Meili（默认）
    - historical: 不走 web，只走 RAG 文档
    """
    if not query or not query.strip():
        return "normal"
    q = query.strip().lower()

    # REALTIME：今天/现在/此刻/实时/当前
    _realtime = ["今天", "今日", "现在", "此刻", "实时", "当前", "刚刚",
                 "today", "now", "currently", "right now"]
    if any(k in q for k in _realtime):
        return "realtime"

    # HISTORICAL：明确年份/历史事件
    import re
    if re.search(r"20[0-2]\d\s*年", q):  # 2000-2029（容忍空格）
        return "historical"
    _hist = ["历史", "过去", "当年", "曾经"]
    if any(k in q for k in _hist):
        return "historical"

    # RECENT：最近/本周/近期
    _recent = ["最近", "本周", "这周", "近期", "这几天", "近期",
               "recent", "this week", "recently", "news"]
    if any(k in q for k in _recent):
        return "recent"

    return "normal"


def classify_with_rule(query: str) -> tuple:
    """分类 + 返回对应规则"""
    cat = classify(query)
    return cat, get_rule(cat)


if __name__ == "__main__":
    # 自测：15 题 + 边界
    tests = [
        ("重庆今天气温", "realtime"),
        ("2026年9月13日重庆天气", "realtime"),
        ("最新的 AI 新闻", "realtime"),
        ("什么是 Qdrant", "factual"),
        ("Python 3.12 什么时候发布", "factual"),
        ("Qdrant vs Milvus 哪个更好", "compare"),
        ("如何安装 Docker", "howto"),
        ("Docker 部署步骤", "howto"),
        ("2027 年诺贝尔奖得主是谁", "unanswerable"),
        ("预测一下下期彩票号码", "unanswerable"),
        ("明天股价预测", "unanswerable"),
        ("你好", "factual"),  # 兜底
    ]
    print(f"{'查询':<36} {'期望':<14} {'实际':<14} {'规则':<12} 结果")
    print("─" * 90)
    ok = 0
    for q, expected in tests:
        actual, rule = classify_with_rule(q)
        mark = "✅" if actual == expected else "❌"
        if actual == expected:
            ok += 1
        print(f"{q:<36} {expected:<14} {actual:<14} {rule.behavior:<12} {mark}")
    print(f"\n通过: {ok}/{len(tests)}")
