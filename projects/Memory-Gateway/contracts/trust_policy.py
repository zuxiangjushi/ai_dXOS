"""信任分级与污点传播策略"""
from contracts.memory import Trust

# 来源类型 → 初始信任等级
ORIGIN_TRUST = {
    "user_explicit":  Trust.TRUSTED,       # 用户显式指令："记住..."
    "conversation":   Trust.TRUSTED,       # 对话中自然抽取
    "tool_output":    Trust.LOCAL_DERIVED, # 本地工具输出（编译结果、错误栈）
    "document":       Trust.LOCAL_DERIVED, # 上传的文档
    "web":            Trust.UNTRUSTED,     # 网页/搜索结果
    "search_result":  Trust.UNTRUSTED,     # 搜索引擎结果
}

# 信任等级 → 可入层级
TRUST_TIERS = {
    Trust.TRUSTED:       {"L2_EPISODIC", "L3_SEMANTIC", "L4_PROJECT", "L5_USER"},
    Trust.LOCAL_DERIVED: {"L2_EPISODIC", "L4_PROJECT"},
    Trust.UNTRUSTED:     {"L1_WORKING"},   # 只进会话级，24h 后自动消失
}

# 信任等级 → TTL（秒）
TRUST_TTL = {
    Trust.TRUSTED:       0,        # 永久（靠 valid_until 失效）
    Trust.LOCAL_DERIVED: 30 * 86400,
    Trust.UNTRUSTED:     24 * 3600,
}

def resolve_trust(origin_type: str, content: str = "") -> Trust:
    """根据来源类型解析信任等级。"""
    return ORIGIN_TRUST.get(origin_type, Trust.UNTRUSTED)

def can_enter_tier(trust: Trust, tier: str) -> bool:
    """判断某信任等级能否进入指定记忆层。"""
    return tier in TRUST_TIERS.get(trust, set())

def get_ttl(trust: Trust) -> int:
    """获取该信任等级的 TTL（秒）；0 表示永久。"""
    return TRUST_TTL.get(trust, 24 * 3600)


def is_trusted_for_longterm(trust) -> bool:
    """判断该信任级别是否允许进入长期记忆（L3+）
    - TRUSTED: 用户显式/对话抽取 → 允许
    - LOCAL_DERIVED: 本地工具输出/文档 → 允许
    - UNTRUSTED: 网页/搜索结果 → 拒绝（只进会话级）
    """
    return trust in (Trust.TRUSTED, Trust.LOCAL_DERIVED)
