import httpx
from .base import ProbeResult, Timer

async def run(cfg):
    r = ProbeResult("P2", "CPU 重排延迟")
    c0 = cfg["rerank"]["candidates"]; ln = cfg["rerank"]["doc_chars"]
    docs = [f"候选片段 {i}：" + "记忆检索与上下文预算的说明文本。" * (ln // 16)
            for i in range(c0)]
    t = Timer()
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            for _ in range(20):
                await t.a(c.post, cfg["rerank"]["url"],
                          json={"query": "max_context 默认值", "documents": docs})
    except Exception as e:
        r.passed, r.reason = False, f"重排服务不可达：{str(e)[:70]}"
        r.hint = "重排容器尚未部署，属预期；Week2 起 CPU 版 bge-reranker-v2-m3"
        return r
    lim = cfg["budgets"]["rerank_p95"]
    r.metrics.update({"p50": t.p50, "p95": t.p95, "候选数": c0})
    r.passed = t.p95 is not None and t.p95 <= lim
    r.reason = f"P95={t.p95}ms (门禁{lim}，候选{c0})"
    if not r.passed:
        r.metrics["建议候选数"] = max(8, int(c0 * lim / max(t.p95, 1)))
        r.hint = "降候选数或缩短片段长度；融合分 top1 优势>0.25 时跳过重排"
    return r
