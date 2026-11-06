import httpx, yaml, os, time
GW = "http://192.168.10.132:9980"
CONF = os.getenv("KEYS_CONF", "/ai/ai_dxos/secrets/keys.conf")
keys = {}
for line in open(CONF):
    line = line.strip()
    if line.startswith("KEY_") and "=" in line:
        k, v = line.split("=", 1)
        keys[k] = v.strip().strip('"')
print("载入密钥数:", len(keys))
rows, emb_ok, chat_ok = [], [], []
with httpx.Client(timeout=25) as c:
    for ref, k in keys.items():
        h = {"Authorization": f"Bearer {k}"}
        try:
            r = c.get(GW + "/v1/models", headers=h)
            models = [m["id"] for m in r.json().get("data", [])] if r.status_code == 200 else []
            st = r.status_code
        except Exception as e:
            models, st = [], type(e).__name__
        print(f"{ref:<22} modelsHTTP={st} 可见={models}")
        for m in models:
            try:
                er = c.post(GW + "/v1/embeddings", headers=h,
                            json={"model": m, "input": ["hello"]}, timeout=20)
                dim = len(er.json()["data"][0]["embedding"]) if er.status_code == 200 else None
            except Exception:
                dim = None
            try:
                cr = c.post(GW + "/v1/chat/completions", headers=h, json={
                    "model": m, "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1}, timeout=25)
                chat = cr.status_code
            except Exception:
                chat = None
            rows.append((ref, m, dim, chat))
            if dim: emb_ok.append((ref, m, dim))
            if chat == 200: chat_ok.append((ref, m))
print("\n--- 可_embeddings 的 key+模型 ---")
for x in emb_ok: print("  ", x)
print("--- 可_chat 的 key+模型 ---")
for x in chat_ok[:12]: print("  ", x)
print("\n--- 直连 8003 路由探测（Infinity 原生）---")
for path, method in [("/health", "get"), ("/", "get"), ("/v1/models", "get"),
                     ("/models", "get"), ("/v1/embeddings", "post"), ("/embed", "post")]:
    try:
        r = getattr(httpx, method)("http://192.168.10.132:8003" + path,
                                   json={"input": ["hello"], "model": "bge-m3"}, timeout=8)
        print(f"  {method.upper():4} {path:<18} {r.status_code} {r.text[:90]}")
    except Exception as e:
        print(f"  {method.upper():4} {path:<18} ERR {str(e)[:50]}")
if emb_ok:
    best = next((x for x in emb_ok if x[2] == 1024), emb_ok[0])
    out = {"emb_key_ref": best[0], "emb_model": best[1], "emb_dim": best[2]}
    pref = next((x for x in chat_ok if "30b" in x[1] or "32b" in x[1]),
                chat_ok[0] if chat_ok else None)
    if pref: out.update({"judge_key_ref": pref[0], "judge_model": pref[1]})
    yaml.safe_dump(out, open("deploy/g0/config/g0_discovered.yaml", "w"),
                   allow_unicode=True)
    print("\n已写入 deploy/g0/config/g0_discovered.yaml ->", out)
else:
    print("\n⚠️ 没有任何 key 能做 embeddings：需底座在 LiteLLM 注册 embeddings 能力，或给直连 Infinity 的权限")
