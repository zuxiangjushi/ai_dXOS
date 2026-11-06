import hashlib, hmac, os, secrets, time
import asyncpg
from contracts.errors import Unauthorized, ScopeViolation

PEPPER = os.environ["DXOS_PEPPER"].encode()

def _hash(secret): return hmac.new(PEPPER, secret.encode(), hashlib.sha256).hexdigest()

class KeyService:
    def __init__(self, dsn, cache=None):
        self.dsn, self.cache = dsn, cache

    async def _conn(self): return await asyncpg.connect(self.dsn)

    async def issue(self, user_id, workspace_id, agent_type, models, scopes,
                    default_model, workspaces=None, ttl_days=365, label="",
                    quota_tokens=1000000, rate_qps=10):
        key_id, raw = secrets.token_hex(8), secrets.token_urlsafe(32)
        now = int(time.time())
        conn = await self._conn()
        try:
            await conn.execute(
                """INSERT INTO api_keys(key_id,key_hash,user_id,workspace_id,agent_type,
                   allowed_workspace_ids,model_allowlist,scopes,default_model,quota_tokens,
                   rate_qps,expires_at,created_at,updated_at)
                   VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10,$11,$12,$13,$14)""",
                key_id, _hash(raw), user_id, workspace_id, agent_type,
                _json(list(workspaces or [workspace_id])), _json(list(models)),
                _json(list(scopes)), default_model, quota_tokens, rate_qps,
                now + ttl_days * 86400, now, now)
        finally:
            await conn.close()
        return "sk-dx-" + key_id + "." + raw

    async def authenticate(self, bearer):
        if not bearer or not bearer.startswith("sk-dx-"):
            raise Unauthorized("格式不符")
        try:
            key_id, raw = bearer[6:].split(".", 1)
        except ValueError:
            raise Unauthorized("格式不符")
        ck = "keybind:" + key_id
        rec = await self.cache.get(ck) if self.cache else None
        if rec is None:
            conn = await self._conn()
            try:
                row = await conn.fetchrow("SELECT * FROM api_keys WHERE key_id=$1", key_id)
            finally:
                await conn.close()
            if not row:
                raise Unauthorized("key 不存在")
            rec = dict(row)
            if self.cache:
                await self.cache.set(ck, rec, ex=60)
        if rec["is_revoked"] or (rec["expires_at"] and rec["expires_at"] < time.time()):
            raise Unauthorized("已撤销或过期")
        if _hash(raw) != rec["key_hash"]:
            raise Unauthorized("密钥不匹配")
        return rec

    async def revoke(self, key_id):
        conn = await self._conn()
        try:
            await conn.execute("UPDATE api_keys SET is_revoked=TRUE, updated_at=$2,"
                               " label_version=label_version+1 WHERE key_id=$1",
                               key_id, int(time.time()))
        finally:
            await conn.close()
        if self.cache:
            await self.cache.delete("keybind:" + key_id)
            await self.cache.set("revoked:" + key_id, "1", ex=3600)

def _json(v):
    import json; return json.dumps(v, ensure_ascii=False)
