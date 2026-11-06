"""MemoryHooks：pre-call 注入 Mem0 记忆 + post-call 入队写回"""
import asyncio
import os
import time

from contracts.credentials import PROFILES
from adapters.langfuse_trace import TraceAdapter
from app.metrics import memory_recall_total, memory_recall_hits
from adapters.web_search import get_web_search


class MemoryHooks:
    def __init__(self, auth, router, context_engine, queue, trace=None, metrics=None):
        self.auth = auth
        self.router = router
        self.ce = context_engine
        self.queue = queue
        self.trace = trace or TraceAdapter()
        self.metrics = metrics
        self._degraded_count = 0
        # ★ 用户级稳定内容缓存（user_id -> (content, ts)）
        self._stable_cache = {}
        self._stable_ttl = 60  # 60 秒过期

    async def _build_stable_context(self, ident) -> str:
        """用户级稳定内容（只依赖 user_id）"""
        user_id = ident.get("user_id", "")
        if not user_id:
            return ""
        import time as _t
        now = _t.time()
        cached = self._stable_cache.get(user_id)
        if cached and now - cached[1] < self._stable_ttl:
            return cached[0]

        parts = []

        # 1. 用户画像
        try:
            profile = self.ce._get_profile(ident)
            if profile:
                parts.append(f"[用户画像] {profile}")
        except Exception:
            pass

        # 2. Mem0 长期记忆（按 id 稳定排序）
        try:
            import os
            import httpx
            async with httpx.AsyncClient(timeout=2.5) as c:
                r = await c.get(
                    "http://127.0.0.1:8888/memories",
                    params={"user_id": user_id},
                    headers={"X-API-Key": os.environ.get("MEM0_ADMIN_KEY", "")})
                if r.status_code == 200:
                    body = r.json()
                    mems = body if isinstance(body, list) else body.get("results", [])
                    if not isinstance(mems, list):
                        mems = []
                    mems_sorted = sorted(mems, key=lambda x: str(x.get("id", "")))
                    texts = []
                    for m in mems_sorted[:8]:
                        t = (m.get("memory") or "").strip()
                        if t:
                            texts.append(t[:80])
                    if texts:
                        parts.append("[用户长期记忆] " + " | ".join(texts))
        except Exception as e:
            print(f"   [stable-ctx] Mem0 失败: {type(e).__name__}: {e}", flush=True)

        # 3. 用户文档标题
        try:
            import os
            import httpx
            async with httpx.AsyncClient(timeout=2.5) as c:
                r = await c.post(
                    "http://127.0.0.1:7700/indexes/documents/search",
                    headers={"Authorization": f"Bearer {os.environ.get('MEILISEARCH_API_KEY','')}"},
                    json={"q": "", "limit": 50,
                          "filter": f'user_id = "{user_id}"',
                          "sort": ["id:asc"]})
                if r.status_code == 200:
                    hits = r.json().get("hits", [])
                    seen = set()
                    titles = []
                    for h in sorted(hits, key=lambda x: str(x.get("id", ""))):
                        did = h.get("doc_id") or h.get("id")
                        t = h.get("title")
                        if did and did not in seen and t:
                            seen.add(did)
                            titles.append(t[:40])
                    if titles:
                        parts.append(f"[我的文档] {', '.join(titles[:10])}")
        except Exception:
            pass

        out = "\n".join(parts) if parts else ""
        self._stable_cache[user_id] = (out, now)
        import hashlib
        h = hashlib.md5(out.encode()).hexdigest()[:6]
        print(f"   [stable-ctx] user={user_id} mem0_len={sum(len(x) for x in [])} docs_len={sum(len(x) for x in [])} parts={len(parts)} len={len(out)} hash={h}", flush=True)
        return out

    async def _recall(self, ident, messages):
        """从 Mem0 检索相关记忆"""
        backend = os.environ.get("MEMORY_BACKEND", "mem0").lower()
        if backend != "mem0":
            return []
        query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                query = msg.get("content", "")
                break
        if not query:
            return []
        try:
            from adapters.mem0_adapter import get_mem0
            mem0 = get_mem0()
            results = await mem0.search(query, user_id=ident["user_id"], limit=30)
            hits = [r.get("memory", "") for r in results if r.get("memory")]
            memory_recall_total.labels(backend="mem0", status="hit" if hits else "miss").inc()
            memory_recall_hits.labels(backend="mem0").observe(len(hits))
            print(f"   [recall] Mem0 返回 {len(hits)} 条记忆", flush=True)
            for h in hits[:3]:
                print(f"      · {h[:60]}", flush=True)

            # ★ 记忆也用 reranker 重排（≥3 条才触发）
            if len(hits) >= 3:
                try:
                    from adapters.reranker import get_reranker
                    _rk = [{"content": h} for h in hits]
                    _rk2 = await get_reranker().rerank(query, _rk, top_k=30)
                    hits = [x.get("content", "") for x in _rk2 if x.get("content")]
                    print(f"   [recall] reranker 重排后 {len(hits)} 条", flush=True)
                except Exception as e:
                    print(f"   [recall] reranker 失败: {type(e).__name__}: {e}", flush=True)

            # ★ 记录访问日志（fire and forget）
            try:
                import asyncio as _aio
                from app.use_cases.access_logger import log_hits
                _aio.create_task(log_hits(ident.get('user_id', ''), query, 'mem0', results))
            except Exception:
                pass

            # ★ 影子调用 OpenViking（异步，不阻塞，不影响主流程）
            try:
                from adapters.openviking_shadow import shadow_query as _shadow_query
                import asyncio as _aio2
                _aio2.create_task(_shadow_query(
                    ident.get("user_id", "default_user"),
                    query,
                    {"results": [{"memory": h} for h in hits]},
                ))
                print(f"   [shadow] OpenViking 影子调用已触发", flush=True)
            except Exception as _shadow_err:
                print(f"   [shadow] 启动失败: {_shadow_err}", flush=True)

            return hits
        except Exception as e:
            print(f"   [recall] Mem0 失败: {type(e).__name__}: {e}", flush=True)
            memory_recall_total.labels(backend="mem0", status="error").inc()
            return []

    async def _recall_rag(self, ident, messages):
        """双源检索：Qdrant 语义 + Meili 关键词"""
        try:
            q = ""
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("role") == "user":
                    q = str(m.get("content", ""))
                    break
            if not q:
                return []

            user_id = ident.get("user_id", "")
            out = []
            seen = set()

            # 1. Qdrant 语义检索（min_score=0.5 过滤）
            try:
                from adapters.qdrant_rag import get_rag
                hits = await get_rag().search(q, user_id=user_id, limit=30)
                for h in hits:
                    if h.get("score", 0) < 0.4:
                        continue
                    c = (h.get("content") or "").strip()
                    if c and c not in seen:
                        seen.add(c)
                        out.append({
                            "title": h.get("title", ""),
                            "content": c[:500],
                            "source": "semantic",
                            "score": h.get("score", 0),
                        })
                if out:
                    print(f"   [rag] Qdrant 语义返回 {len(out)} 条", flush=True)
                try:
                    import asyncio as _aio
                    from app.use_cases.access_logger import log_hits
                    _aio.create_task(log_hits(user_id, q, 'rag_qdrant', out))
                except Exception:
                    pass
            except Exception as e:
                print(f"   [rag] Qdrant 失败: {type(e).__name__}: {e}", flush=True)

            # 2. Meili 关键词（补充）
            try:
                from adapters.meili_client import get_meili
                hits = await get_meili().search(q, user_id=user_id, limit=30)
                for h in hits:
                    c = (h.get("content") or "").strip()
                    if c and c not in seen:
                        seen.add(c)
                        out.append({
                            "title": h.get("title", ""),
                            "content": c[:500],
                            "source": "keyword",
                        })
                        if len(out) >= 8:
                            break
            except Exception:
                pass


            # 重排（bge-reranker-v2-m3）
            if len(out) >= 3:
                try:
                    from adapters.reranker import get_reranker
                    out = await get_reranker().rerank(q, out, top_k=30)
                    print(f"   [rag] 重排后 top3", flush=True)
                except Exception as e:
                    print(f"   [rag] 重排失败: {type(e).__name__}: {e}", flush=True)

            return out[:3]
        except Exception as e:
            print(f"   [rag] 检索失败: {type(e).__name__}: {e}", flush=True)
            return []


    async def _recall_kip(self, query: str, top_k: int = 5, data: dict = None) -> list:
        """KIP 知识库检索（新 177K 知识库）
        v5.0: KIP 检索对所有模型开启（记忆 + 知识库对所有客户端可用）
        只有 Web 搜索受 MG/ 前缀控制
        """
        if not query or not query.strip():
            return []
        try:
            import httpx as _hx
            async with _hx.AsyncClient(timeout=10.0) as c:
                # ★ v5.0: 用 Qwen3 新 collection
                import os as _os_k
                _kip_col = _os_k.environ.get("KIP_COLLECTION", "col_qwen3_06b")
                r = await c.post("http://127.0.0.1:8030/search", json={
                    "query": query[:500],
                    "top_k": top_k,
                    "use_rerank": True,
                    "collection": _kip_col,
                })
                if r.status_code == 200:
                    return r.json().get("hits", [])
        except Exception as e:
            print(f"   [kip] 失败: {type(e).__name__}: {e}", flush=True)
        return []

    # Web 搜索触发关键词
    WEB_TRIGGER_KEYWORDS = (
        "搜索", "搜一下", "查一下", "查查", "联网", "上网", "百度", "谷歌",
        "最新", "今天", "今天", "现在", "实时", "当前", "最近", "新闻",
        # ★ 扩展：事实查询类关键词
        "是什么", "什么是", "哪一天", "哪天", "多少钱", "怎么样", "怎么样",
        "放假", "安排", "规定", "政策", "标准", "版本", "价格", "是多少",
        "什么时间", "什么时候", "谁", "在哪", "在哪里",
        "search", "latest", "today", "news", "current",
    )

    PERSONAL_QUERY_PATTERNS = (
        "我叫什么", "我的名字", "我叫", "我住在", "我来自",
        "我喜欢", "我做什么", "我从事", "我的工作",
        "我之前", "我上次", "我说过", "还记得", "记住",
        # ★ 上下文测试类：不联网（精确匹配）
        "前面说的", "刚才说的", "上文提到", "之前说的",
        "上一轮", "上一句", "上一段",
    )

    def _is_personal_query(self, text: str) -> bool:
        """个人问题 → 只走记忆，不走联网"""
        if not text:
            return False
        if any(p in text for p in self.PERSONAL_QUERY_PATTERNS):
            return True
        # ★ 正则匹配 "第N轮" 上下文测试类
        import re as _re
        if _re.search(r'第\s*\d+\s*轮', text):
            return True
        return False

    def _should_search(self, text: str) -> bool:
        """判断是否需要联网搜索"""
        if not text:
            return False
        if self._is_personal_query(text):
            return False
        t = text.lower()
        return any(kw in t for kw in self.WEB_TRIGGER_KEYWORDS)

    async def _recall_web(self, ident, messages, data=None):
        """关键词触发时调用 SearXNG 搜索"""
        # ★ v5.0: 无 MG/ 前缀 → 跳过
        if data is not None and data.get("_has_mg_prefix") is False:
            print(f"   [web] 无 MG/ 前缀 → 跳过 Web 搜索", flush=True)
            return []
        # ★ v5.0: MG_ 强制搜索优先于用户黑名单
        _force = (data or {}).get("_force_search")
        if _force is True:
            print(f"   [web] MG_ 强制搜索 → 绕过黑名单检查", flush=True)
        else:
            # 搜索开关（仅按 User-Id）
            import os as _os_off
            _sd_users = set(s.strip().lower() for s in _os_off.environ.get("SEARCH_DISABLED_USERS", "").split(",") if s.strip())
            if _sd_users:
                _uid = (ident.get("user_id") or "").lower() if ident else ""
                if _uid in _sd_users:
                    print(f"   [search-off] User={_uid} 黑名单 → 跳过", flush=True)
                    return []
        
        try:
            q = ""
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("role") == "user":
                    q = str(m.get("content", ""))
                    break
            # ★ 能力边界分类（先于关键词触发判断）
            if q:
                try:
                    from app.use_cases.query_classifier import classify_with_rule
                    _cat, _rule = classify_with_rule(q)
                    print(f"   [classify] {_cat} → {_rule.behavior}", flush=True)
                    if data is not None:
                        data["_classify"] = {"category": _cat, "behavior": _rule.behavior}
                    if _rule.behavior == "must_refuse":
                        if data is not None:
                            data["_force_refuse"] = True
                            data["_force_refuse_reason"] = _rule.reason
                        print(f"   [classify] 标记拒答（{_cat}）", flush=True)
                        return []
                    if _rule.behavior == "no_cite":
                        print(f"   [classify] 跳过 web 搜索（{_cat}）", flush=True)
                        return []
                except Exception as _e:
                    print(f"   [classify] 分类失败，继续默认流程: {_e}", flush=True)

                # ★ Freshness 分级
                try:
                    from app.use_cases.query_classifier import classify_freshness
                    _fresh = classify_freshness(q)
                    print(f"   [freshness] {_fresh}", flush=True)
                    if data is not None:
                        data["_freshness"] = _fresh
                except Exception as _fe:
                    print(f"   [freshness] 分类失败: {_fe}", flush=True)

            # ★ freshness 明确（realtime/recent/historical）→ 绕过关键词检查
            _fresh_early = (data or {}).get("_freshness", "normal")
            _should_by_freshness = _fresh_early in ("realtime", "recent", "historical")

            if not q:
                return []
            if not _should_by_freshness and not self._should_search(q):
                return []
            # ★ 走 Discovery 聚合器（SearXNG + Wukong）
            from adapters.discovery import get_discovery
            from app.use_cases.evidence_engine import get_evidence_engine
            from app.use_cases.quality_gate import get_quality_gate
            from contracts.research import QueryPlan
            _orig_q = q  # ★ 保存原始 query（重试时用）
            plan = QueryPlan(
                plan_id="web_hook",
                need_web_search=True,
                reason="关键词触发",
                queries=[q],
                max_candidates=5,
            )
            # ★ 质量门禁循环（最多 2 次迭代）
            best_hits = []
            best_bundle = None
            best_decision = None

            # ★ 按 freshness 决定 provider 过滤
            _fresh = (data or {}).get("_freshness", "normal")
            if _fresh == "realtime":
                _exclude = ["meili_web"]  # 实时问题不查索引
                _max_iter = 1  # 不重试（要快）
            elif _fresh == "historical":
                _exclude = ["meili_web"]  # 历史问题优先 SearXNG archive
                _max_iter = 1
            else:
                _exclude = None
                _max_iter = 2  # 允许重试

            for iteration in range(1, _max_iter + 1):
                result = await get_discovery().discover(plan, exclude_providers=_exclude)
                hits = result.get("raw", [])
                sources = result.get("sources", [])
                dist = result.get("distribution", {})

                if hits:
                    dist_str = ", ".join(f"{k}={v}" for k, v in dist.items())
                    print(f"   [web] iter={iteration} Discovery 返回 {len(hits)} 条 ({dist_str})", flush=True)

                if not hits:
                    return []

                # Evidence Engine
                bundle = await get_evidence_engine().build(q, hits, sources)

                # 记录当前最佳
                if best_bundle is None or bundle.authority_score > best_bundle.authority_score:
                    best_hits = hits
                    best_bundle = bundle

                # 给每条 hit 加引用编号
                eid_map = {s.source_id: ev.evidence_id
                           for s, ev in zip(sources, bundle.evidences)}
                cit_map = {c.evidence_id: c.display_index
                           for c in bundle.citations}
                for h in hits:
                    url = h.get("url", "")
                    for s in sources:
                        if s.url == url:
                            eid = eid_map.get(s.source_id)
                            cidx = cit_map.get(eid, 0)
                            if cidx:
                                h["citation_index"] = cidx
                                h["content"] = f"[{cidx}] " + (h.get("content") or "")
                            h["authority"] = s.authority_score
                            break

                print(f"   [evidence] iter={iteration} "
                      f"{len(bundle.evidences)} 证据, "
                      f"{len(bundle.citations)} 引用, "
                      f"{len(bundle.conflicts)} 冲突, "
                      f"auth={bundle.authority_score:.2f}", flush=True)

                # Quality Gate
                decision = get_quality_gate().evaluate(bundle, plan, iteration)
                best_decision = decision
                print(f"   [quality] iter={iteration} verdict={decision.verdict} "
                      f"score={decision.score:.3f} "
                      f"relevance={decision.breakdown.get('relevance', 0):.2f} "
                      f"authority={decision.breakdown.get('authority', 0):.2f} "
                      f"freshness={decision.breakdown.get('freshness', 0):.2f}", flush=True)

                if decision.verdict == "pass":
                    return hits
                elif decision.verdict == "retry":
                    # ★ 分数提升检查：iter≥2 且分数没变 → 直接放弃，避免浪费
                    if iteration >= 2 and best_decision is not None:
                        _prev = best_decision.score
                        if abs(decision.score - _prev) < 0.01:
                            print(f"   [quality] 分数未提升（{_prev:.3f}→{decision.score:.3f}），放弃重试", flush=True)
                            return best_hits

                    # ★ 用 _orig_q 生成建议（不累加）
                    _base = _orig_q or (plan.queries[0] if plan.queries else "")

                    # 优先用 suggestions（基于原 query 的）
                    if decision.retry_suggestions:
                        plan.queries = decision.retry_suggestions
                        print(f"   [quality] 重试 query: {plan.queries}", flush=True)
                        continue

                    # 兜底：基于原 query + 有效词
                    # 优先级：时效性问题 → "最新"；一般性问题 → 年份
                    if "今天" in _base or "最近" in _base or "最新" in _base:
                        _hint = "最新消息"
                    else:
                        import datetime
                        _hint = f"{datetime.date.today().year}"
                    plan.queries = [f"{_base} {_hint}"]
                    print(f"   [quality] retry 无建议，兜底重试: {plan.queries}", flush=True)
                    continue
                else:  # give_up
                    print(f"   [quality] 放弃，返回最佳结果（{len(best_hits)} 条）", flush=True)
                    return best_hits

            return best_hits
        except Exception as e:
            print(f"   [web] 搜索失败: {type(e).__name__}: {e}", flush=True)
            return []

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):

        span = self.trace.start_span("pre_call", {"model": data.get("model")})
        t0 = time.perf_counter()
        print(f"   [pre-call] 进入钩子", flush=True)

        # ★ 优先用调用方传入的 _ident（含 Header 解析结果）
        ident = data.get("_ident")
        if not ident:
            ident = await self.auth.authenticate(data.pop("_bearer", None) or "")
            data["_ident"] = ident

        # 保存原始用户消息
        original = ""
        for msg in reversed(data.get("messages", [])):
            if msg.get("role") == "user":
                original = msg.get("content", "")
                break
        data["_original_user_content"] = original
        print(f"   [pre-call] user={ident['user_id']} 原始消息: {original[:40]}", flush=True)

        prof = PROFILES.get(ident.get("agent_type", "claude_code"))
        if not prof:
            return data

        if not prof.memory_inject:
            data["max_tokens"] = min(data.get("max_tokens", prof.max_output_tokens),
                                     prof.max_output_tokens)
            return data

        # ★ 检索 Mem0 记忆
        memory_hits = []
        try:
            memory_hits = await asyncio.wait_for(
                self._recall(ident, data["messages"]),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            print(f"   [pre-call] 检索超时（>2s），降级为无记忆", flush=True)
            memory_recall_total.labels(backend="mem0", status="timeout").inc()
            memory_recall_hits.labels(backend="mem0").observe(0)
        except Exception as e:
            print(f"   [pre-call] 检索失败: {type(e).__name__}: {e}", flush=True)
            memory_recall_total.labels(backend="mem0", status="error").inc()
            memory_recall_hits.labels(backend="mem0").observe(0)

        # ★ 检索 RAG（Meilisearch）
        rag_hits = []
        try:
            rag_hits = await asyncio.wait_for(
                self._recall_rag(ident, data["messages"]),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            print(f"   [pre-call] RAG 检索超时（>2s），降级为无 RAG", flush=True)
            rag_hits = []
        except Exception as e:
            print(f"   [pre-call] RAG 检索失败: {type(e).__name__}: {e}", flush=True)
            rag_hits = []

        # ★ KIP 知识库检索（新 177K 知识库）
        kip_hits = []
        try:
            # 先异步发请求（预热）
            kip_task = asyncio.create_task(self._recall_kip(original, data=data))
            
            # 同时做其他处理（不阻塞）
            # 其他 pre-call 逻辑已经执行...
            
            # 最后再等 KIP 结果（已预热）
            try:
                kip_hits = await asyncio.wait_for(kip_task, timeout=10.0)
                if kip_hits:
                    print(f"   [kip] 返回 {len(kip_hits)} 条", flush=True)
            except asyncio.TimeoutError:
                print(f"   [kip] 超时", flush=True)
        except asyncio.TimeoutError:
            print(f"   [kip] 超时（>3s）", flush=True)
        except Exception as e:
            print(f"   [kip] 失败: {type(e).__name__}", flush=True)

        # ★ LLM 摘要（如果历史较长）
        precomputed_summary = ""
        try:
            old_msgs = data["messages"][:-8] if len(data.get("messages", [])) > 10 else []
            if len(old_msgs) >= 3:
                precomputed_summary = await asyncio.wait_for(
                    self.ce._llm_summarize(old_msgs),
                    timeout=8.0
                )
        except asyncio.TimeoutError:
            print(f"   [pre-call] LLM 摘要超时，降级到拼接", flush=True)
        except Exception as e:
            print(f"   [pre-call] LLM 摘要异常: {type(e).__name__}", flush=True)

        # ★ Web 搜索（关键词触发）
        web_hits = []
        try:
            web_hits = await asyncio.wait_for(
                self._recall_web(ident, data["messages"], data),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            print(f"   [pre-call] Web 搜索超时（>20s）", flush=True)
            web_hits = []
        except Exception as e:
            print(f"   [pre-call] Web 搜索失败: {type(e).__name__}", flush=True)
            web_hits = []

        # ★ web 触发后：构造引用映射 + 禁用 thinking + 加大 max_tokens
        if web_hits:
            # ★ 构造 N → url 映射（引用跳转） + N → meta 映射（参考列表）
            _url_map = {}
            _citation_meta = {}
            for _h in web_hits:
                _cidx = _h.get("citation_index")
                _u = _h.get("url")
                if _cidx and _u:
                    _url_map[int(_cidx)] = _u
                    _a = _h.get("authority") or 0.5
                    if _a >= 0.9:
                        _tag = "[官方]"
                    elif _a >= 0.6:
                        _tag = "[媒体]"
                    else:
                        _tag = "[社区]"
                    _citation_meta[int(_cidx)] = {
                        "tag": _tag,
                        "url": _u,
                        "title": (_h.get("title") or "")[:60],
                    }
            if _url_map:
                data["_citation_urls"] = _url_map
                print(f"   [cite] 构造引用映射 {len(_url_map)} 条", flush=True)
            if _citation_meta:
                data["_citation_meta"] = _citation_meta
                print(f"   [cite] 构造参考列表 {len(_citation_meta)} 条", flush=True)

            data["chat_template_kwargs"] = {"enable_thinking": False}
            if not data.get("max_tokens") or data["max_tokens"] < 2000:
                data["max_tokens"] = 2000
            print(f"   [pre-call] web 触发：禁用 thinking, max_tokens={data['max_tokens']}", flush=True)

        # ★ 组装上下文（记忆在 messages 尾部）
        try:
            # ★ 同步调用（ce.build 是同步函数）
            stable_context = await self._build_stable_context(ident)
            bundle = self.ce.build(ident, data["messages"], None,
                                   memory_hits, rag_hits, web_hits,
                                   precomputed_summary=precomputed_summary,
                                   stable_context=stable_context)
            before = len(data["messages"])
            # ★ 拒答提示（能力边界分类结果）
            if data.get("_force_refuse"):
                _rr = data.get("_force_refuse_reason", "此问题涉及未来/不存在的信息")
                _refuse_msg = {
                    "role": "system",
                    "content": f"【系统提示】{_rr}。请明确告知用户你无法回答此问题，不要编造任何信息。",
                }
                data["messages"] = [_refuse_msg] + list(data["messages"])
                print(f"   [classify] 注入拒答提示", flush=True)

            data["messages"] = self._append_context(data["messages"], bundle)

            # ★ KIP 结果注入（作为独立 system message）
            if kip_hits:
                kip_text = "## 知识库检索结果（KIP）\n\n以下是相关参考资料：\n\n"
                for i, h in enumerate(kip_hits, 1):
                    src_name = h.get("source_name", "")[:80]
                    cat = h.get("category", "")
                    h1 = h.get("h1", "")[:80]
                    text = (h.get("text") or "")[:500]
                    kip_text += f"[K{i}] 《{src_name}》({cat})"
                    if h1:
                        kip_text += f"\n章节: {h1}"
                    kip_text += f"\n内容: {text}\n\n"
                kip_text += "请在回答时引用以上资料（用 [K1]、[K2] 等标记）。"
                # 插入到 system 之后的第 1 个位置
                insert_pos = 0
                for idx, m in enumerate(data["messages"]):
                    if m.get("role") == "system":
                        insert_pos = idx + 1
                        break
                data["messages"].insert(insert_pos, {
                    "role": "system",
                    "content": kip_text,
                })
                print(f"   [kip] 注入 {len(kip_hits)} 条 KIP 结果", flush=True)

            after = len(data["messages"])
            print(f"   [pre-call] 注入 {after - before} 段上下文（总 {after} 条 messages）", flush=True)
            self.trace.log_event(span, "context_built", {"sections": after - before})
        except asyncio.TimeoutError:
            self._degraded_count += 1
            print(f"   [pre-call] 上下文组装超时，降级", flush=True)
        except Exception as e:
            self._degraded_count += 1
            print(f"   [pre-call] 上下文组装失败: {type(e).__name__}: {e}", flush=True)

        self.trace.end_span(span, {"elapsed_ms": (time.perf_counter() - t0) * 1000})
        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        ident = data.get("_ident")
        if not ident:
            print("   [post-call] _ident 缺失，跳过", flush=True)
            return response

        prof = PROFILES.get(ident.get("agent_type"))
        if not prof or not prof.memory_writeback:
            return response

        try:
            await self.queue.enqueue(ident, data, response)
            print(f"   [post-call] 已入队 user={ident['user_id']}", flush=True)
        except Exception as e:
            print(f"   [post-call] 入队失败: {type(e).__name__}: {e}", flush=True)
        return response

    def _append_context(self, messages, bundle):
        """把记忆/RAG/Web 分类注入，明确标注引用编号"""
        sections = bundle.get("sections", [])

        memory_parts = []
        rag_parts = []
        web_parts = []

        for name, content in sections:
            if name not in ("retrieved_memory", "retrieved_rag", "web_results"):
                continue
            if not isinstance(content, list):
                continue
            for item in content:
                if isinstance(item, dict):
                    c = item.get("content") or item.get("memory") or ""
                    title = item.get("title", "")
                    cidx = item.get("citation_index")
                    if name == "web_results":
                        # 去掉可能已有的 [1] 前缀
                        import re as _re
                        c_clean = _re.sub(r'^\[\d+\]\s*', '', c)
                        # ★ 权威分级标记
                        _auth = item.get("authority")
                        if _auth is None:
                            _auth = 0.5
                        if _auth >= 0.9:
                            _tag = "[官方]"
                        elif _auth >= 0.6:
                            _tag = "[媒体]"
                        else:
                            _tag = "[社区]"
                        if cidx:
                            if title:
                                c = f"[{cidx}] {_tag} {title[:60]}: {c_clean}"
                            else:
                                c = f"[{cidx}] {_tag} {c_clean}"
                        elif title:
                            c = f"{_tag} {title} — {c_clean}"
                        else:
                            c = f"{_tag} {c_clean}"
                else:
                    c = str(item)
                c = c.strip()
                if not c:
                    continue
                if name == "retrieved_memory":
                    memory_parts.append(c[:200])
                elif name == "retrieved_rag":
                    rag_parts.append(c[:400])
                elif name == "web_results":
                    web_parts.append(c[:500])

        if not (memory_parts or rag_parts or web_parts):
            return messages

        import datetime
        today = datetime.date.today().isoformat()
        ref_lines = [f"【当前日期】{today}"]

        if memory_parts:
            ref_lines += ["", "【用户长期记忆】"]
            for c in memory_parts[:5]:
                ref_lines.append(f"- {c}")

        if rag_parts:
            ref_lines += ["", "【用户上传的文档】"]
            for c in rag_parts[:3]:
                ref_lines.append(f"- {c}")

        if web_parts:
            ref_lines += [
                "",
                "【联网搜索结果（实时数据，来自互联网）】",
                "",
                "⚠️ 必须遵守的回答规则（违反视为错误）：",
                "1. 任何来自下方搜索结果的事实，陈述末尾必须紧跟 [1]、[2] 这样的引用编号",
                "2. 回答中若包含具体数字/日期/名称，必须有至少 1 个引用编号（如 [1]）",
                "3. 只有「完全不知道」或「证据不足」才能不引用",
                "4. 多个结果冲突时，优先引用最接近当前日期的",
                "5. 来源分级：[官方] > [媒体] > [社区]，冲突时优先级别最高的",
                "6. 若只有 [社区] 来源，需明确说明「仅社区来源，请谨慎参考」",
                "",
                "示例：",
                "  ✅ 正确：重庆今日最高气温 27℃，最低 20℃ [1]",
                "  ❌ 错误：重庆今日最高气温 27℃（缺引用）",
                "",
                "搜索结果（每条已带 [1] [2] 等编号）：",
            ]
            for c in web_parts[:5]:
                ref_lines.append(f"{c}")

        ref_text = "\n".join(ref_lines)
        ref_msg = {"role": "system", "content": ref_text}

        idx = len(messages)
        for i, m in enumerate(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                idx = i
                break
        return list(messages[:idx]) + [ref_msg] + list(messages[idx:])

