import json
import uuid
from typing import Any

MAX_TOKENS_LIMIT = 8192

class ProtocolError(Exception):
    """客户端请求或上游协议不符合约定。"""
    pass

def _require_dict(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ProtocolError(f"{name} must be an object")
    return value

def _require_text(value: Any, name: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise ProtocolError(f"{name} must not be empty")
    return value

def _validate_max_tokens(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProtocolError("max_tokens must be a positive integer")
    return min(value, MAX_TOKENS_LIMIT)

def _convert_system(system: Any) -> list:
    if system is None or system == "": return []
    if isinstance(system, str): return [{"role": "system", "content": system}]
    if not isinstance(system, list): raise ProtocolError("system must be a string or a list of text blocks")
    parts = []
    for i, block in enumerate(system):
        block = _require_dict(block, f"system[{i}]")
        if block.get("type") != "text": raise ProtocolError(f"Unsupported system block type: {block.get('type')}")
        parts.append(_require_text(block.get("text"), f"system[{i}].text"))
    return [{"role": "system", "content": "\n".join(parts)}] if parts else []

def _convert_tool_choice(choice: Any) -> Any:
    if choice is None: return None
    choice = _require_dict(choice, "tool_choice")
    kind = choice.get("type")
    if kind == "auto": return "auto"
    if kind == "any": return "required"
    if kind == "tool":
        name = _require_text(choice.get("name"), "tool_choice.name", False)
        return {"type": "function", "function": {"name": name}}
    raise ProtocolError(f"Unsupported tool_choice type: {kind}")

def convert_anthropic_to_openai(body: dict, target_model: str) -> dict:
    body = _require_dict(body, "request body")
    max_tokens = _validate_max_tokens(body.get("max_tokens", 4096))
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ProtocolError("messages must be a non-empty array")

    openai_msgs = _convert_system(body.get("system", ""))
    pending_tool_ids = set()
    seen_tool_ids = set()

    for mi, raw_message in enumerate(messages):
        message = _require_dict(raw_message, f"messages[{mi}]")
        role = message.get("role")
        if role not in ("user", "assistant"):
            raise ProtocolError(f"Unsupported message role at index {mi}")

        content = message.get("content", "")
        if isinstance(content, str):
            openai_msgs.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            raise ProtocolError(f"messages[{mi}].content must be a string or array")

        text_parts, tool_calls, tool_results = [], [], []

        for bi, raw_block in enumerate(content):
            block = _require_dict(raw_block, f"messages[{mi}].content[{bi}]")
            btype = block.get("type")

            if btype == "text":
                text_parts.append(_require_text(block.get("text"), f"messages[{mi}].text"))
            elif btype == "tool_use":
                if role != "assistant": raise ProtocolError("tool_use is only supported in assistant messages")
                tid = _require_text(block.get("id"), "tool_use.id", False)
                name = _require_text(block.get("name"), "tool_use.name", False)
                arguments = block.get("input", {})
                if not isinstance(arguments, dict): raise ProtocolError("tool_use.input must be an object")
                if tid in seen_tool_ids: raise ProtocolError(f"Duplicate tool_use id: {tid}")
                seen_tool_ids.add(tid)
                pending_tool_ids.add(tid)
                tool_calls.append({"id": tid, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}})
            elif btype == "tool_result":
                if role != "user": raise ProtocolError("tool_result is only supported in user messages")
                tid = _require_text(block.get("tool_use_id"), "tool_result.tool_use_id", False)
                if tid not in pending_tool_ids: raise ProtocolError(f"tool_result references unknown or completed id: {tid}")
                if tid in [r["tool_call_id"] for r in tool_results]: raise ProtocolError(f"Duplicate tool_result id: {tid}")
                
                result_content = block.get("content", "")
                if isinstance(result_content, str): result_text = result_content
                elif isinstance(result_content, list):
                    result_text = "\n".join(_require_text(sub.get("text"), "tool_result text") for sub in result_content if isinstance(sub, dict) and sub.get("type") == "text")
                else: raise ProtocolError("Invalid tool_result content format")
                
                tool_results.append({"role": "tool", "tool_call_id": tid, "content": result_text})
                pending_tool_ids.remove(tid)
            else:
                raise ProtocolError(f"Unsupported content block type: {btype}")

        if role == "assistant":
            if tool_calls:
                openai_msgs.append({"role": "assistant", "content": "".join(text_parts) or None, "tool_calls": tool_calls})
            elif text_parts:
                openai_msgs.append({"role": "assistant", "content": "".join(text_parts)})
            else:
                raise ProtocolError(f"Empty assistant content at index {mi}")
        else:
            if tool_results and text_parts:
                raise ProtocolError("Mixing text and tool_result in one user message is not supported")
            if tool_results: openai_msgs.extend(tool_results)
            elif text_parts: openai_msgs.append({"role": "user", "content": "".join(text_parts)})
            else: raise ProtocolError(f"Empty user content at index {mi}")

    if pending_tool_ids:
        raise ProtocolError("Missing tool_result for one or more tool_use blocks")

    tools = body.get("tools")
    openai_tools = None
    if tools is not None:
        if not isinstance(tools, list): raise ProtocolError("tools must be an array")
        openai_tools = []
        names = set()
        for i, raw_tool in enumerate(tools):
            tool = _require_dict(raw_tool, f"tools[{i}]")
            name = _require_text(tool.get("name"), f"tools[{i}].name", False)
            if name in names: raise ProtocolError(f"Duplicate tool name: {name}")
            names.add(name)
            schema = tool.get("input_schema", {"type": "object", "properties": {}})
            if not isinstance(schema, dict): raise ProtocolError(f"tools[{i}].input_schema must be an object")
            openai_tools.append({"type": "function", "function": {"name": name, "description": tool.get("description", ""), "parameters": schema}})

    result = {"model": target_model, "messages": openai_msgs, "max_tokens": max_tokens, "stream": False}
    if openai_tools: result["tools"] = openai_tools

    tool_choice = _convert_tool_choice(body.get("tool_choice"))
    if tool_choice is not None:
        if not openai_tools: raise ProtocolError("tool_choice requires tools")
        result["tool_choice"] = tool_choice

    stop_sequences = body.get("stop_sequences")
    if stop_sequences is not None:
        if not isinstance(stop_sequences, list) or not all(isinstance(s, str) for s in stop_sequences):
            raise ProtocolError("stop_sequences must be an array of strings")
        result["stop"] = stop_sequences

    return result

def convert_openai_response(response: dict, raw_model: str) -> dict:
    response = _require_dict(response, "upstream response")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices: raise ProtocolError("Upstream returned empty choices")

    choice = _require_dict(choices[0], "choices[0]")
    message = _require_dict(choice.get("message"), "choices[0].message")
    finish_reason = choice.get("finish_reason")

    content = []
    text = message.get("content")
    if text:
        if not isinstance(text, str): raise ProtocolError("Upstream message.content must be a string or null")
        content.append({"type": "text", "text": text})

    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list): raise ProtocolError("Upstream tool_calls must be an array")

    for tc_index, raw_call in enumerate(tool_calls):
        tc = _require_dict(raw_call, f"tool_calls[{tc_index}]")
        function = _require_dict(tc.get("function"), "tool_call.function")
        name = _require_text(function.get("name"), "tool_call.function.name", False)
        raw_args = function.get("arguments", "{}")
        if not isinstance(raw_args, str): raise ProtocolError("tool_call arguments must be a JSON string")
        try: args = json.loads(raw_args)
        except (ValueError, TypeError) as exc: raise ProtocolError("Invalid JSON in tool_call arguments") from exc
        if not isinstance(args, dict): raise ProtocolError("tool_call arguments JSON must decode to an object")

        # 由适配层生成 Anthropic ID。客户端下一轮会将该 ID 原样放入 tool_result。
        tool_id = f"toolu_{uuid.uuid4().hex}"
        content.append({"type": "tool_use", "id": tool_id, "name": name, "input": args})

    if tool_calls: stop_reason = "tool_use"
    elif finish_reason == "stop": stop_reason = "end_turn"
    elif finish_reason == "length": stop_reason = "max_tokens"
    elif finish_reason in ("content_filter",): raise ProtocolError(f"Unsupported finish_reason: {finish_reason}")
    elif finish_reason in (None, "tool_calls"): raise ProtocolError("Inconsistent finish_reason")
    else: raise ProtocolError(f"Unsupported finish_reason: {finish_reason}")

    usage = response.get("usage") or {}
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message", "role": "assistant", "model": raw_model, "content": content,
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}
    }

def generate_anthropic_sse_stream(message: dict) -> list:
    events = []
    def emit(event_name: str, data: dict) -> str:
        return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"

    start_message = dict(message)
    start_message.update({"content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": message["usage"]["input_tokens"], "output_tokens": 0}})
    events.append(emit("message_start", {"type": "message_start", "message": start_message}))

    for index, block in enumerate(message["content"]):
        if block["type"] == "text":
            events.append(emit("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}}))
            text = block["text"]
            for offset in range(0, len(text), 20):
                events.append(emit("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text[offset:offset + 20]}}))
        elif block["type"] == "tool_use":
            events.append(emit("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}}))
            events.append(emit("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"], ensure_ascii=False)}}))
        else:
            raise ProtocolError(f"Unsupported output block type: {block.get('type')}")
        events.append(emit("content_block_stop", {"type": "content_block_stop", "index": index}))

    events.append(emit("message_delta", {"type": "message_delta", "delta": {"stop_reason": message["stop_reason"], "stop_sequence": message["stop_sequence"]}, "usage": {"output_tokens": message["usage"]["output_tokens"]}}))
    events.append(emit("message_stop", {"type": "message_stop"}))
    return events
