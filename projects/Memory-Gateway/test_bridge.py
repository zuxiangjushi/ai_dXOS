import json
import unittest
from protocol_bridge import ProtocolError, convert_anthropic_to_openai, convert_openai_response, generate_anthropic_sse_stream

class ProtocolBridgeTests(unittest.TestCase):
    def test_text_only(self):
        req = {"model": "claude-test", "max_tokens": 128, "messages": [{"role": "user", "content": "hello"}]}
        out = convert_anthropic_to_openai(req, "memory-llm")
        self.assertEqual(out["messages"][0]["content"], "hello")
        msg = convert_openai_response({"choices": [{"message": {"content": "hi", "tool_calls": []}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}, "claude-test")
        self.assertEqual(msg["stop_reason"], "end_turn")
        self.assertIn("event: message_start", generate_anthropic_sse_stream(msg)[0])

    def test_three_stage_tool_roundtrip(self):
        req1 = {"model": "claude-test", "max_tokens": 256, "messages": [{"role": "user", "content": "列出文件"}], "tools": [{"name": "ListFiles", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}]}
        upstream_req1 = convert_anthropic_to_openai(req1, "memory-llm")
        
        assistant_msg = convert_openai_response({"choices": [{"message": {"content": "", "tool_calls": [{"id": "up-001", "function": {"name": "ListFiles", "arguments": '{"path":"/tmp"}'}}]}, "finish_reason": "tool_calls"}], "usage": {}}, "claude-test")
        tool_block = assistant_msg["content"][0]
        self.assertTrue(tool_block["id"].startswith("toolu_"))

        req2 = {"model": "claude-test", "max_tokens": 256, "messages": [{"role": "user", "content": "列出文件"}, {"role": "assistant", "content": assistant_msg["content"]}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_block["id"], "content": "a.txt"}]}]}
        upstream_req2 = convert_anthropic_to_openai(req2, "memory-llm")
        self.assertEqual(upstream_req2["messages"][-1]["role"], "tool")
        self.assertEqual(upstream_req2["messages"][-1]["tool_call_id"], tool_block["id"])

    def test_bad_tool_json(self):
        with self.assertRaises(ProtocolError):
            convert_openai_response({"choices": [{"message": {"content": "", "tool_calls": [{"id": "x", "function": {"name": "Bash", "arguments": '{"cmd":'}}]}, "finish_reason": "tool_calls"}], "usage": {}}, "claude-test")

    def test_unknown_tool_result_id(self):
        req = {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "not-seen", "content": "result"}]}]}
        with self.assertRaises(ProtocolError):
            convert_anthropic_to_openai(req, "memory-llm")

    def test_invalid_max_tokens(self):
        for value in (0, -1, True, "100"):
            with self.subTest(value=value):
                with self.assertRaises(ProtocolError):
                    convert_anthropic_to_openai({"max_tokens": value, "messages": [{"role": "user", "content": "hello"}]}, "memory-llm")

if __name__ == "__main__":
    unittest.main(verbosity=2)
