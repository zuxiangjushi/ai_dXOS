"""契约层单元测试"""
import sys
sys.path.insert(0, "/ai/Memory-Gateway")

from contracts.research import (
    Source, Document, Chunk, Evidence, Claim, Citation, Conflict,
    Budget, QueryPlan, RetrievalDecision, EvidenceBundle, QualityDecision,
    FAILURE_CODES, make_id, to_dict,
)


def test_source_defaults():
    s = Source(source_id="s1", url="https://x.com", domain="x.com")
    assert s.authority_score == 0.5
    assert s.language == "zh-CN"
    assert s.trust_level == "unknown"


def test_budget_reduce_by_half():
    b = Budget(max_queries=5, max_candidates=300, max_crawl=50)
    b.reduce_by_half()
    assert b.max_queries == 2
    assert b.max_candidates == 150
    assert b.max_crawl == 25


def test_budget_exhausted_by_crawl():
    b = Budget(max_crawl=5)
    b.crawl_count = 5
    assert b.exhausted() is True


def test_budget_not_exhausted():
    b = Budget(max_crawl=5)
    b.crawl_count = 2
    assert b.exhausted() is False


def test_budget_snapshot():
    b = Budget()
    b.iteration = 2
    b.crawl_count = 10
    snap = b.snapshot()
    assert snap["iteration"] == 2
    assert snap["crawl_count"] == 10


def test_query_plan_defaults():
    p = QueryPlan(plan_id="p1", need_web_search=True, reason="用户问天气")
    assert p.query_type == "general"
    assert p.freshness == "normal"
    assert p.max_candidates == 50


def test_retrieval_decision_defaults():
    d = RetrievalDecision(url="https://x.com")
    assert d.strategy == "http"
    assert d.timeout_s == 15


def test_quality_decision_verdict():
    for v in ("pass", "retry", "give_up"):
        d = QualityDecision(verdict=v, score=0.5)
        assert d.verdict == v


def test_evidence_bundle_empty():
    b = EvidenceBundle(query="test")
    assert b.claims == []
    assert b.coverage_score == 0.0


def test_failure_codes_prefixes():
    """所有失败码都应有正确的模块前缀"""
    valid_prefixes = ("QP_", "DP_", "CI_", "RP_", "CE_", "RR_", "EE_", "QG_", "BG_")
    for code in FAILURE_CODES:
        assert code.startswith(valid_prefixes), f"失败码 {code} 前缀错误"


def test_make_id_stable():
    a = make_id("doc", "https://x.com")
    b = make_id("doc", "https://x.com")
    assert a == b
    c = make_id("doc", "https://y.com")
    assert a != c


def test_to_dict():
    s = Source(source_id="s1", url="https://x.com", domain="x.com")
    d = to_dict(s)
    assert d["source_id"] == "s1"
    assert isinstance(d, dict)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
