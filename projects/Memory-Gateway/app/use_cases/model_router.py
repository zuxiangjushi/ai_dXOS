"""池感知路由 + 参数治理"""
import yaml
from pathlib import Path
from typing import Optional, Tuple


class ModelRouter:
    def __init__(self, packages_path: str = "config/model_packages.yaml"):
        self.pkgs = self._load(packages_path)

    def _load(self, path):
        p = Path(path)
        if not p.exists():
            return {}
        try:
            return yaml.safe_load(p.read_text()) or {}
        except Exception:
            return {}

    def resolve(self, requested: str, preferred_pool: Optional[str] = None,
                allow_fallback: bool = True) -> Tuple[str, bool, str]:
        """返回 (model, downgraded, note)"""
        if not self.pkgs:
            return requested, False, "no_packages"

        if preferred_pool:
            in_pool = [m for m, cfg in self.pkgs.items()
                       if (cfg or {}).get("pool") == preferred_pool]
            if requested in in_pool:
                return requested, False, f"pool={preferred_pool}"
            if in_pool and allow_fallback:
                return in_pool[0], True, f"fallback_to_{in_pool[0]}"
            return requested, False, f"pool={preferred_pool}_no_match"

        return requested, False, "passthrough"

    def describe(self) -> dict:
        out = {}
        for m, cfg in self.pkgs.items():
            out[m] = {
                "pool": (cfg or {}).get("pool", "?"),
                "engine": (cfg or {}).get("engine", "?"),
                "cold_start_seconds": (cfg or {}).get("cold_start_seconds", 0),
            }
        return out
