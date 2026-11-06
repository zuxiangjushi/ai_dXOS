"""LongCite 句子级引用引擎

基于 THUDM/LongCite-glm4-9b，生成答案时精确标注引用的句子位置。
作为 Evidence Engine 的 Citation Generator Adapter。
"""
import os
import re
from typing import List, Dict, Optional


class LongCiteEngine:
    """LongCite 引擎（延迟加载）"""

    def __init__(self, model_path: str = None):
        self.model_path = model_path or os.environ.get(
            "LONGCITE_MODEL_PATH", "/ai/models/LongCite-glm4-9b")
        self._model = None
        self._tokenizer = None

    def _load(self):
        """延迟加载（首次调用时）"""
        if self._model is not None:
            return

        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM

        print(f"   [longcite] 加载模型: {self.model_path}", flush=True)
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_path, trust_remote_code=True)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=torch.bfloat16,
            trust_remote_code=True,
            device_map="auto",
        )
        self._model.eval()
        print(f"   [longcite] 模型已加载", flush=True)

    def cite(self, context: str, query: str,
             max_input_length: int = 128000,
             max_new_tokens: int = 1024) -> Dict:
        """生成带句子级引用的答案

        返回:
            {
                "answer": "...",
                "citations": [
                    {"sentence": "...", "source_chunk": 0, "quote": "..."},
                    ...
                ]
            }
        """
        self._load()

        try:
            result = self._model.query_longcite(
                context,
                query,
                tokenizer=self._tokenizer,
                max_input_length=max_input_length,
                max_new_tokens=max_new_tokens,
            )
            return result
        except Exception as e:
            print(f"   [longcite] 失败: {type(e).__name__}: {e}", flush=True)
            return {"answer": "", "citations": [], "error": str(e)}

    def health(self) -> bool:
        try:
            self._load()
            return self._model is not None
        except Exception:
            return False


_engine = None


def get_longcite() -> LongCiteEngine:
    global _engine
    if _engine is None:
        _engine = LongCiteEngine()
    return _engine


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/ai/Memory-Gateway")

    engine = get_longcite()
    result = engine.cite(
        context="重庆市今天（2026年9月13日）多云，最高气温30℃，最低气温24℃。",
        query="重庆今天气温",
    )
    print(f"答案: {result.get('answer', '')[:200]}")
    print(f"引用数: {len(result.get('citations', []))}")
