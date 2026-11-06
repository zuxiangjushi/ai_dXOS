"""成本追踪：按 token 估算成本（CNY）"""
import os

# 简化定价（元 / 1K tokens）—— 按自有 GPU 折旧估算
PRICING = {
    "qwen3_32b":     {"prompt": 0.001, "completion": 0.002},
    "qwen38_27b_f8": {"prompt": 0.001, "completion": 0.002},
    "yy38_27b":      {"prompt": 0.0005, "completion": 0.001},
    "yy35b_q6":      {"prompt": 0.0005, "completion": 0.001},
    "38FN_Q4":       {"prompt": 0.0005, "completion": 0.001},
    "gemma_4":       {"prompt": 0.0003, "completion": 0.0006},
    "qwen3_30b":     {"prompt": 0.0008, "completion": 0.0016},
    "deepseek_70b":  {"prompt": 0.002, "completion": 0.004},
}
DEFAULT_PRICE = {"prompt": 0.001, "completion": 0.002}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """返回成本（CNY）"""
    p = PRICING.get(model, DEFAULT_PRICE)
    return (prompt_tokens / 1000.0 * p["prompt"]) + \
           (completion_tokens / 1000.0 * p["completion"])
