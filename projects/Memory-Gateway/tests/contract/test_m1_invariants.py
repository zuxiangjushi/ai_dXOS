import asyncio, time
import pytest

from contracts.credentials import PROFILES
from contracts.errors import ModelNotAllowed, PoolBusy
from app.use_cases.pool_route import PoolRouter

PKGS = {
    "qwen3_32b": {"cold_start_seconds": 95},
    "qwen38_27b_f8": {"cold_start_seconds": 80},
}
KEY = {"model_allowlist": ["qwen3_32b", "qwen38_27b_f8"], "allow_silent_fallback": False}


class FakePilot:
    def __init__(self, ids):
        self.ids = set(ids)

    async def list_models(self, ttl=60):
        return set(self.ids)


class DownPilot:
    async def list_models(self, ttl=60):
        from contracts.errors import PilotUnavailable
        raise PilotUnavailable("down")


def rt(models):
    return PoolRouter(FakePilot(models), packages=PKGS)


def test_explicit_model_never_silently_swapped():
    with pytest.raises(PoolBusy) as e:
        asyncio.run(rt([]).route("qwen3_32b", KEY))
    assert e.value.retry_after_s > 0


def test_resident_model_used_directly():
    d = asyncio.run(rt(["qwen3_32b"]).route("qwen3_32b", KEY))
    assert d.model_id == "qwen3_32b" and d.downgraded is False


def test_model_not_in_allowlist_rejected():
    with pytest.raises(ModelNotAllowed):
        asyncio.run(rt(["qwen3_32b"]).route("deepseek_70b", KEY))


def test_sticky_pins_resident_model():
    sess = {"resident_model": "qwen38_27b_f8", "pinned_until": int(time.time()) + 900}
    d = asyncio.run(rt(["qwen38_27b_f8"]).route("qwen3_32b", KEY, sess))
    assert d.model_id == "qwen38_27b_f8" and "sticky" in d.note


def test_pilot_down_keeps_last_snapshot_and_no_crash():
    r = PoolRouter(DownPilot(), packages=PKGS)
    r.snapshot = {"ts": time.time(), "seen": {"qwen3_32b"}, "resident": {"qwen3_32b"}}
    d = asyncio.run(r.route("qwen3_32b", KEY))
    assert d.model_id == "qwen3_32b"


def test_comfyui_profile_has_zero_memory_and_load():
    p = PROFILES["comfyui_desktop"]
    assert not p.memory_inject and not p.memory_writeback
    assert not p.allow_load and p.pre_call_budget_ms == 50


def test_op_decision_belongs_to_rules_not_model():
    from contracts.t0_rules import classify_tier as c
    assert c("忘掉之前那条").rule == "forget"
    assert c("我不再用pgvector").rule == "negation_flip"
