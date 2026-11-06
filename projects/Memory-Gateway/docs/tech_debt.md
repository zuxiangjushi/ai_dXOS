
## [P2] 待修清单（2026-09-11 追加）

### [P2-1] ContextEngine 中文 token 估算器低估 2 倍
- 位置: app/use_cases/context_engine.py `count()`
- 现状: `len(text) // 2`，对中文实际 token 数低估约 2 倍
- 影响: 真实超窗时未触发截断，上游可能报 max_length
- 修法: 装 tiktoken 或 Qwen tokenizer；或粗暴改成 `len(text)`
- 何时修: P2

### [P2-2] Prometheus Counter 无持久化
- 现状: 网关重启计数器归零
- 影响: 日报只能看"自上次重启以来"
- 修法: Pushgateway 或定期快照到 PG
- 何时修: P2

### [P2-3] [BOOT] _reconciler 没打印
- 位置: fastapi_gateway.py lifespan
- 影响: 启动日志看不到 reconciler 状态
- 何时修: 顺手

### [P2-4] pre-call 检索失败异常消息为空
- 位置: adapters/litellm_hooks.py `_recall` except 分支
- 现象: 日志显示 `[pre-call] 检索失败:`，e 的 str 为空
- 根因: 大概率 asyncio.TimeoutError（wait_for 2s）
- 修法: except 打印 type(e).__name__，把超时和异常分开
- 何时修: 下一轮

### [P2-5] 超窗请求未拦截 → 客户端收 400
- 现象: 40000 字输入 → 网关转发 → 上游 400 → 客户端看到 400
- 根因: [P2-1] 估算器低估 2 倍
- 影响: 用户体验差（本该网关截断，让上游跑通）
- 何时修: P2-1 修完后自然解决

### [P2-7] litellm_hooks 外层 timeout 补丁未生效
- 位置: adapters/litellm_hooks.py line 85
- 现象: 外层 except 只捕获 Exception，没有 TimeoutError 分支
- 根因: 补丁脚本用 `if 'asyncio.TimeoutError' in s` 判断，误命中别处字符串
- 影响: Mem0 超时时埋点看不到 status="timeout"
- 修法: 用行号定位 line 85，手动加分支
- 何时修: 明天

### [P3] writeback_worker.py 第 8-9 行重复 import
- 位置: app/workers/writeback_worker.py
- 现象: trust_policy 的 import 出现两次
- 影响: 无（Python 幂等），只是不干净
- 何时修: 顺手

### [P1-8] 流式请求完成埋点缺失
- 位置: fastapi_gateway.py `_proxy_stream()` 函数末尾
- 现象: gateway_requests_total{stream="true"} 只有 started，无 200
-        gateway_duration_seconds 完全没有流式数据
- 影响: 流式成功率/耗时无法监控（而客户端 99% 用流式）
- 修法: _proxy_stream 正常结束前加：
       gateway_requests_total.labels(model=..., stream="true", status="200").inc()
       gateway_duration_seconds.labels(model=..., stream="true").observe(...)
- 何时修: 明天第一个任务

### [P2-9] Mem0 empty 时降级自研写入，可能重复写入
- 现象: memory_write_total{backend="mem0",status="empty"} 2
        memory_write_total{backend="native",status="ok"} 2
- 疑问: Mem0 判"无信息量"后，自研写入的"内容"是什么？
- 待观察: 是否出现同内容双写
- 暂不改

### [P2-11] 流式 started > 200，有未完成请求
- 现象: stream="true" 的 started=2，200=1（差 1）
- 可能原因: 客户端断连 / post-call 异常
- 待观察: 5 用户灰度期间该比值
- 阈值: 若 (started-200)/started > 2% → 修
- 暂不改

### [P3-修正] writeback_worker 的 2 行 trust_policy import 不是重复
- 我判断错：两行内容不同（一行含 is_trusted_for_longterm，一行含 get_ttl）
- 删除任一都会 break
- 撤销此条：不需要修

## [已完成] 2026-09-11 晚 批量修复

- [P2-1]  token 估算器 + _truncate 重写（list 逐条截 / str 截）✅
- [P2-3]  [BOOT] _reconciler 打印 ✅
- [P2-7]  litellm_hooks 超时分支（status=timeout）✅
- [P2-12] 内部任务跳过记忆注入（原子替换）✅
- [P3]    撤回（writeback_worker 的两行 import 不是重复）❌ 误判

## 待修清单（保留）
- [P2-2]  Prometheus Counter 无持久化
- [P2-4]  pre-call 检索失败异常消息为空
- [P2-5]  超窗请求未拦截（已缓解，非完全解决）
- [P2-6]  Mem0 search 冷启动慢
- [P2-9]  Mem0 empty 时降级自研写入（观察中）
- [P2-10] 流式 generator 客户端断连未埋点
- [P2-11] 流式 started > 200（观察中）

### [P2-13] bge-m3 embedding 服务偶发极慢（188s）
- 现象: 2026-09-11 晚 20:15 左右，bge-m3 单次 188s
- 现在: 已自愈，0.06s
- 可能原因: 冷启动 / CPU 抖动 / 磁盘 IO
- 缓解: 网关 wait_for 可能需要 8s；或加监控
- 待观察: 是否重现

## [已完成] 2026-09-12 最后一公里修复

### 根因
- context_engine.build() 函数体用了 stable_context，但签名未声明
- 导致 pre-call TypeError → 降级为无记忆透传
- 表现：模型拒绝回答（隐私模板），实际是"根本没收到记忆"

### 修法
- build() 签名加 stable_context="" 参数（第 118 行）
- 用行号精确定位，不用字符串匹配

### 验证
- 记忆闭环：zhangsan "我住哪" → "北京" ✅
- RAG 闭环：inject_test "缓存用什么" → "Redis" ✅
- stable-ctx len=297 hash=ba41f5（前缀稳定）

### 教训（SOP 新增）
**改函数签名和函数体必须原子操作，补丁后必须打印签名确认。**

## [已完成] 2026-09-12 v5.0 Phase 0-3

### 新增能力
- 契约层 contracts/research.py（12 dataclass + 12 tests）
- Discovery 双源（SearXNG + Meili web_index）
- Evidence Engine（Evidence + Claim + Citation + Conflict）
- Claim Extractor（qwen3_32b + enable_thinking=False）
- Quality Gate（5 维评分 + PASS/RETRY/GIVE_UP）
- Evaluation Harness（evals/research_eval.py）

### 关键优化
- 延迟：33.6s → 7.7s（-77%）
- 禁用 thinking（web 触发时自动）
- 搜索驱动建索引（用过一次的内容秒回）

### 遗留
- Phase 4: 完整评测集（当前 5 题）
- 延迟进一步优化：7.7s → <5s
- 悟空引擎包装成 HTTP 服务（Go）
- Open WebUI 多用户隔离

### [P2-14] Open WebUI 收到大量 PATCH /api/models/* 405
- 现象: Open WebUI 日志有几十条 PATCH 405
- 根因: 某个外部同步脚本调用 Open WebUI 不支持的 PATCH 方法
- 影响: 无（用户使用正常）
- 修复: 找到同步脚本，改用正确 API（PUT/POST）
- 何时修: P2

### [P2-14 已止血] sync_openwebui_models.py PATCH 405
- 根因: /ai/ai_dxos/scripts/sync_openwebui_models.py 用 requests.patch，
  Open WebUI 不支持 PATCH（405）
- 影响: 每分钟 16 次无效请求，日志噪音；模型启用/禁用同步无效
- 止血: crontab 已注释（备份 /tmp/crontab.bak.*）
- 正解（P3）: 改写走 config API 更新 model_ids 白名单，
  或网关侧过滤 /v1/models
- 何时修: P3

### [P3] 引用 URL 尾部标点被吃进链接
- 现象: [1](url)。 中，末尾中文句号被 Markdown 解析为 URL 一部分
- 影响: 浏览器地址栏多一个 。，但能正常打开页面
- 修复: 网关 _linkify_citations 时正则排除尾部标点
- 何时修: P3

### [P2 已修] Quality Gate verdict=retry 但 retry_suggestions 为空
- 现象: 日志 verdict=retry score=0.653 但直接返回 best_hits，没重试
- 根因: _generate_retry_suggestions 的触发条件（authority<0.5 / freshness<0.4 / coverage<0.5）
        在实际场景下可能都不满足，导致 suggestions 为空
- 影响: 可观测性差
- 修复: 无论是否有 suggestions，都打印 verdict=retry 的具体原因
- 何时修: P2

### [P2] howto/compare 类答案过长（24s）
- 现象: 分类器正确跳过 web，但模型默认生成 1600+ 字长答案，耗时 24s
- 根因: 非 bug，是 yy38_27b 生成速度 ~60 字/s 的物理极限
- 修复选项:
  1. system prompt 对非 realtime/factual 类加"简洁回答"
  2. 网关侧动态设 max_tokens（howto/compare → 800）
  3. 换 qwen3_32b（快 3.5 倍）
- 何时修: P2

### [P3 已修] regression_clients.sh 单引号阻止 $MODEL 展开
- 现象: 脚本发送 "model":"$MODEL" 字面量，上游 400
- 根因: bash 单引号内不做变量展开
- 修法: '"$MODEL"' 拼接
- 教训: shell 脚本里 JSON 拼变量必须用 '"$VAR"' 或双引号转义

### [P3 已修] 边界扫描替换误吞模块级变量
- 现象: 替换 _generate_retry_suggestions 时，END = "\n\ndef " 匹配到 def get_quality_gate，
        把中间 _gate = None 也吞了，导致 NameError
- 教训: 边界扫描的 END 要选在替换目标内，不是"下一个 def"（会吞中间代码）
- 修法: 加回 _gate = None


### [P3] authority 阈值边缘导致经常 retry
- 现象: authority=0.54 一直 >= 0.5 但接近边界，每次 realtime 都 retry 一次
- 影响: 多一次 3.5s 搜索（虽然分数未提升会放弃）
- 修复: authority 阈值从 0.5 调到 0.45
- 何时修: 观察几天，若经常触发再调

### [P3] 评测脚本对"不该引用"的类别语义不适配
- 现象: compare/howto 期望 min 0.5，unanswerable 期望 max 0.3，但系统正确行为是 0 引用
- 根因: citation_precision 定义为"有引用的都正确"，0 引用时默认为 1.0，
        与"该类别不该引用"的语义冲突
- 影响: 评测输出看似失败，实际系统行为正确
- 修复: 对 compare/howto/unanswerable 用新指标（如 refusal_rate / appropriate_silence）
- 何时修: P3

### [权衡] authority retry 让延迟 +36%
- 现象: authority 0.5→0.6 后，realtime p50 从 7.83s → 10.68s
- 根因: site:gov.cn retry 真生效，每次 realtime 走两次搜索
- 收益: citation_precision 0.867 → 1.0，authority 0.54 → 0.81
- 决策: 保留（质量优先）
- 缓解: 换 qwen3_32b（快 3.5 倍）或 authority 回调 0.45

### [层次1 已交付] 稳定性增强
- 修 A: mem0_adapter 无状态 httpx（每次新建连接）
  → Mem0 重建后网关自动重连，不用重启
- 修 B: sync_all_models.sh 每分钟跑（原 5 分钟）
  → 底座切换 1 分钟内自愈
- 修 C: compose 硬编码 OPENAI_MODEL=yy38_27b
  → 消除 shell 变量优先级问题
- 修 D: deploy/.env 提供 compose 变量
  → 不再依赖外部 export

### [层次2 待做] 能力代理
- 目标: 用"能力抽象"替代"硬编码模型名"
- 架构: 客户端 → capability://xxx → 代理 → 底座
- 收益: 零硬编码 / 秒级切换 / 动态最优选型
- 成本: 4h
- 何时做: 明天

### [P1 已修] LongCite CPU 资源竞争
- 现象: LongCite 占 1.5 核 CPU、37GB 内存
- 修复: taskset -c 0-3 限定 4 核
- 效果: 不抢底座 CPU

### [P1] 底座模型动态切换导致测试失败
- 现象: 底座从 yy38_27b 切到 qwen38_27b_f8，硬编码测试 400
- 根因: 底座按需启停，测试脚本/手动 curl 硬编码
- 修复: 所有测试用动态 model
- 已修: 评测、回归脚本（用 model_picker）
- 未修: 手动 curl 测试（靠习惯）

### [已交付] 参数调优（10 模型全覆盖）
- config/model_params.yaml: 10 模型基线 + 5 分类系数
- app/use_cases/param_tuner.py: 优先级 + clamp
- 网关接入: [param] 日志可见
- 范围: 8 个生成模型（2 个 skip）
- 与底座完全解耦（只改 HTTP body）

### [可选] 未来增强
- A/B 测试超参（需评测集）
- 按用户个性化参数
- 动态 temperature（根据回答长度反馈）

### [P3 已交付] A/B 测试超参框架
- evals/ab_test.py: 跑 A/B 两组
- evals/ab_compare.py: 对比
- PARAM_TUNING_ENABLED 开关
- 首次结果: A 组 15/15，延迟 5.15s
- 问题: B 组被模型切换污染
- 待重跑: 固定模型 + 样本 30+

### [P2 已修] RAG 大文件上传超时
- 现象: 1.1M 文件上传 300s 超时
- 根因: bge-m3 单批 2.5s × 100 批 = 250s
- 修复:
  1. Qdrant 批量 upsert
  2. rag_indexer 批处理（BATCH=10）
  3. bge-m3 限流（semaphore）
  4. RAG 上传异步化（> 200KB 走后台）
- 效果: 上传 0.1s 返回，后台处理

### [P3] bge-m3 吞吐瓶颈
- 现象: 单批 3 条 2.5s，约 1.2 条/秒
- 影响: 大文件后台处理时间长
- 优化方向:
  - 换 TEI/SGLang 引擎
  - 多副本 + 负载均衡
  - 升级 GPU
- 何时修: P3
