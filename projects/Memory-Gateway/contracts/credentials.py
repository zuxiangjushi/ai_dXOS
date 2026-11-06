from dataclasses import dataclass
TIER_PRIOR = {"L0_CONTEXT": 1.0, "L1_WORKING": 0.9, "L2_EPISODIC": 0.7,
              "L3_SEMANTIC": 0.8, "L4_PROJECT": 0.75, "L5_USER": 0.85}

@dataclass(frozen=True)
class AgentProfile:
    name: str; memory_inject: bool = True; memory_writeback: bool = True
    allow_load: bool = True; max_output_tokens: int = 8192
    pre_call_budget_ms: int = 300; max_concurrency: int = 4

PROFILES = {
    "openwebui": AgentProfile("openwebui"), "cursor": AgentProfile("cursor"),
    "claude_code": AgentProfile("claude_code"), "codex": AgentProfile("codex"),
    "cline": AgentProfile("cline"), "continue": AgentProfile("continue"),
    "hermes": AgentProfile("hermes"), "openclaw": AgentProfile("openclaw"),
    "comfyui_desktop": AgentProfile("comfyui_desktop", memory_inject=False,
        memory_writeback=False, allow_load=False, max_output_tokens=1024,
        pre_call_budget_ms=50, max_concurrency=2)}

@dataclass(frozen=True)
class IssuedKey:
    key_id: str; key_hash: str; user_id: str; workspace_id: str; agent_type: str
    allowed_workspace_ids: frozenset; model_allowlist: frozenset; scopes: frozenset
    default_model: str; quota_tokens: int; rate_qps: int
    allow_silent_fallback: bool = False; expires_at: int | None = None
    @property
    def profile(self) -> AgentProfile: return PROFILES[self.agent_type]
