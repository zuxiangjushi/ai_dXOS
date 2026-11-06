import time
import yaml

from contracts.routing import RouteDecision
from contracts.errors import ModelNotAllowed, PoolBusy, PilotUnavailable

DEFAULT_PKGS = {
    "38FN_Q4": {"pool": "Pool-ALL", "cold_start_seconds": 300, "safe_default": True},
    "qwen3_32b": {"pool": "Pool-A", "cold_start_seconds": 95},
    "yy35b_q6": {"pool": "Pool-A", "cold_start_seconds": 95},
    "qwen38_27b_f8": {"pool": "Pool-B", "cold_start_seconds": 80},
}

class PoolRouter:
    """A 模式：显式指定模型 = 单元素候选集；禁止静默换模型；依赖底座池状态 [2]。"""

    def __init__(self, pilot, packages=None, packages_path="config/model_packages.yaml",
                 snapshot_ttl=300, queue_budget_ms=20000):
        self.pilot = pilot
        if packages is None:
            packages = self._load(packages_path)
        self.pkgs = packages or DEFAULT_PKGS
        self.snapshot_ttl = snapshot_ttl
        self.queue_budget_ms = queue_budget_ms
        self.snapshot = {"ts": 0.0, "resident": set(), "seen": set()}

    @staticmethod
    def _load(path):
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except (FileNotFoundError, ValueError):
            return {}

    async def refresh(self):
        try:
            ids = set(await self.pilot.list_models())
            self.snapshot = {
                "ts": time.time(),
                "seen": ids,
                "resident": ids & set(self.pkgs.keys()),
            }
        except PilotUnavailable:
            pass
        return self.snapshot

    def _stale(self):
        return (time.time() - float(self.snapshot.get("ts") or 0)) > self.snapshot_ttl

    async def route(self, model, key, session=None):
        snap = await self.refresh()
        resident = set(snap.get("resident") or set())
        allow_raw = key.get("model_allowlist") or []
        allowed = set(allow_raw) if isinstance(allow_raw, (list, tuple, set)) else set()
        if model not in allowed:
            raise ModelNotAllowed(model, allowed)

        if self._stale():
            safe = self.pkgs.get(model, {}).get("safe_default")
            if resident and model not in resident:
                alt = sorted(resident & allowed)
                if alt:
                    return RouteDecision(alt[0], 0, True, "fail_static_snapshot_stale")
            if not safe:
                raise PoolBusy(model, self.pkgs.get(model, {}).get("cold_start_seconds", 120),
                               sorted(resident & allowed))

        pinned = (session or {}).get("resident_model")
        if pinned in resident and pinned in allowed and \
                int((session or {}).get("pinned_until") or 0) > time.time():
            return RouteDecision(pinned, 0, False, "sticky_reuse")

        if model in resident:
            return RouteDecision(model, 0, False, "explicit_ready")

        eta = int(self.pkgs.get(model, {}).get("cold_start_seconds", 120))
        if eta * 1000 > self.queue_budget_ms:
            if not key.get("allow_silent_fallback"):
                raise PoolBusy(model, eta, sorted(resident & allowed))
            alt = sorted(resident & allowed)
            if alt:
                return RouteDecision(alt[0], 0, True, "silent_fallback_authorized")
            raise PoolBusy(model, eta, [])
        return RouteDecision(model, eta * 1000, False, "cold_start_queued")
