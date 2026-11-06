import dataclasses, time
import pytest
from contracts.scope import MemoryScope, narrow_scope
from contracts.memory import new_memory, Trust, MemoryRecord
from contracts.errors import ScopeViolation
from contracts.credentials import PROFILES, IssuedKey
from contracts.context import LAYOUT, DEGRADE_ORDER
from contracts.plan import AuthorizedPlan
from contracts.routing import RouteDecision

def mk_scope(): return MemoryScope(user_id="u1", workspace_id="ws_a", project_id="p1")

def test_scope_requires_workspace():
    with pytest.raises(TypeError): MemoryScope(user_id="u1")

def test_header_cannot_escalate_workspace():
    with pytest.raises(ScopeViolation): narrow_scope(mk_scope(), {"X-Workspace-Id": "ws_b"})

def test_header_can_narrow_project():
    s = narrow_scope(mk_scope(), {"X-Project-Id": "p1"})
    assert s.project_id == "p1"

def test_scope_filter_pushes_tenant_down():
    f = mk_scope().as_filter()
    assert f["workspace_id"] == "ws_a" and f["user_id"] == "u1"

def test_stale_memory_not_effective():
    now = int(time.time())
    m = new_memory(mk_scope(), "旧偏好", "user.pref.db")
    m2 = dataclasses.replace(m, superseded_by="mem_x")
    m3 = dataclasses.replace(m, valid_until=now - 1)
    assert m.is_effective(now) and not m2.is_effective(now) and not m3.is_effective(now)

def test_trust_propagation_takes_weakest():
    assert Trust.TRUSTED.weakest(Trust.UNTRUSTED) == Trust.UNTRUSTED
    assert Trust.LOCAL_DERIVED.weakest(Trust.TRUSTED) == Trust.LOCAL_DERIVED

def test_comfyui_profile_disables_memory_and_load():
    p = PROFILES["comfyui_desktop"]
    assert not p.memory_inject and not p.memory_writeback and not p.allow_load

def test_coding_profile_all_enabled():
    p = PROFILES["claude_code"]
    assert p.memory_inject and p.memory_writeback and p.allow_load
    assert p.pre_call_budget_ms == 300

def test_execution_only_accepts_authorized_plan():
    with pytest.raises(TypeError): AuthorizedPlan(task_type="chat")

def test_volatile_slots_after_stable():
    names = [s.name for s in LAYOUT]
    assert names.index("retrieved_memory") > names.index("user_profile")
    assert names.index("web_results") == len(names) - 1
    assert set(DEGRADE_ORDER).issubset(set(names))

def test_route_decision_has_no_silent_swap_without_flag():
    d = RouteDecision("qwen3_32b", 0, False, "explicit")
    assert d.downgraded is False
