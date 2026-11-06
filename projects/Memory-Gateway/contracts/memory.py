import hashlib, time
from dataclasses import dataclass, field
from enum import Enum
from .scope import MemoryScope

class Trust(str, Enum):
    TRUSTED = "trusted"; LOCAL_DERIVED = "local_derived"; UNTRUSTED = "untrusted"
    def weakest(self, other: "Trust") -> "Trust":
        order = [Trust.TRUSTED, Trust.LOCAL_DERIVED, Trust.UNTRUSTED]
        return max(self, other, key=order.index)

class MemoryClass(str, Enum):
    FACT = "fact"; PREFERENCE = "preference"; DECISION = "decision"
    PROCEDURE = "procedure"; EPISODE = "episode"

class WriteOp(str, Enum): ADD = "ADD"; UPDATE = "UPDATE"; DELETE = "DELETE"; NOOP = "NOOP"

@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str; scope: MemoryScope; content: str; entity_key: str
    memory_class: MemoryClass; tier: str; confidence: float; importance: float
    trust: Trust = Trust.TRUSTED; origin_type: str = "conversation"
    valid_from: int = 0; valid_until: int | None = None
    supersedes: str | None = None; superseded_by: str | None = None
    content_hash: str = ""; last_accessed_at: int | None = None
    def is_effective(self, now: int | None = None) -> bool:
        now = now or int(time.time())
        return self.superseded_by is None and (self.valid_until is None or self.valid_until > now)

def new_memory(scope, content, entity_key, memory_class=MemoryClass.FACT, tier="L3_SEMANTIC",
               confidence=0.7, importance=0.5, trust=Trust.TRUSTED, origin_type="conversation") -> MemoryRecord:
    now = int(time.time())
    return MemoryRecord(memory_id=f"mem_{hashlib.sha1(f'{scope.user_id}{content}{now}'.encode()).hexdigest()[:16]}",
        scope=scope, content=content, entity_key=entity_key, memory_class=memory_class, tier=tier,
        confidence=confidence, importance=importance, trust=trust, origin_type=origin_type,
        valid_from=now, content_hash=hashlib.sha256(content.encode()).hexdigest())

@dataclass(frozen=True)
class WriteJob:
    idem_key: str; scope: MemoryScope; tier: str; payload: dict
    created_at: int; attempts: int = 0; keep_always: bool = False
