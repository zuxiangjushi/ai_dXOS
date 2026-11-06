import httpx, json, yaml
B = "http://192.168.10.132:8003"
PATHS = ["/embeddings", "/embed", "/encode", "/v1/embeddings"]
MODELS = ["models/bge-m3", "bge-m3", None]
FIELDS = ["input", "texts", "text", "inputs"]
good = None
with httpx.Client(timeout=25) as c:
    for p in PATHS:
        for m in MODELS:
            for f in FIELDS:
                payload = {f: ["错误码 E1042 表示网关超时"]}
                if m: payload["model"] = m
                try:
                    r = c.post(B + p, json=payload)
                except Exception:
                    continue
                if r.status_code != 200:
                    continue
                d = r.json()
                dim = None
                if isinstance(d, list) and d and isinstance(d[0], list):
                    dim = len(d[0])
                elif isinstance(d, dict) and isinstance(d.get("data"), list) and d["data"]:
                    dim = len(d["data"][0].get("embedding", []))
                elif isinstance(d, dict) and isinstance(d.get("data"), list) and d["data"] \
                        and isinstance(d["data"][0], list):
                    dim = len(d["data"][0])
                if dim:
                    good = {"url": B + p, "field": f, "model": m, "dim": dim}
                    print("命中:", good)
                    break
            if good: break
        if good: break
if not good:
    print("未命中任何组合，把下面诊断贴回来：")
    with httpx.Client(timeout=15) as c:
        for p in PATHS:
            try:
                r = c.post(B + p, json={"model": "models/bge-m3", "input": ["hi"]})
                print(p, r.status_code, r.text[:120])
            except Exception as e:
                print(p, "ERR", str(e)[:60])
else:
    out = {"emb_mode": "infinity_native", "emb_url": good["url"],
           "emb_field": good["field"], "emb_model": good["model"], "emb_dim": good["dim"]}
    old = {}
    try:
        old = yaml.safe_load(open("deploy/g0/config/g0_discovered.yaml")) or {}
    except Exception:
        pass
    out.setdefault("judge_model", old.get("judge_model", "38FN_Q4"))
    yaml.safe_dump(out, open("deploy/g0/config/g0_discovered.yaml", "w"), allow_unicode=True)
    print("已写入 g0_discovered.yaml ->", out)
