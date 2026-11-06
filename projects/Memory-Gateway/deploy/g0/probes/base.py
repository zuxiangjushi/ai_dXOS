import os, time, statistics as st
from dataclasses import dataclass, field

@dataclass
class ProbeResult:
    pid: str; name: str
    passed: bool | None = None
    metrics: dict = field(default_factory=dict)
    reason: str = ""; hint: str = ""

def p(vals, q=95):
    if not vals: return None
    if len(vals) < 2: return round(vals[0], 2)
    return round(st.quantiles(vals, n=100)[q-1], 2)

class Timer:
    def __init__(self): self.samples = []
    async def a(self, fn, *a, **k):
        t0 = time.perf_counter(); out = await fn(*a, **k)
        self.samples.append((time.perf_counter()-t0)*1000); return out
    @property
    def p95(self): return p(self.samples, 95)
    @property
    def p50(self): return p(self.samples, 50)

def env(name, default=None):
    v = os.getenv(name)
    if not v and default is None: raise RuntimeError(f"环境变量 {name} 未设置")
    return v or default

KEYS_CONF = os.getenv("KEYS_CONF", "/ai/ai_dxos/secrets/keys.conf")
_secrets = {}
def secret(ref):
    if not _secrets:
        try:
            for ln in open(KEYS_CONF):
                ln = ln.strip()
                if ln.startswith("KEY_") and "=" in ln:
                    k, v = ln.split("=", 1)
                    _secrets[k] = v.strip().strip('"')
        except FileNotFoundError:
            pass
    v = os.getenv(ref) or _secrets.get(ref)
    if not v:
        raise RuntimeError("找不到密钥 " + str(ref) + "，检查 " + KEYS_CONF)
    return v

def discovered():
    p = "deploy/g0/config/g0_discovered.yaml"
    if not os.path.exists(p):
        return {}
    import yaml as y
    return y.safe_load(open(p)) or {}
