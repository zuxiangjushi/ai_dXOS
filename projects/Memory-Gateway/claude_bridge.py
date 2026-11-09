import logging
import os
import json
import uuid
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from protocol_bridge import ProtocolError, convert_anthropic_to_openai, convert_openai_response

logger = logging.getLogger("claude_bridge")

# 🛑 硬编码 LiteLLM 的基础地址
LITELLM_URL = "http://127.0.0.1:9980/v1"
LITELLM_KEY = "<REDACTED_LITELLM_KEY>"
CLIENT_KEY = "sk-gateway-secret-2026"

# 🛑 终极自动探测：问底层要真名，绝不瞎猜
async def _get_active_chat_model():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{LITELLM_URL}/models", headers={"Authorization": f"Bearer {LITELLM_KEY}"})
            if r.status_code == 200:
                models = r.json().get("data", [])
                for m in models:
                    mid = m.get("id", "")
                    # 自动过滤掉非对话模型
                    if "embedding" not in mid.lower() and "reranker" not in mid.lower():
                        return mid
    except Exception as e:
        logger.error(f"探测模型失败: {e}")
    return None

def err(status, msg):
    return JSONResponse({"type": "error", "error": {"type": "api_error", "message": msg}}, status_code=status)

def check_auth(req: Request):
    return req.headers.get("x-api-key") == CLIENT_KEY or req.headers.get("authorization") == f"Bearer {CLIENT_KEY}"

async def claude_messages_handler(request: Request):
    if not check_auth(request):
        return err(401, "Unauthorized")

    # 🛑 每次请求动态获取当前活跃模型
    physical_model = await _get_active_chat_model()
    if not physical_model:
        return err(503, "No active chat model found in LiteLLM. Please start a model in the Dxos panel.")

    body = await request.json()
    raw_model = body.get("model", "")
    if not raw_model.startswith("claude-"):
        return err(400, f"Model {raw_model} not supported")

    logger.info(f"Claude-Bridge 动态路由: {raw_model} -> {physical_model}")

    try:
        openai_body = convert_anthropic_to_openai(body, physical_model)
    except ProtocolError as e:
        return err(400, str(e))
    except Exception as e:
        return err(400, "Invalid Request Format")

    is_stream = body.get("stream", True)
    openai_body["stream"] = is_stream
    headers = {"Authorization": f"Bearer {LITELLM_KEY}", "Content-Type": "application/json"}

    # ================= 非流式请求 =================
    if not is_stream:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(f"{LITELLM_URL}/chat/completions", headers=headers, json=openai_body)
                if r.status_code != 200:
                    return err(r.status_code, f"Upstream {r.status_code}: {r.text}")
                return JSONResponse(convert_openai_response(r.json(), raw_model))
        except Exception as e:
            return err(502, str(e))

    # ================= 流式请求 =================
    async def stream_gen():
        msg_id = f"msg_{uuid.uuid4().hex[:16]}"
        yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'model': raw_model, 'content': [], 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
        yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"
        
        idx = 0
        started = False
        tool_buffers = {}
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream("POST", f"{LITELLM_URL}/chat/completions", headers=headers, json=openai_body) as r:
                    if r.status_code != 200:
                        yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': f'Upstream {r.status_code}'}})}\n\n"
                        return
                    async for line in r.aiter_lines():
                        if not line.startswith("data: "): continue
                        data = line[6:]
                        if data == "[DONE]": break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            
                            if delta.get("content"):
                                if not started:
                                    started = True
                                    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': idx, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                                yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': idx, 'delta': {'type': 'text_delta', 'text': delta['content']}})}\n\n"
                            
                            if "tool_calls" in delta:
                                for tc in delta["tool_calls"]:
                                    tc_idx = tc.get("index", 0)
                                    if tc_idx not in tool_buffers:
                                        if started:
                                            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': idx})}\n\n"
                                            idx += 1
                                            started = False
                                        tool_buffers[tc_idx] = {"id": tc.get("id", f"toolu_{uuid.uuid4().hex[:16]}"), "name": "", "args": ""}
                                        if tc.get("function", {}).get("name"):
                                            tool_buffers[tc_idx]["name"] = tc["function"]["name"]
                                            yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': idx, 'content_block': {'type': 'tool_use', 'id': tool_buffers[tc_idx]['id'], 'name': tool_buffers[tc_idx]['name'], 'input': {}}})}\n\n"
                                    if tc.get("function", {}).get("arguments"):
                                        args_chunk = tc["function"]["arguments"]
                                        tool_buffers[tc_idx]["args"] += args_chunk
                                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': idx, 'delta': {'type': 'input_json_delta', 'partial_json': args_chunk}})}\n\n"
                        except Exception:
                            continue
            if started or tool_buffers:
                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': idx})}\n\n"
            yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': 0}})}\n\n"
            yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': str(e)}})}\n\n"

    return StreamingResponse(stream_gen(), media_type="text/event-stream")
