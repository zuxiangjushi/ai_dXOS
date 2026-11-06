import asyncio, time
from .base import ProbeResult, p

async def measure(seconds):
    lags, stop = [], False
    async def mon():
        while not stop:
            t0 = time.perf_counter()
            await asyncio.sleep(0.01)
            lags.append((time.perf_counter() - t0 - 0.01) * 1000)
    m = asyncio.create_task(mon())
    await asyncio.sleep(seconds)
    stop = True
    await m
    return lags

async def run(cfg):
    r = ProbeResult("P8", "事件循环延迟")
    from qdrant_client import AsyncQdrantClient
    floor = await measure(2.0)
    qc = AsyncQdrantClient(url=cfg["stores"]["qdrant_url"])
    coll = cfg["stores"]["qdrant_collection"]
    done = {"f": False}
    async def worker():
        while not done["f"]:
            try:
                await qc.count(coll, exact=False)
            except Exception:
                pass
            await asyncio.sleep(0)
    ts = [asyncio.create_task(worker()) for _ in range(50)]
    busy = await measure(3.0)
    done["f"] = True
    await asyncio.gather(*ts, return_exceptions=True)
    lim = cfg["budgets"]["eventloop_lag_p95"]
    fp, bp = p(floor, 95), p(busy, 95)
    inc = round(bp - fp, 2) if fp is not None and bp is not None else None
    r.metrics = {"空闲地板_p95": fp, "并发50_p95": bp, "自身增量": inc}
    r.passed = inc is not None and inc <= lim
    r.reason = f"地板={fp}ms 并发={bp}ms 增量={inc}ms（门禁 增量<={lim}）"
    if not r.passed:
        r.hint = "增量超标才是网关阻塞；地板高属主机负载问题"
    return r
