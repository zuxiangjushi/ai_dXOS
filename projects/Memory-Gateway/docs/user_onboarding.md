# Memory-Gateway 用户接入指南

## Open WebUI 配置（3 分钟）

1. Settings → Connections → OpenAI API
2. API Base URL: `http://192.168.10.132:9982/v1`
3. API Key: `<从 Memory-Gateway 管理端获取, 勿提交真实值>`
4. Add Custom Header: `X-User-Id: <你的名字拼音>`
5. Save

## 验证

1. 发："记住，我住在北京"
2. 等 30 秒
3. 发："我住在哪"
4. 答"北京市" → 成功

## 常见问题

- 回答"不知道" → 等 30 秒重试
- 换 X-User-Id 后记忆丢 → 记忆按 ID 隔离，请固定
