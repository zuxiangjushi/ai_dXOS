import httpx, os, yaml

def _disc():
    p = "deploy/g0/config/g0_discovered.yaml"
    return (yaml.safe_load(open(p)) or {}) if os.path.exists(p) else {}

def parse_vec(body):
    if isinstance(body, list) and body and isinstance(body[0], list):
        return body[0]
    d = body.get("data") if isinstance(body, dict) else None
    if isinstance(d, list) and d:
        x = d[0]
        return x.get("embedding") if isinstance(x, dict) else x
    raise ValueError("无法解析向量返回结构")

class EmbedClient:
    """嵌入服务：G0 实测走原生 /embeddings，1024 维，P95≈93ms。"""
    def __init__(self, url=None, model=None, field=None, dim=1024, timeout=3.0):
        d = _disc()
        self.url = url or d.get("emb_url")
        self.model = model or d.get("emb_model")
        self.field = field or d.get("emb_field", "input")
        self.dim, self.timeout, self._c = dim, timeout, None
        if not self.url:
            raise RuntimeError("缺少 emb_url，先跑 scripts/03c_find_embed.py")

    def _client(self):
        if self._c is None:
            self._c = httpx.AsyncClient(timeout=self.timeout)
        return self._c

    async def embed(self, text):
        payload = {self.field: [text]}
        if self.model:
            payload["model"] = self.model
        r = await self._client().post(self.url, json=payload)
        if r.status_code != 200:
            raise RuntimeError("嵌入失败 HTTP %s %s" % (r.status_code, r.text[:80]))
        v = parse_vec(r.json())
        if len(v) != self.dim:
            raise RuntimeError("维度 %d != %d" % (len(v), self.dim))
        return v
