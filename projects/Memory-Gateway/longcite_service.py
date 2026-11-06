"""LongCite HTTP 服务：把 LongCite-glm4-9b 包成 HTTP API

端口 8020，供 Evidence Engine 调用生成句子级引用。
"""
import os
import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional

# HF 环境
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/ai/models/huggingface")

MODEL_PATH = os.environ.get("LONGCITE_MODEL_PATH", "/ai/models/LongCite-glm4-9b")
LONGCITE_ENABLED = os.environ.get("LONGCITE_ENABLED", "false").lower() == "true"
CPU_MODE = os.environ.get("LONGCITE_CPU_MODE", "true").lower() == "true"

app = FastAPI(title="LongCite Service")

# 全局模型（延迟加载）
_model = None
_tokenizer = None
_load_ts = 0


class CiteRequest(BaseModel):
    context: str
    query: str
    max_input_length: int = 128000
    max_new_tokens: int = 1024


class CiteResponse(BaseModel):
    answer: str
    citations: List[dict] = []
    latency_s: float = 0.0
    error: Optional[str] = None


def _load_model():
    global _model, _tokenizer, _load_ts
    if _model is not None:
        return
    if time.time() - _load_ts < 30:  # 避免并发重复加载
        raise HTTPException(503, "模型加载中，请稍后")

    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM

    _load_ts = time.time()
    print(f"   [longcite-svc] 加载模型: {MODEL_PATH}", flush=True)
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    # ★ 强制 CPU（避免撞底座 GPU）
    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.float32,      # CPU 用 fp32
        trust_remote_code=True,
        device_map="cpu",               # ★ 强制 CPU
        low_cpu_mem_usage=True,
    )
    _model = _model.to("cpu")
    _model.eval()
    print(f"   [longcite-svc] 模型已加载", flush=True)


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "model_loaded": _model is not None,
        "model_path": MODEL_PATH,
        "cpu_mode": CPU_MODE,
        "enabled": LONGCITE_ENABLED,
    }


@app.get("/v1/models")
async def list_models():
    return {"data": [{"id": "longcite-glm4-9b", "object": "model"}]}


@app.post("/v1/cite", response_model=CiteResponse)
async def cite(req: CiteRequest):
    t0 = time.perf_counter()
    try:
        _load_model()
        result = _model.query_longcite(
            req.context,
            req.query,
            tokenizer=_tokenizer,
            max_input_length=req.max_input_length,
            max_new_tokens=req.max_new_tokens,
        )

        # ★ 解析 statements_with_citations → 扁平化 citations
        citations = []
        for stmt in result.get("statements_with_citations", []) or []:
            text = stmt.get("statement", "").strip()
            if not text:
                continue
            for c in stmt.get("citation", []) or []:
                citations.append({
                    "statement": text,
                    "cite": c.get("cite", ""),
                    "start_sentence_idx": c.get("start_sentence_idx"),
                    "end_sentence_idx": c.get("end_sentence_idx"),
                    "start_char_idx": c.get("start_char_idx"),
                    "end_char_idx": c.get("end_char_idx"),
                })

        return CiteResponse(
            answer=result.get("answer", ""),
            citations=citations,
            latency_s=round(time.perf_counter() - t0, 3),
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return CiteResponse(
            answer="",
            citations=[],
            latency_s=round(time.perf_counter() - t0, 3),
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8020)
