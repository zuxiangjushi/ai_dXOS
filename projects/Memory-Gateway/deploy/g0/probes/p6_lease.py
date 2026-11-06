import httpx, asyncio
from .base import ProbeResult

async def run(cfg):
    r = ProbeResult("P6", "GPU 租约仲裁（Pilot 侧待实现）")
    a = cfg["base"]["admin_url"]
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            st = await c.get(a + "/api/gpu/state")
    except Exception as e:
        r.passed, r.reason = False, f"接口不存在/超时：{str(e)[:60]}"
        r.hint = ("把 deploy/g0/probes/reference_lease_arbiter.py（约30行）交底座团队实现 "
                  "GET /api/gpu/state、POST /api/gpu/lease、DELETE /api/gpu/lease/{id}；不阻塞其他工作")
        return r
    if st.status_code != 200:
        r.passed, r.reason = False, f"/api/gpu/state 返回 {st.status_code}"
        r.hint = "待 Pilot 实现"; return r
    async with httpx.AsyncClient(timeout=10) as c:
        h1 = await c.post(a + "/api/gpu/lease", json={"holder": "probe-a", "need_gb": 24, "ttl_s": 60})
        h2 = await c.post(a + "/api/gpu/lease", json={"holder": "probe-b", "need_gb": 24, "ttl_s": 60})
        j1, j2 = h1.json(), h2.json()
        r.metrics.update({"probe_a_granted": j1.get("granted"), "probe_b_granted": j2.get("granted"),
                          "retry_after_s": j2.get("retry_after_s")})
        both = j1.get("granted") and j2.get("granted")
        await c.delete(a + "/api/gpu/lease/probe-a")
        r.passed = (not both) and j1.get("granted") is True and j2.get("granted") is False
        r.reason = "互斥成立且被拒方拿到 retry_after_s" if r.passed else "互斥或排队语义未满足"
        if not r.passed: r.hint = "Pilot 侧检查 Redis SET NX 与 ttl 计算"
    return r
