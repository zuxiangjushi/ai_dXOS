"""Universal Context Gateway v5.0 - Research Evidence Infrastructure 契约层

本模块定义 4 个核心资产（Query Planner / Retrieval Policy / Evidence Engine / Quality Gate）
的输入输出契约，以及 7 个核心数据结构。

设计原则：
- 契约先于实现：本模块不依赖任何第三方库
- 组件是 Adapter：所有具体实现（SearXNG/Wukong/LongCite）都是可替换的
- 失败码统一：所有模块的失败码有统一前缀
- 证据可溯源：每个 Evidence 都能追溯到 Source + 字符位置
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal, Any
from enum import Enum


# ==================== 7 个核心数据结构 ====================

@dataclass
class Source:
    """来源：一个 URL 的元数据"""
    source_id: str
    url: str
    domain: str
    title: str = ""
    published_at: Optional[int] = None       # Unix 时间戳
    retrieved_at: int = 0                    # Unix 时间戳
    authority_score: float = 0.5             # 0-1
    language: str = "zh-CN"
    content_hash: str = ""
    trust_level: Literal["official", "media", "community", "ugc", "unknown"] = "unknown"


@dataclass
class Document:
    """文档：一个 URL 抓取+清洗后的内容"""
    document_id: str
    source_id: str
    raw_html: Optional[str] = None
    clean_text: str = ""
    markdown: str = ""
    language: str = "zh-CN"
    extractor: str = ""                      # trafilatura / docling / ...
    extract_confidence: float = 0.0
    error: Optional[str] = None


@dataclass
class Chunk:
    """块：文档切分后的检索单元"""
    chunk_id: str
    document_id: str
    text: str
    start_char: int
    end_char: int
    token_count: int = 0
    embedding_id: Optional[str] = None       # Qdrant point id


@dataclass
class Evidence:
    """证据：可追溯到具体位置的内容片段"""
    evidence_id: str
    source_id: str
    document_id: str
    chunk_id: str
    quote: str                               # 引用原文
    start_char: int
    end_char: int
    locator: dict = field(default_factory=dict)  # {url, page, paragraph, sentence}
    relevance_score: float = 0.0
    retrieved_at: int = 0


@dataclass
class Claim:
    """声明：从证据中抽取的事实性陈述"""
    claim_id: str
    text: str
    evidence_ids: list = field(default_factory=list)
    confidence: float = 0.0
    claim_type: Literal["fact", "number", "date", "categorical", "opinion"] = "fact"


@dataclass
class Citation:
    """引用：Claim → Evidence 的显式绑定"""
    citation_id: str
    claim_id: str
    evidence_id: str
    display_index: int                       # [1] [2] 的序号
    span_text: str = ""                      # 被引用的原文片段


@dataclass
class Conflict:
    """冲突：两个 Claim 之间的不一致"""
    conflict_id: str
    claim_a_id: str
    claim_b_id: str
    conflict_type: Literal["numeric", "categorical", "temporal", "authority"]
    resolution: Literal["prefer_latest", "prefer_authoritative",
                        "prefer_majority", "unresolved"] = "unresolved"
    resolved_value: Optional[str] = None


# ==================== Budget 预算控制 ====================

@dataclass
class Budget:
    """本次研究的预算（防止单次查询消耗过多资源）"""
    total_s: int = 60
    max_iterations: int = 3
    max_queries: int = 5
    max_candidates: int = 300
    max_crawl: int = 50
    max_browser: int = 10
    max_llm_calls: int = 3

    # 运行时计数
    queries_used: int = 0
    candidates_seen: int = 0
    crawl_count: int = 0
    browser_count: int = 0
    llm_calls: int = 0
    iteration: int = 0
    started_at: float = 0.0

    def reduce_by_half(self):
        """重试时预算减半"""
        self.max_queries = max(1, self.max_queries // 2)
        self.max_candidates = max(10, self.max_candidates // 2)
        self.max_crawl = max(5, self.max_crawl // 2)

    def exhausted(self) -> bool:
        import time
        if self.started_at and (time.time() - self.started_at) > self.total_s:
            return True
        if self.crawl_count >= self.max_crawl:
            return True
        if self.llm_calls >= self.max_llm_calls:
            return True
        if self.iteration >= self.max_iterations:
            return True
        return False

    def snapshot(self) -> dict:
        return {
            "iteration": self.iteration,
            "queries_used": self.queries_used,
            "candidates_seen": self.candidates_seen,
            "crawl_count": self.crawl_count,
            "browser_count": self.browser_count,
            "llm_calls": self.llm_calls,
        }


# ==================== 4 个核心资产的接口契约 ====================

# ---- ① Query Planner ----
@dataclass
class QueryPlan:
    """Query Planner 的输出"""
    plan_id: str
    need_web_search: bool
    reason: str
    queries: list = field(default_factory=list)          # 1-3 个搜索 query
    query_type: Literal["news", "factual", "howto", "compare",
                        "realtime", "general"] = "general"
    freshness: Literal["realtime", "recent", "normal",
                       "historical"] = "normal"
    language: str = "zh-CN"
    max_candidates: int = 50
    priority_sources: list = field(default_factory=list)
    negative_terms: list = field(default_factory=list)


# ---- ② Retrieval Policy ----
@dataclass
class RetrievalDecision:
    """Retrieval Policy 的输出"""
    url: str
    strategy: Literal["http", "crawl4ai", "playwright",
                      "camoufox", "archive", "domain_api"] = "http"
    domain_provider: Optional[str] = None      # zhihu / bilibili / weibo ...
    reason: str = ""
    timeout_s: int = 15
    expected_cost: float = 0.1                  # 0-1，用于预算控制


# ---- ③ Evidence Engine ----
@dataclass
class EvidenceBundle:
    """Evidence Engine 的输出"""
    query: str
    claims: list = field(default_factory=list)          # [Claim]
    evidences: list = field(default_factory=list)       # [Evidence]
    citations: list = field(default_factory=list)       # [Citation]
    conflicts: list = field(default_factory=list)       # [Conflict]
    sources: list = field(default_factory=list)         # [Source]
    coverage_score: float = 0.0
    authority_score: float = 0.0
    freshness_score: float = 0.0
    generated_at: int = 0


# ---- ④ Quality Gate ----
@dataclass
class QualityDecision:
    """Quality Gate 的输出"""
    verdict: Literal["pass", "retry", "give_up"]
    score: float
    breakdown: dict = field(default_factory=dict)
    retry_suggestions: list = field(default_factory=list)
    reason: str = ""
    trust_provenance: dict = field(default_factory=dict)
    # trust_provenance 建议包含：
    #   runtime_version, model_version, index_version,
    #   evidence_snapshot_id, retrieved_at


# ==================== 统一失败码 ====================

FAILURE_CODES = {
    # Query Planner
    "QP_EMPTY_INPUT": "输入为空",
    "QP_LLM_TIMEOUT": "查询规划超时",
    "QP_LLM_ERROR": "查询规划异常",
    "QP_BUDGET_EXCEEDED": "查询规划预算耗尽",

    # Discovery
    "DP_ALL_FAILED": "全部搜索源失败",
    "DP_NO_RESULTS": "无搜索结果",
    "DP_TIMEOUT": "搜索超时",

    # Candidate Intelligence
    "CI_ALL_FILTERED": "全部候选被过滤",
    "CI_NO_CANDIDATES": "无候选",

    # Retrieval Policy
    "RP_HTTP_TIMEOUT": "HTTP 超时",
    "RP_HTTP_403": "HTTP 反爬拦截",
    "RP_CRAWL4AI_FAIL": "Crawl4AI 渲染失败",
    "RP_PLAYWRIGHT_FAIL": "Playwright 失败",
    "RP_CAMOUFOX_FAIL": "Camoufox 失败",
    "RP_ARCHIVE_MISS": "缓存无",
    "RP_ALL_FAILED": "全部抓取策略失败",
    "RP_BUDGET_EXCEEDED": "抓取预算耗尽",

    # Content Extraction
    "CE_PARSE_FAIL": "内容解析失败",
    "CE_EMPTY": "内容为空",

    # Reranker
    "RR_TIMEOUT": "重排超时",
    "RR_FAIL": "重排失败",

    # Evidence Engine
    "EE_NO_CONTENT": "无内容可抽取",
    "EE_LLM_TIMEOUT": "声明抽取超时",
    "EE_NO_SOURCE": "无法关联来源",
    "EE_CONFLICT_UNRESOLVED": "冲突未解决",

    # Quality Gate
    "QG_SCORE_TOO_LOW": "质量分数不足",
    "QG_MAX_ITERATIONS": "达到最大循环",
    "QG_BUDGET_EXHAUSTED": "预算耗尽",
    "QG_NO_EVIDENCE": "无证据",

    # Budget
    "BG_TOTAL_TIMEOUT": "总耗时超限",
    "BG_CRAWL_EXHAUSTED": "抓取次数耗尽",
    "BG_LLM_EXHAUSTED": "LLM 调用耗尽",
}


# ==================== 辅助函数 ====================

def to_dict(obj) -> dict:
    """dataclass → dict（用于 JSON 序列化）"""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj


def make_id(prefix: str, seed: str) -> str:
    """生成稳定的 ID"""
    import hashlib
    h = hashlib.sha1(seed.encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


__all__ = [
    "Source", "Document", "Chunk", "Evidence",
    "Claim", "Citation", "Conflict",
    "Budget",
    "QueryPlan", "RetrievalDecision",
    "EvidenceBundle", "QualityDecision",
    "FAILURE_CODES",
    "to_dict", "make_id",
]
