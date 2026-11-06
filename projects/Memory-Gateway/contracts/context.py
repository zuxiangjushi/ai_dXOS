from dataclasses import dataclass
@dataclass(frozen=True)
class Slot:
    name: str; budget: int; stable: bool; versioned: bool = False
LAYOUT = (
    Slot("system_policy", 1200, True), Slot("tools_spec", 1500, True),
    Slot("user_profile", 800, True, versioned=True),
    Slot("project_context", 1800, True, versioned=True),
    Slot("summary_history", 1500, True), Slot("recent_messages", 6000, False),
    Slot("retrieved_memory", 2000, False), Slot("retrieved_rag", 3000, False),
    Slot("web_results", 2000, False))
DEGRADE_ORDER = ("web_results", "retrieved_rag", "retrieved_memory", "recent_messages")
STABLE_SLOTS = tuple(s.name for s in LAYOUT if s.stable)
VOLATILE_SLOTS = tuple(s.name for s in LAYOUT if not s.stable)
