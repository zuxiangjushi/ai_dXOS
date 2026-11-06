from dataclasses import dataclass, field

@dataclass(frozen=True)
class ProposedPlan:
    task_type: str
    need_memory: bool = True
    need_rag: bool = False
    need_web: bool = False
    need_tools: bool = False
    freshness: bool = False

@dataclass(frozen=True)
class AuthorizedPlan(ProposedPlan):
    authorized_at: int = field(kw_only=True)
    policy_version: str = "1"
    permissions_granted: tuple = ()
