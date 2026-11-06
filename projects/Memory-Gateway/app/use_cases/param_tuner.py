"""参数调优：按模型 + 分类调整生成参数

设计原则：
- 不改变模型本质能力，只做场景适配
- 优先级：用户显式 > 模型基线 × 分类系数
- 安全边界 clamp 防止越界
"""
import os
import time
import yaml
from typing import Optional, Dict, Any

_CONFIG_PATH = os.environ.get("PARAM_CONFIG",
                              "/ai/Memory-Gateway/config/model_params.yaml")


class ParamTuner:
    def __init__(self, config_path: str = None):
        self.config_path = config_path or _CONFIG_PATH
        self._cache: Dict = {}
        self._cache_ts = 0.0
        self._load()

    def _load(self):
        now = time.time()
        if now - self._cache_ts < 60 and self._cache:
            return
        try:
            with open(self.config_path) as f:
                self._cache = yaml.safe_load(f) or {}
            self._cache_ts = now
        except Exception as e:
            print(f"   [param] 加载失败: {e}", flush=True)
            self._cache = {}

    def tune(self, body: dict, model: str,
             category: Optional[str] = None) -> Dict[str, Any]:
        """返回调优后的参数（不修改 body）

        优先级：用户显式 > 模型基线 × 分类系数
        """
        # ★ A/B 测试开关（环境变量控制）
        if os.environ.get("PARAM_TUNING_ENABLED", "true").lower() != "true":
            return {}

        self._load()
        cfg = self._cache or {}
        models = cfg.get("models", {})
        cats = cfg.get("categories", {})
        safety = cfg.get("safety", {})

        base = models.get(model) or {}
        if base.get("skip"):
            return {}

        if category and category in cats:
            cat = cats[category]
            temp_coef = cat.get("temp_coef", 1.0)
            top_p_coef = cat.get("top_p_coef", 1.0)
        else:
            temp_coef = 1.0
            top_p_coef = 1.0

        out: Dict[str, Any] = {}

        # temperature
        if body.get("temperature") is None and base.get("temp") is not None:
            t = base["temp"] * temp_coef
            t = max(safety.get("temp_min", 0.0),
                    min(safety.get("temp_max", 1.2), t))
            out["temperature"] = round(t, 2)

        # top_p
        if body.get("top_p") is None and base.get("top_p") is not None:
            p = base["top_p"] * top_p_coef
            p = max(safety.get("top_p_min", 0.5),
                    min(safety.get("top_p_max", 1.0), p))
            out["top_p"] = round(p, 2)

        # top_k（不分类）
        if body.get("top_k") is None and base.get("top_k") is not None:
            out["top_k"] = base["top_k"]

        # repetition_penalty
        if body.get("repetition_penalty") is None and base.get("repetition_penalty") is not None:
            rp = base["repetition_penalty"]
            rp = max(safety.get("rp_min", 1.0),
                     min(safety.get("rp_max", 1.3), rp))
            out["repetition_penalty"] = rp

        return out


_tuner = None


def get_tuner() -> ParamTuner:
    global _tuner
    if _tuner is None:
        _tuner = ParamTuner()
    return _tuner


if __name__ == "__main__":
    t = get_tuner()
    print("测试 1: qwen38_27b_f8 + realtime")
    print("  ", t.tune({}, "qwen38_27b_f8", "realtime"))
    print("测试 2: deepseek_70b + factual")
    print("  ", t.tune({}, "deepseek_70b", "factual"))
    print("测试 3: 用户显式 temperature=0.95")
    print("  ", t.tune({"temperature": 0.95}, "qwen38_27b_f8", "realtime"))
    print("测试 4: qwen3_emb_8b（跳过）")
    print("  ", t.tune({}, "qwen3_emb_8b", "factual"))
    print("测试 5: 未知模型")
    print("  ", t.tune({}, "unknown_model", "factual"))
