# Memory-Gateway 用户接入指南 v2（5 用户灰度）

## 特性
- 长期记忆（记住你说的话）
- 实时联网（天气/新闻/最新版本）
- 引用可验证（[1] [2]）

## 5 用户名单
| # | 用户名 | X-User-Id | 客户端 |
|---|---|---|---|
| 1 | 张三 | zhangsan | Open WebUI |
| 2 | 李四 | lisi | Open WebUI |
| 3 | 王五 | wangwu | Claude Code |
| 4 | 赵六 | zhaoliu | Cline |
| 5 | 钱七 | qianqi | Continue |

## Open WebUI 配置
1. Settings → Connections → OpenAI API
2. Base URL: http://192.168.10.132:9982/v1
3. API Key: <从管理员获取>
4. Custom Header: X-User-Id = <你的名字拼音>
5. Save

## Claude Code 配置
export ANTHROPIC_BASE_URL="http://192.168.10.132:9982"
export ANTHROPIC_API_KEY="<从管理员获取>"
export X_USER_ID="wangwu"

## 验证（每用户 2 分钟）
1. 记忆：说"记住我住在北京" → 等 30 秒 → 问"我住在哪" → 应答"北京"
2. 联网：问"重庆今天气温" → 应答含 [1]
3. 隔离：新用户问"我住在哪" → 不应看到别人的记忆

## 常见问题
- 模型不记得 → 等 30 秒（Mem0 抽取）
- 引用点不动 → 正常，后续加链接
- 联网搜不到 → 检查是否含触发词（搜索/查/最新/今天）
