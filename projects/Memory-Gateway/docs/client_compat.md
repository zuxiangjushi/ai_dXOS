# 客户端兼容矩阵

| 客户端 | 协议 | 端点 | 状态 |
|---|---|---|---|
| Open WebUI | OpenAI | /v1/chat/completions | ✅ |
| OpenClaw | OpenAI | /v1/chat/completions | ✅ |
| Cline | OpenAI + tools | /v1/chat/completions | ✅ |
| Continue | OpenAI + tools | /v1/chat/completions | ✅ |
| Cursor | OpenAI | /v1/chat/completions | ✅ |
| Aider | OpenAI | /v1/chat/completions | ✅ |
| Hermes | OpenAI | /v1/chat/completions | ✅ |
| Claude Code | Anthropic | /v1/messages | ✅ |
| Codex CLI | Responses API | /v1/responses | ✅ |
| ComfyUI | OpenAI（profile 关记忆） | /v1/chat/completions | ✅ |
| pi | 待识别 | 看日志 [ua/*] | 🔍 |

## 网关端点
- GET  /metrics                Prometheus 指标
- GET  /v1/models              动态透传底座
- POST /v1/chat/completions    OpenAI 标准
- POST /v1/messages            Anthropic 协议
- POST /v1/responses           OpenAI Responses API

## 未知客户端识别
    grep -a "\[ua" logs/gateway_*.log | tail -20
