"""把 20 角色 × 25 会话灌入 Mem0（供 M4 对照）"""
import asyncio
import json
import hashlib
import os
import httpx

MEM0_URL = os.environ.get("MEM0_URL", "http://127.0.0.1:8888")
MEM0_KEY = os.environ.get("MEM0_ADMIN_KEY", "")


def user_id_for(persona):
    """M4 用 ws_for(persona)，Mem0 版用 user_id 对齐"""
    return "eval_" + hashlib.md5(persona.encode()).hexdigest()[:8]


async def main():
    personas = json.load(open("evals/datasets/personas_20.json"))
    total = sum(len(p["sessions"]) for p in personas)
    print(f"📦 待灌入: {total} 条 / {len(personas)} 角色")

    ok, fail = 0, 0
    async with httpx.AsyncClient(timeout=120) as c:
        for p in personas:
            uid = user_id_for(p["persona"])
            for i, sess in enumerate(p["sessions"]):
                try:
                    r = await c.post(
                        f"{MEM0_URL}/memories",
                        headers={"X-API-Key": MEM0_KEY},
                        json={
                            "messages": [{"role": "user", "content": sess["content"]}],
                            "user_id": uid,
                            "metadata": {"persona": p["persona"], "ts": sess["ts"]},
                        })
                    if r.status_code in (200, 201):
                        ok += 1
                    else:
                        fail += 1
                        if fail <= 3:
                            print(f"  ❌ HTTP {r.status_code}: {r.text[:100]}")
                except Exception as e:
                    fail += 1
                    if fail <= 3:
                        print(f"  ❌ {type(e).__name__}: {e}")

                if (ok + fail) % 50 == 0:
                    print(f"  进度: {ok+fail}/{total} ok={ok} fail={fail}")

    print(f"\n✅ 完成: ok={ok}, fail={fail}")


if __name__ == "__main__":
    asyncio.run(main())
