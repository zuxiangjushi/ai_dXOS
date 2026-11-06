import httpx, time
from contracts.errors import PilotUnavailable, ModelNotAllowed

class PilotAdapter:
    def __init__(self, base_url, api_key, timeout=90):
        self._c = httpx.AsyncClient(base_url=base_url, timeout=timeout,
                                    headers={"Authorization": "Bearer " + api_key})
        self._models_cache = {"ids": set(), "ts": 0}

    async def list_models(self, ttl=60):
        if time.time() - self._models_cache["ts"] < ttl:
            return self._models_cache["ids"]
        try:
            r = await self._c.get("/v1/models")
            ids = {m["id"] for m in r.json().get("data", [])}
            self._models_cache.update({"ids": ids, "ts": time.time()})
            return ids
        except Exception as e:
            raise PilotUnavailable(str(e)[:120])

    async def infer(self, model, messages, parameters=None, response_format=None):
        payload = {"model": model, "messages": messages,
                   **(parameters or {})}
        if response_format:
            payload["response_format"] = response_format
        try:
            r = await self._c.post("/v1/chat/completions", json=payload)
        except Exception as e:
            raise PilotUnavailable(type(e).__name__ + ": " + str(e)[:110])
        if r.status_code == 400 and "Invalid model name" in r.text:
            self._models_cache["ts"] = 0
            raise ModelNotAllowed(model, await self.list_models(0))
        if r.status_code != 200:
            raise PilotUnavailable("HTTP " + str(r.status_code) + " " + r.text[:100])
        ch = r.json()["choices"][0]
        msg = ch.get("message", {})
        return {
            "content": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or "",
            "finish_reason": ch.get("finish_reason"),
            "usage": r.json().get("usage") or {},
        }
