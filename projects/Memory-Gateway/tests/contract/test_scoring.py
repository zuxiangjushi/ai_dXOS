import time
from contracts.memory import new_memory
from contracts.scoring import RecallScorer, RecallWeights
from contracts.scope import MemoryScope

SC = MemoryScope(user_id="u1", workspace_id="ws_a")
NOW = 1_800_000_000
def mk(sim_ok=True, **kw):
    base = dict(confidence=0.7, importance=0.5)
    base.update(kw)
    m = new_memory(SC, kw.get("content", "内容"), "user.pref.x", **{k: v for k, v in base.items()})
    return m

def test_bounded_zero_one():
    s = RecallScorer()
    for sim in (0.55, 0.7, 0.85, 1.0):
        for imp in (0.0, 0.5, 1.0):
            for conf in (0.0, 0.6, 1.0):
                v = s.score(mk(importance=imp, confidence=conf), sim, now=NOW)
                assert v is None or 0.0 <= v.score <= 1.0

def test_monotonic_in_similarity():
    s = RecallScorer(); m = mk()
    vals = [s.score(m, x, now=NOW).score for x in (0.56, 0.7, 0.85, 1.0)]
    assert vals == sorted(vals)

def test_monotonic_in_importance_and_confidence():
    s = RecallScorer()
    imp = [s.score(mk(importance=x), 0.9, now=NOW).score for x in (0.0, 0.5, 1.0)]
    conf = [s.score(mk(confidence=x), 0.9, now=NOW).score for x in (0.0, 0.5, 1.0)]
    assert imp == sorted(imp) and conf == sorted(conf)

def test_threshold_acts_on_raw_similarity_only():
    s = RecallScorer()
    assert s.score(mk(confidence=0.05, importance=0.05), 0.40) is None
    assert s.score(mk(confidence=0.5, importance=0.5), 0.90) is not None

def test_effective_memory_never_all_dropped_at_mid_similarity():
    s = RecallScorer()
    got = [s.score(mk(confidence=c, importance=i), 0.75, now=NOW)
           for c in (0.5, 0.7, 0.9) for i in (0.3, 0.6, 0.9)]
    assert all(x is not None for x in got)

def test_score_does_not_mutate_memory():
    s = RecallScorer(); m = mk()
    before = dataclasses.asdict(m) if (dataclasses := __import__("dataclasses")) else None
    out = s.score(m, 0.93, now=NOW)
    assert dataclasses.asdict(m) == before
    assert out.score != getattr(m, "weight_score", None)

def test_invalidated_memory_not_recalled():
    s = RecallScorer()
    dead = dataclasses.replace(mk(), valid_until=NOW - 1) if (dataclasses := __import__("dataclasses")) else None
    assert s.score(dead, 0.99, now=NOW) is None
