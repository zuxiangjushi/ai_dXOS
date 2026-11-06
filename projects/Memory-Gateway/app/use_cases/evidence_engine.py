"""Evidence Engine: 从 raw hits 构造 EvidenceBundle

Phase 2.1 基础版：
- Evidence 构造（从 raw hits）
- Citation 编号（[1] [2]）
- 冲突检测（数值差异 > 30%）
- 时效性/权威性/覆盖率评分
- 不做 Claim 抽取（Phase 2.2 接 LLM）
"""
import sys
import time
import re
from typing import List, Dict

if "/ai/Memory-Gateway" not in sys.path:
    sys.path.insert(0, "/ai/Memory-Gateway")

from contracts.research import (
    Source, Evidence, Claim, Citation, Conflict, EvidenceBundle, make_id,
)


class EvidenceEngine:
    """最简版 Evidence Engine"""

    async def build(self, query: str, raw_hits: List[Dict],
                    sources: List[Source],
                    enable_claim_extraction: bool = False) -> EvidenceBundle:
        now = int(time.time())

        # 1. 构造 Evidence（每条 hit 一个）
        evidences: List[Evidence] = []
        for i, raw in enumerate(raw_hits):
            content = raw.get("content", "") or raw.get("snippet", "")
            if not content:
                continue
            # 找对应 source（按 URL 匹配）
            url = raw.get("url", "")
            src = self._find_source(url, sources, i)
            eid = make_id("ev", f"{src.source_id}:{i}")
            evidences.append(Evidence(
                evidence_id=eid,
                source_id=src.source_id,
                document_id=src.source_id,
                chunk_id=f"{src.source_id}_c0",
                quote=content[:500],
                start_char=0,
                end_char=len(content),
                locator={"url": src.url, "page": None,
                         "paragraph": None, "sentence": None},
                relevance_score=max(0.0, 1.0 - i * 0.05),
                retrieved_at=now,
            ))

        # 2. Citation 编号
        citations: List[Citation] = []
        for i, ev in enumerate(evidences):
            citations.append(Citation(
                citation_id=make_id("cit", ev.evidence_id),
                claim_id="",  # Phase 2.2 关联 claim
                evidence_id=ev.evidence_id,
                display_index=i + 1,
                span_text=ev.quote[:100],
            ))

        # 3. 冲突检测
        conflicts = self._detect_conflicts(evidences)

        # 4. 评分
        authority_score = (sum(s.authority_score for s in sources)
                           / max(1, len(sources)))
        _fc = getattr(self, "_current_freshness", "normal")
        freshness_score = self._compute_freshness(sources, now, freshness_class=_fc)
        coverage_score = min(1.0, len(evidences) / 5.0)

        # ★ Claim 抽取（可选，失败降级）
        import os
        if os.environ.get("EVIDENCE_ENABLE_CLAIM", "false").lower() == "true":
            enable_claim_extraction = True
        claims = []
        if enable_claim_extraction and evidences:
            try:
                from app.use_cases.claim_extractor import get_claim_extractor
                import asyncio
                claims = await asyncio.wait_for(
                    get_claim_extractor().extract(query, evidences),
                    timeout=15.0)
                if claims:
                    print(f"   [evidence] claim 抽取 {len(claims)} 条", flush=True)
            except asyncio.TimeoutError:
                print(f"   [evidence] claim 抽取超时，降级", flush=True)
            except Exception as e:
                print(f"   [evidence] claim 抽取失败: {type(e).__name__}: {e}", flush=True)

        # Citation 重编号（如果有 claims，引用编号按 claim 组织）
        # Phase 2.2 暂不改编号逻辑，保持 [1][2] 对应 evidence

        return EvidenceBundle(
            query=query,
            claims=claims,
            evidences=evidences,
            citations=citations,
            conflicts=conflicts,
            sources=list(sources),
            coverage_score=coverage_score,
            authority_score=authority_score,
            freshness_score=freshness_score,
            generated_at=now,
        )

    def _find_source(self, url: str, sources: List[Source], idx: int) -> Source:
        """按 URL 找 source，否则用第 idx 个兜底"""
        for s in sources:
            if s.url == url:
                return s
        if idx < len(sources):
            return sources[idx]
        # 极端兜底
        return Source(source_id=f"src_{idx}", url=url, domain="")

    def _detect_conflicts(self, evidences: List[Evidence]) -> List[Conflict]:
        """检测数值冲突（同一单位，数值差 > 30%）"""
        num_pat = re.compile(r"(\d+(?:\.\d+)?)\s*(℃|%|度)")
        numbers = []  # [(eid, [(val, unit), ...])]
        for ev in evidences:
            found = num_pat.findall(ev.quote)
            if found:
                numbers.append((ev.evidence_id, found))

        conflicts: List[Conflict] = []
        seen_pairs = set()
        for i in range(len(numbers)):
            for j in range(i + 1, len(numbers)):
                eid_a, na = numbers[i]
                eid_b, nb = numbers[j]
                for va_str, ua in na:
                    for vb_str, ub in nb:
                        if ua != ub:
                            continue
                        va, vb = float(va_str), float(vb_str)
                        if max(va, vb) == 0:
                            continue
                        if abs(va - vb) / max(va, vb) > 0.3:
                            key = (eid_a, eid_b)
                            if key in seen_pairs:
                                continue
                            seen_pairs.add(key)
                            conflicts.append(Conflict(
                                conflict_id=make_id(
                                    "conf", f"{eid_a}:{eid_b}:{va}:{vb}"),
                                claim_a_id=eid_a,
                                claim_b_id=eid_b,
                                conflict_type="numeric",
                                resolution="prefer_latest",
                                resolved_value=f"{va_str}{ua} vs {vb_str}{ub}",
                            ))
                            break
        return conflicts[:5]

    def _compute_freshness(self, sources: List[Source], now: int,
                            freshness_class: str = "normal") -> float:
        """v6.3 Phase 2：按 query 时效性 + 域名分级打分"""
        if not sources:
            return 0.0
        # ★ 按查询时效性决定窗口
        _window = {"realtime": 1.0, "recent": 7.0,
                   "normal": 30.0, "historical": 365.0}.get(freshness_class, 30.0)
        scores = []
        for s in sources:
            if not s.published_at:
                # ★ 无时间戳：按 trust_level 兜底
                tlevel = getattr(s, "trust_level", "unknown")
                _fb = {"official": 0.80, "media": 0.62,
                       "community": 0.55, "ugc": 0.50}.get(tlevel, 0.50)
                scores.append(_fb)
                continue
            age_days = max(0.0, (now - s.published_at) / 86400.0)
            score = max(0.0, 1.0 - age_days / _window)
            scores.append(score)
        return sum(scores) / len(scores)


_engine = None


def get_evidence_engine() -> EvidenceEngine:
    global _engine
    if _engine is None:
        _engine = EvidenceEngine()
    return _engine


if __name__ == "__main__":
    import asyncio
    # 独立测试
    from adapters.discovery import get_discovery
    from contracts.research import QueryPlan

    async def main():
        plan = QueryPlan(plan_id="test", need_web_search=True,
                         reason="test", queries=["重庆今天气温"],
                         max_candidates=5)
        result = await get_discovery().discover(plan)
        hits = result.get("raw", [])
        sources = result.get("sources", [])
        print(f"Discovery: {len(hits)} hits, {len(sources)} sources")

        bundle = await get_evidence_engine().build("重庆今天气温", hits, sources)
        print(f"\nEvidence: {len(bundle.evidences)}")
        print(f"Citations: {len(bundle.citations)}")
        print(f"Conflicts: {len(bundle.conflicts)}")
        print(f"Coverage: {bundle.coverage_score:.2f}")
        print(f"Authority: {bundle.authority_score:.2f}")
        print(f"Freshness: {bundle.freshness_score:.2f}")
        print()
        for c in bundle.citations[:3]:
            print(f"  [{c.display_index}] {c.span_text[:80]}")
        if bundle.conflicts:
            print("\n冲突:")
            for c in bundle.conflicts:
                print(f"  · {c.resolved_value} ({c.conflict_type})")

    asyncio.run(main())
