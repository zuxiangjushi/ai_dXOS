"""动态选模型：优先 yy35b_q6，不可用时选第一个在线模型

设计目标：解耦测试脚本和底座模型名
"""
import os
import httpx
from typing import Optional

# 优先级列表（按偏好排序）
PREFERRED_MODELS = [
    "yy35b_q6",
    "qwen38_27b_f8",
    "yy38_27b",
    "gemma_4",
    "38FN_Q4",
]


def _read_key() -> str:
    k = os.environ.get("PILOT_KEY_M00", "").strip()
    if k:
        return k
    try:
        for line in open("/ai/Memory-Gateway/.env.g0"):
            if line.startswith("PILOT_KEY_M00="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def pick_model(base_url: str = None, preferred: list = None) -> str:
    """从 /v1/models 里选一个可用的模型

    1. 优先 preferred 列表（默认 PREFERRED_MODELS）
    2. 都没有 → 用第一个在线模型
    3. 完全没有 → 返回 "yy35b_q6"（兜底）
    """
    base = (base_url
            or os.environ.get("UPSTREAM_BASE", "http://192.168.10.132:9980")).rstrip("/")
    key = _read_key()
    preferred = preferred or PREFERRED_MODELS

    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{base}/v1/models",
                      headers={"Authorization": f"Bearer {key}"})
            if r.status_code != 200:
                return preferred[0]
            ids = [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return preferred[0]

    if not ids:
        return preferred[0]

    # 按偏好匹配
    for p in preferred:
        if p in ids:
            return p

    # 兜底：第一个在线模型
    return ids[0]


if __name__ == "__main__":
    m = pick_model()
    print(f"选中模型: {m}")
