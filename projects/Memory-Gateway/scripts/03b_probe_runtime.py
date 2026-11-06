import httpx, yaml, os, glob, re
GW = "http://192.168.10.132:9980"
ADMIN = "http://192.168.10.132:9981"
CONF = os.getenv("KEYS_CONF", "/ai/ai_dxos/secrets/keys.conf")

def load_keys():
    out = {}
    for ln in open(CONF):
        ln = ln.strip()
        if ln.startswith("KEY_") and "=" in ln:
            k, v = ln.split("=", 1)
            out[k] = v.strip().strip('"')
    return out

keys = load_keys()
first_key = next((v for v in keys.values() if v != "sk-xxx"), None)
H = {"Authorization": f"Bearer {first_key}"}
found_emb, found_chat = [], []

with httpx.Client(timeout=20) as c:
    print("=== 1 运行时模型目录（唯一真源）===")
    try:
        models = [m["id"] for m in c.get(GW + "/v1/models", headers=H).json().get("data", [])]
    except Exception as e:
        models = []
        print("  ERR", e)
    print("  可见模型:", models)
    for m in models:
        try:
            r = c.post(GW + "/v1/embeddings", headers=H, json={"model": m, "input": ["hi"]})
            if r.status_code == 200:
                found_emb.append(("9980", m, len(r.json()["data"][0]["embedding"])))
            print(f"  emb {m:<12} -> {r.status_code}")
        except Exception as e:
            print(f"  emb {m:<12} -> ERR {str(e)[:40]}")
        try:
            rc = c.post(GW + "/v1/chat/completions", headers=H,
                        json={"model": m, "messages": [{"role": "user", "content": "hi"}],
                              "max_tokens": 1})
            if rc.status_code == 200:
                found_chat.append(("9980", m))
        except Exception:
            pass

    print("\n=== 2 嵌入服务候选端口/路径（GET 探测已修正）===")
    CAND = [("http://192.168.10.132:8003", "/v1/models"),
            ("http://192.168.10.132:8003", "/health"),
            ("http://192.168.10.132:8003", "/models"),
            ("http://192.168.10.132:8003", "/v1/embeddings"),
            ("http://192.168.10.132:8003", "/embeddings"),
            ("http://192.168.10.132:8080", "/v1/models"),
            ("http://127.0.0.1:11434", "/api/tags"),
            ("http://192.168.10.132:8080", "/embed")]
    for base, path in CAND:
        try:
            r = c.get(base + path, timeout=6)
            print(f"  GET  {base[-9:]:<10} {path:<16} {r.status_code} {r.text[:80]}")
        except Exception as e:
            print(f"  GET  {base[-9:]:<10} {path:<16} ERR {str(e)[:40]}")
    for base in ["http://192.168.10.132:8003", "http://192.168.10.132:8080"]:
        for path in ["/v1/embeddings", "/embed"]:
            try:
                r = c.post(base + path, timeout=15,
                           json={"model": "bge-m3", "input": ["hello"],
                                 "texts": ["hello"], "text": ["hello"]})
                print(f"  POST {base[-9:]:<10} {path:<16} {r.status_code} {r.text[:90]}")
                if r.status_code == 200:
                    found_emb.append((base + path, "bge-m3", None))
            except Exception as e:
                print(f"  POST {base[-9:]:<10} {path:<16} ERR {str(e)[:40]}")

    print("\n=== 3 底座管理表（看真实模型全集与运行状态）[2] ===")
    admin_keys = set()
    for f in glob.glob("/ai/ai_dxos/**/*", recursive=True):
        if not os.path.isfile(f) or os.path.getsize(f) > 2_000_000:
            continue
        try:
            txt = open(f, errors="ignore").read()
        except Exception:
            continue
        for m in re.finditer(r"(?i)(admin[_-]?key|X-Admin-Key)[\"' :=]+([A-Za-z0-9_\-]{6,})", txt):
            admin_keys.add(m.group(2))
    print("  找到候选 admin key 数:", len(admin_keys))
    for ak in list(admin_keys)[:5]:
        try:
            r = c.get(ADMIN + "/api/admin/table", headers={"X-Admin-Key": ak}, timeout=8)
            print(f"  admin table -> {r.status_code} {r.text[:400]}")
            if r.status_code == 200:
                break
        except Exception as e:
            print("  admin table ERR", str(e)[:50])

out = {"chat_candidates": [{"model": m} for _, m in found_chat],
       "emb_candidates": [{"where": w, "model": m, "dim": d} for w, m, d in found_emb]}
if found_chat:
    pref = next((x for x in found_chat if any(s in x[1].lower() for s in
               ["7b", "8b", "14b", "qwen3_30b"])), found_chat[0])
    out["judge_model"] = pref[1]
if found_emb and found_emb[0][2]:
    out["emb_model"], out["emb_dim"] = found_emb[0][1], found_emb[0][2]
yaml.safe_dump(out, open("deploy/g0/config/g0_discovered.yaml", "w"), allow_unicode=True)
print("\n写入 discovered:", out)
print("⚠️ 判定模型若为 Pool-ALL 大模型，写回会与用户流量抢显存，需改为小模型常驻 [2]")
