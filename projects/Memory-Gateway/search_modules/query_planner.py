"""
Query Planner —— 规则版 Query 改写
- 5 类识别：compare / howto / realtime / list / general
- 规则优先，无 LLM
- 决策点：A/B 收益 <10% → 不引入
"""
import re
from typing import List, Dict, Tuple
from datetime import date


class QueryPlanner:
    """规则版 Query 改写器"""

    # ───────── 规则表 ─────────
    RULES = [
        # 优先级 1: 对比（最具体）
        ("compare", [
            r"^(.+?)\s*(?:vs\.?|VS|对比|比较)\s*(.+)$",
            r"^(.+?)\s*(?:和|与|跟)\s*(.+?)\s*(?:哪个好|哪个更|哪个强|区别|差异|优劣)$",
        ]),
        # 优先级 2: weekly（比 realtime 更具体，放在 realtime 之前）
        ("weekly", [
            r"^(.+?)\s*(?:本周|这周|下周|上周)\s*(.+)$",
            r"^(.+?)\s*(?:未来|接下来)\s*(?:一?[周星期]|几天|\d+天)\s*(.+)$",
            r"^(.+?)\s*(?:7天|3天|一周|几天)\s*(.+)$",
        ]),
        # 优先级 3: howto（要求完整动词，避免匹配 "怎么样"）
        ("howto", [
            r"^(.+?)\s*(?:怎么办|如何解决|怎么解决|怎样解决|如何处理|怎么处理|怎样处理|报错|错误|失败|出错|异常)$",
        ]),
        # 优先级 4: realtime
        ("realtime", [
            r"^(?:今天|今日|现在|刚刚|此刻)\s*(.+)$",
            r"^(?:最新|最近的?)\s*(.+)$",
        ]),
        # 优先级 5: list
        ("list", [
            r"^(.+?)\s*(?:有哪些|有哪几种|有什么|有几种)$",
        ]),
    ]

    def __init__(self, enable: bool = True, min_gain_threshold: float = 0.10):
        self.enable = enable
        self.min_gain_threshold = min_gain_threshold

    def classify(self, query: str) -> Tuple[str, dict]:
        """返回 (type, match_info)"""
        if not query:
            return ("general", {})
        q = query.strip()

        for rule_type, patterns in self.RULES:
            for pat in patterns:
                m = re.search(pat, q, re.IGNORECASE)
                if m:
                    return (rule_type, {"match": m, "pattern": pat})

        return ("general", {})

    def rewrite(self, query: str) -> List[str]:
        """返回改写后的 query 列表"""
        if not query or not query.strip():
            return []

        q = query.strip()
        q_type, info = self.classify(q)

        if q_type == "general" or not info.get("match"):
            return [q]

        m = info["match"]
        today = date.today()

        try:
            if q_type == "compare":
                a, b = m.group(1).strip(), m.group(2).strip()
                return [f"{a} 特点 优势", f"{b} 特点 优势", f"{a} vs {b} 对比"]

            elif q_type == "weekly":
                # group(1)+group(2) 拼接，清洗掉疑问词
                topic = (m.group(1) + m.group(2)).strip()
                topic = self._clean_topic(topic)
                if not topic:
                    topic = q
                return [
                    f"{topic} 未来一周",
                    f"{topic} 7天预报",
                    q,
                ]

            elif q_type == "howto":
                topic = m.group(1).strip()
                return [
                    f"{topic} 解决方案",
                    f"{topic} 排查步骤",
                    f"{topic} 官方文档",
                ]

            elif q_type == "realtime":
                # realtime 不改写（时间锚点不能丢）
                return [q]

            elif q_type == "list":
                topic = m.group(1).strip()
                return [
                    f"{topic} 列表",
                    f"{topic} 完整清单",
                    q,
                ]

        except (IndexError, AttributeError):
            pass

        return [q]

    def _clean_topic(self, topic: str) -> str:
        """清洗主题词：去掉命令词前缀 + 疑问词后缀"""
        if not topic:
            return ""
        # ★ v7.7: 剥离命令词前缀（避免 "搜索一下" 进入搜索引擎查询）
        _prefixes = ["搜索一下", "搜一下", "查一下", "查查", "帮我查", "帮我搜", "请搜", "搜索", "查询"]
        for _p in _prefixes:
            if topic.startswith(_p):
                topic = topic[len(_p):].strip()
                break
        # 剥离疑问词后缀
        topic = re.sub(r'(怎么样|如何|怎样|是什么|有哪些|怎么)$', '', topic)
        topic = re.sub(r'[的了]$', '', topic)
        return topic.strip()

    def plan(self, query: str) -> Dict:
        """返回完整规划（含分类 + queries）"""
        q_type, _ = self.classify(query)
        queries = self.rewrite(query)
        return {
            "original": query,
            "type": q_type,
            "queries": queries,
            "rewritten": len(queries) > 1,
        }


_planner = None


def get_planner() -> QueryPlanner:
    global _planner
    if _planner is None:
        _planner = QueryPlanner()
    return _planner


# ───────── 单测 ─────────
if __name__ == "__main__":
    p = get_planner()
    tests = [
        "SGLang NCCL 报错怎么办",
        "bge-m3 vs Qwen3-Embedding 哪个好",
        "今天重庆天气",
        "Python 有哪些新特性",
        "OpenAI 最新模型",
        "你好",  # general
    ]
    for q in tests:
        r = p.plan(q)
        print(f"\n[{r['type']}] {r['original']}")
        for i, sq in enumerate(r["queries"], 1):
            print(f"  {i}. {sq}")
