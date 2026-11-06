from dataclasses import dataclass, replace
from .errors import ScopeViolation

@dataclass(frozen=True)
class MemoryScope:
    user_id: str
    workspace_id: str
    project_id: str | None = None
    agent_id: str | None = None
    def as_filter(self) -> dict:
        f = {"user_id": self.user_id, "workspace_id": self.workspace_id, "is_deleted": False}
        if self.project_id: f["project_id"] = self.project_id
        return f

def narrow_scope(bound: MemoryScope, headers: dict) -> MemoryScope:
    ws, pj = headers.get("X-Workspace-Id"), headers.get("X-Project-Id")
    if ws and ws != bound.workspace_id:
        raise ScopeViolation(f"header workspace {ws} != key workspace {bound.workspace_id}")
    if pj and bound.project_id and pj != bound.project_id:
        raise ScopeViolation(f"header project {pj} not bound to key")
    return replace(bound, project_id=pj or bound.project_id)
