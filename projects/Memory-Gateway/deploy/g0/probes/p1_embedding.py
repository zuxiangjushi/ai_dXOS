import httpx, yaml, os
from .base import ProbeResult, Timer

def load_disc():
    p = "deploy/g0/config/g0_discovered.yaml"
    return (yaml.safe_load(open(p)) or {}) if os.path.exists(p) else {}

def parse_dim(d):
    if isinstance(d, list) and d and isinstance(d[0], list):
        return len(d[0])
    if isinstance(d, dict):
        v = d.get("data")
        if isinstance(v, list) and v:
            x = v[0]
            if isinstance(x, dict) and isinstance(x.get("embedding"), list):
                return len(x["embedding"])
            if isinstance(x, list):
                return len(x)
    return None

async def run(cfg):
    r = ProbeResult("P1", "嵌入通路")
    d = load_disc()
    if not d.get("emb_url"):
        r.passed, r.reason = None, "未发现嵌入端点，先跑 scripts/03c_find_embed.py"
        return r
    field = d.get("emb_field", "input")
    payload = {field: ["错误码 E1042 表示网关超时，需调整 max_context"]}
    if d.get("emb_model"):
        payload["model"] = d["emb_model"]
    t = Timer()
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await c.post(d["emb_url"], json=payload)
            if resp.status_code != 200:
                r.passed, r.reason = False, f"HTTP {resp.status_code} {resp.text[:90]}"
                r.hint = "重跑 scripts/03c_find_embed.py"
                return r
            dim = parse_dim(resp.json())
            r.metrics = {"mode": d.get("emb_mode"), "url": d["emb_url"],
                         "model": d.get("emb_model"), "dim": dim}
            want = d.get("emb_dim") or cfg["expected_dim"]
            if dim != want:
                r.passed, r.reason = False, f"维度 {dim} != 期望 {want}"
                r.hint = "向量集合维度必须与嵌入模型一致，改 expected_dim 并重建集合"
                return r
            for _ in range(30):
                await t.a(c.post, d["emb_url"], json=payload)
    except Exception as e:
        r.passed, r.reason = False, f"{type(e).__name__}: {str(e)[:90]}"
        return r
    lim = cfg["budgets"]["embed_p95"]
    r.metrics.update({"p50": t.p50, "p95": t.p95})
    r.passed = t.p95 is not None and t.p95 <= lim
    r.reason = f"嵌入可用(原生) P95={t.p95}ms（门禁{lim}）"
    if not r.passed:
        r.hint = "CPU 嵌入偏慢：常驻预热+批量；读路径超时走关键词兜底"
    return r
