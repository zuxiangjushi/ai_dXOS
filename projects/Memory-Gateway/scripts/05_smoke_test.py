import httpx
import json

GW = "http://192.168.10.132:9982"  # 网关对外端口
KEY = "sk-dx-test.xxx"  # 先随便填，验证透传链路

# 先测试网关是否可访问
try:
    r = httpx.get(GW + "/v1/models", timeout=5)
    print(f"GET /v1/models → HTTP {r.status_code}")
    print(r.text[:200])
except Exception as e:
    print(f"网关不可达: {e}")

# 测试 chat 流式
payload = {
    "model": "38FN_Q4",
    "messages": [{"role": "user", "content": "你好，请用一句话介绍你自己"}],
    "stream": True,
    "max_tokens": 100
}
try:
    with httpx.stream("POST", GW + "/v1/chat/completions", json=payload, timeout=30) as resp:
        print(f"\nPOST /v1/chat/completions → HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if line.startswith("data:"):
                print(line[:120])
except Exception as e:
    print(f"流式请求失败: {e}")
