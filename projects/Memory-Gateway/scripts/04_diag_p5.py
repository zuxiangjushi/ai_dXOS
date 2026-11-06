import httpx
GW = "http://192.168.10.132:9980"
k = [l.split("=",1)[1].strip().strip('"') for l in open("/ai/ai_dxos/secrets/keys.conf") if l.startswith("KEY_qwen3_32b")][0]
SCHEMA = {"name":"facts","schema":{"type":"object","additionalProperties":False,"required":["facts"],
 "properties":{"facts":{"type":"array","items":{"type":"object","additionalProperties":False,
 "required":["op","entity_key","memory_class","content","confidence"],
 "properties":{"op":{"type":"string","enum":["ADD","UPDATE","DELETE","NOOP"]},
 "entity_key":{"type":"string"},
 "memory_class":{"type":"string","enum":["fact","preference","decision","procedure","episode"]},
 "content":{"type":"string"},"confidence":{"type":"number"}}}}}}}
Q = '抽取事实，只输出JSON：{"facts":[{"op":"ADD","entity_key":"x","memory_class":"fact","content":"项目用Qdrant","confidence":0.9}]}'
with httpx.Client(timeout=120) as c:
    for tag, extra in [("裸提示词", {}), ("json_object", {"response_format":{"type":"json_object"}}),
                       ("json_schema", {"response_format":{"type":"json_schema","json_schema":SCHEMA}})]:
        p = {"model":"38FN_Q4","messages":[{"role":"user","content":Q}],"max_tokens":300,"temperature":0}
        p.update(extra)
        r = c.post(GW+"/v1/chat/completions", headers={"Authorization":f"Bearer {k}"}, json=p)
        print("###", tag, "HTTP", r.status_code)
        if r.status_code != 200: print(r.text[:300])
        else: print(repr(r.json()["choices"][0]["message"].get("content"))[:300])
