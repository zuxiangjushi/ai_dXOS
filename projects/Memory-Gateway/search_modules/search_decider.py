"""
Search Decider —— 统一搜索决策器（v6.9）

设计目标：
    把所有"搜索/不搜索"的决策逻辑集中到 1 个文件，避免散落在
    fastapi_gateway.py / litellm_hooks.py / query_classifier.py。

优先级链（高 → 低）：
    1. 空 query                  → 不搜
    2. personal query            → 不搜（用户记忆类）
    3. must_refuse               → 不搜（拒答类）
    4. MG_ / force_search        → 强制搜（穿透 no_cite）
    5. freshness 特殊            → 搜（穿透关键词表，但受 no_cite 约束）
    6. 关键词命中                → 搜
    7. 用户黑名单                → 不搜
    8. 默认                      → 不搜
"""
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchDecision:
    should_search: bool
    reason: str
    queries: List[str] = field(default_factory=list)
    freshness: str = "normal"
    category: str = "general"
    should_refuse: bool = False
    refuse_reason: str = ""
    debug: dict = field(default_factory=dict)


class SearchDecider:
    # ─── 关键词表（从 litellm_hooks.py 迁移） ───
    WEB_TRIGGER_KEYWORDS = (
        "搜索", "搜一下", "查一下", "查查", "联网", "上网", "百度", "谷歌",
        "最新", "今天", "现在", "实时", "当前", "最近", "新闻",
        "是什么", "什么是", "哪一天", "哪天", "多少钱", "怎么样",
        "放假", "安排", "规定", "政策", "标准", "版本", "价格", "是多少",
        "什么时间", "什么时候", "谁", "在哪", "在哪里",
        "search", "latest", "today", "news", "current",
        # ★ v6.8：时间范围词
        "本周", "这周", "下周", "上周",
        "未来几天", "未来一周", "未来三天", "未来七天",
        "未来3天", "未来7天",
        "明天", "后天", "一周", "几天", "每日", "每天",
        "7天", "3天", "天气预报", "周报",
    )

    PERSONAL_QUERY_PATTERNS = (
        "我叫什么", "我的名字", "我叫", "我住在", "我来自",
        "我喜欢", "我做什么", "我从事", "我的工作",
        "我之前", "我上次", "我说过", "还记得", "记住",
        "前面说的", "刚才说的", "上文提到", "之前说的",
        "上一轮", "上一句", "上一段",
    )

    def __init__(self):
        pass

    def is_personal_query(self, text: str) -> bool:
        if not text:
            return False
        if any(p in text for p in self.PERSONAL_QUERY_PATTERNS):
            return True
        if re.search(r'第\s*\d+\s*轮', text):
            return True
        return False

    def match_keywords(self, text: str) -> bool:
        if not text:
            return False
        t = text.lower()
        return any(kw in t for kw in self.WEB_TRIGGER_KEYWORDS)

    def _get_disabled_users(self):
        raw = os.environ.get("SEARCH_DISABLED_USERS", "")
        return set(s.strip().lower() for s in raw.split(",") if s.strip())

    def decide(
        self,
        query: str,
        has_mg_prefix: Optional[bool] = None,
        force_search: Optional[bool] = None,
        user_id: str = "",
    ) -> SearchDecision:
        debug = {
            "has_mg_prefix": has_mg_prefix,
            "force_search": force_search,
            "user_id": user_id,
        }

        # 1. 空 query
        if not query or not query.strip():
            return SearchDecision(should_search=False, reason="empty", debug=debug)

        q = query.strip()

        # 2. personal query
        if self.is_personal_query(q):
            return SearchDecision(should_search=False, reason="personal", debug=debug)

        # 3. 分类（must_refuse 优先）
        try:
            from app.use_cases.query_classifier import classify_with_rule
            cat, rule = classify_with_rule(q)
            debug["classify"] = {"category": cat, "behavior": rule.behavior}
        except Exception as e:
            cat, rule = "general", None
            debug["classify_error"] = f"{type(e).__name__}: {e}"

        if rule is not None and getattr(rule, "behavior", "") == "must_refuse":
            return SearchDecision(
                should_search=False,
                reason="must_refuse",
                should_refuse=True,
                refuse_reason=getattr(rule, "reason", ""),
                category=cat,
                debug=debug,
            )

        # 4. MG_ / force_search（穿透 no_cite）
        if force_search is True or has_mg_prefix is True:
            plan_data = self._plan(q)
            return SearchDecision(
                should_search=True,
                reason="mg_prefix" if has_mg_prefix else "force_search",
                queries=plan_data["queries"],
                freshness=self._freshness(q),
                category=plan_data["type"],
                debug=debug,
            )

        # 5. freshness 特殊（但受 no_cite 约束）
        fresh = self._freshness(q)
        debug["freshness"] = fresh
        if fresh in ("realtime", "recent", "historical"):
            if rule is not None and getattr(rule, "behavior", "") == "no_cite":
                return SearchDecision(
                    should_search=False,
                    reason=f"freshness={fresh}+no_cite",
                    freshness=fresh, category=cat, debug=debug)
            plan_data = self._plan(q)
            return SearchDecision(
                should_search=True,
                reason=f"freshness={fresh}",
                queries=plan_data["queries"],
                freshness=fresh, category=plan_data["type"], debug=debug)

        # 6. 关键词命中
        if self.match_keywords(q):
            if rule is not None and getattr(rule, "behavior", "") == "no_cite":
                return SearchDecision(
                    should_search=False, reason="keyword+no_cite",
                    freshness=fresh, category=cat, debug=debug)
            plan_data = self._plan(q)
            return SearchDecision(
                should_search=True, reason="keyword",
                queries=plan_data["queries"],
                freshness=fresh, category=plan_data["type"], debug=debug)

        # 7. 用户黑名单
        disabled = self._get_disabled_users()
        if disabled and user_id.lower() in disabled:
            return SearchDecision(
                should_search=False, reason="user_blacklist",
                freshness=fresh, category=cat, debug=debug)

        # 8. 默认不搜
        return SearchDecision(
            should_search=False, reason="default",
            freshness=fresh, category=cat, debug=debug)

    def _freshness(self, q: str) -> str:
        try:
            from app.use_cases.query_classifier import classify_freshness
            return classify_freshness(q)
        except Exception:
            return "normal"

    def _plan(self, q: str) -> dict:
        try:
            from search_modules.query_planner import get_planner
            return get_planner().plan(q)
        except Exception:
            return {"original": q, "type": "general", "queries": [q], "rewritten": False}


_decider = None


def get_decider() -> SearchDecider:
    global _decider
    if _decider is None:
        _decider = SearchDecider()
    return _decider
