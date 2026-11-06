"""交给底座团队的参考实现：Pilot 唯一有权仲裁显存，网关只申请。"""
import time
KEY = "gpu:lease"

async def acquire(r, holder, need_gb, ttl_s=900, mode="preempt_llm"):
    cur = await r.hgetall(KEY)
    if not cur:
        await r.hset(KEY, mapping={"holder": holder, "gb": need_gb, "since": int(time.time())})
        await r.expire(KEY, ttl_s)
        return {"granted": True, "lease_id": holder}
    if cur["holder"] == holder:
        await r.expire(KEY, ttl_s)
        return {"granted": True, "lease_id": holder, "renewed": True}
    remain = int(await r.ttl(KEY) or 0)
    return {"granted": False, "holder": cur["holder"], "retry_after_s": max(5, remain),
            "drain_eta_s": 20 if mode == "preempt_llm" else None}

async def release(r, lease_id):
    cur = await r.hgetall(KEY)
    if cur and cur.get("holder") == lease_id:
        await r.delete(KEY); return {"released": True}
    return {"released": False, "reason": "not holder"}
