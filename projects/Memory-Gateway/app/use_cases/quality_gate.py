"""Quality Gate: 判断证据是否足够回答问题

五维评分（权重和 = 1.0）：
- 相关度 30%
- 权威性 25%
- 时效性 20%
- 覆盖率 15%
- 冲突度 10%

阈值：
- >= 0.70 → PASS
- 0.45 ~ 0.70 → RETRY（带改写 query 建议）
- < 0.45 → GIVE_UP
"""
import sys
import datetime
from typing import Dict

if "/ai/Memory-Gateway" not in sys.path:
    sys.path.insert(0, "/ai/Memory-Gateway")

from contracts.research import (
    EvidenceBundle, QueryPlan, QualityDecision, Budget,
)


class QualityGate:
    PASS_THRESHOLD = 0.70
    RETRY_THRESHOLD = 0.45

    def evaluate(self, bundle: EvidenceBundle, plan: QueryPlan,
                 iteration: int = 1,
                 budget: Budget = None) -> QualityDecision:
        # 五维评分
        relevance = self._compute_relevance(bundle)
        authority = bundle.authority_score
        freshness = bundle.freshness_score
        coverage = bundle.coverage_score
        conflict_score = self._compute_conflict_score(bundle)

        score = (
            0.30 * relevance +
            0.25 * authority +
            0.20 * freshness +
            0.15 * coverage +
            0.10 * conflict_score
        )

        # 决策
        if score >= self.PASS_THRESHOLD:
            verdict = "pass"
            reason = f"证据充分（score={score:.2f}）"
        elif score >= self.RETRY_THRESHOLD and iteration < 3:
            verdict = "retry"
            reason = f"证据不足（score={score:.2f}），建议重试"
        else:
            verdict = "give_up"
            reason = f"证据严重不足（score={score:.2f}），建议拒答"

        # 预算检查
        if budget and budget.exhausted():
            verdict = "give_up"
            reason = "预算耗尽"

        # 生成重试建议
        retry_suggestions = []
        if verdict == "retry":
            retry_suggestions = self._generate_retry_suggestions(bundle, plan)

        breakdown = {
            "relevance": round(relevance, 3),
            "authority": round(authority, 3),
            "freshness": round(freshness, 3),
            "coverage": round(coverage, 3),
            "conflict": round(conflict_score, 3),
            "weighted": round(score, 3),
        }

        return QualityDecision(
            verdict=verdict,
            score=score,
            breakdown=breakdown,
            retry_suggestions=retry_suggestions,
            reason=reason,
            trust_provenance={
                "iteration": iteration,
                "query": plan.queries[0] if plan.queries else "",
                "evidence_count": len(bundle.evidences),
                "claim_count": len(bundle.claims),
                "conflict_count": len(bundle.conflicts),
            },
        )

    # -------- 五维评分 --------
    def _compute_relevance(self, bundle: EvidenceBundle) -> float:
        """相关度 = 0.5 × 数量饱和 + 0.5 × 排名质量"""
        if not bundle.evidences:
            return 0.0
        n = len(bundle.evidences)
        quantity = min(1.0, n / 5.0)           # 5 条以上满分
        rank_quality = sum(ev.relevance_score for ev in bundle.evidences) / n
        return 0.5 * quantity + 0.5 * rank_quality

    def _compute_conflict_score(self, bundle: EvidenceBundle) -> float:
        """冲突度：无冲突 = 1.0，冲突比例越高分越低"""
        n_claims = max(1, len(bundle.claims))
        n_conflicts = len(bundle.conflicts)
        ratio = n_conflicts / n_claims
        return max(0.0, 1.0 - ratio * 2.0)     # 50% 冲突 → 0 分

    # -------- 重试建议 --------
    def _generate_retry_suggestions(self, bundle: EvidenceBundle,
                                     plan: QueryPlan) -> list:
        """根据 breakdown 生成改写 query 建议"""
        import datetime
        suggestions = []
        base = plan.queries[0] if plan.queries else ""

        # 权威性低 → 加 site:gov.cn
        if bundle.authority_score < 0.6:
            suggestions.append(f"{base} site:gov.cn")
        # 时效性低 → 加年份
        year = datetime.date.today().year
        if bundle.freshness_score < 0.4:
            suggestions.append(f"{base} {year}")
        # 覆盖率低 → 加"详细"
        if bundle.coverage_score < 0.5:
            suggestions.append(f"{base} 详细")

        # ★ 兜底：都没触发 → 用原 query + 详细，保证不空
        if not suggestions and base:
            suggestions.append(f"{base} 详细")

        return suggestions[:2]

_gate = None


def get_quality_gate() -> QualityGate:
    global _gate
    if _gate is None:
        _gate = QualityGate()
    return _gate


if __name__ == "__main__":
    # 独立测试：模拟不同质量场景
    from contracts.research import (
        Evidence, Source, Claim, Citation, Conflict, make_id,
    )

    # 场景 1：证据充分
    print("════════ 场景 1：证据充分 ════════")
    sources = [Source(source_id="s1", url="https://gov.cn/x", domain="gov.cn",
                      authority_score=0.95)]
    evidences = [
        Evidence(evidence_id=f"ev{i}", source_id="s1", document_id="d1",
                 chunk_id="c1", quote=f"证据 {i}", start_char=0, end_char=10,
                 relevance_score=0.9 - i * 0.05)
        for i in range(5)
    ]
    bundle = EvidenceBundle(
        query="测试", evidences=evidences, sources=sources,
        authority_score=0.95, freshness_score=0.9, coverage_score=1.0)
    d = get_quality_gate().evaluate(bundle, QueryPlan(
        plan_id="p1", need_web_search=True, reason="t", queries=["测试"]))
    print(f"  verdict={d.verdict} score={d.score:.3f}")
    print(f"  breakdown={d.breakdown}")

    # 场景 2：证据不足
    print("\n════════ 场景 2：证据不足 ════════")
    sources = [Source(source_id="s2", url="https://x.com", domain="x.com",
                      authority_score=0.3)]
    evidences = [
        Evidence(evidence_id="ev0", source_id="s2", document_id="d2",
                 chunk_id="c2", quote="模糊内容", start_char=0, end_char=10,
                 relevance_score=0.5)
    ]
    bundle = EvidenceBundle(
        query="测试", evidences=evidences, sources=sources,
        authority_score=0.3, freshness_score=0.2, coverage_score=0.2)
    d = get_quality_gate().evaluate(bundle, QueryPlan(
        plan_id="p2", need_web_search=True, reason="t", queries=["测试"]))
    print(f"  verdict={d.verdict} score={d.score:.3f}")
    print(f"  breakdown={d.breakdown}")
    print(f"  retry_suggestions={d.retry_suggestions}")

    # 场景 3：完全无证据
    print("\n════════ 场景 3：无证据 ════════")
    bundle = EvidenceBundle(query="测试")
    d = get_quality_gate().evaluate(bundle, QueryPlan(
        plan_id="p3", need_web_search=True, reason="t", queries=["测试"]))
    print(f"  verdict={d.verdict} score={d.score:.3f}")
