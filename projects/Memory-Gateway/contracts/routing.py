from dataclasses import dataclass
@dataclass(frozen=True)
class ModelStatus:
    model_id: str; state: str; resident: bool; cold_start_seconds: int | None
    max_input_tokens: int; lease_holder_type: str | None = None
@dataclass(frozen=True)
class RouteDecision:
    model_id: str; queued_ms: int; downgraded: bool; note: str
@dataclass(frozen=True)
class LeaseTicket:
    granted: bool; lease_id: str | None = None; retry_after_s: int | None = None
