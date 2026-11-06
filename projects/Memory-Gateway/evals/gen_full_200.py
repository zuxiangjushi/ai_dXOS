"""生成 20 角色 × 25 会话 + 200 问题的完整评测集"""
import json
import random
random.seed(42)

TOPICS = [
    ("Web 框架", ["FastAPI", "Django", "Gin", "Express"], 0, 1),
    ("数据库",   ["PostgreSQL", "MySQL", "TiDB", "MongoDB"], 0, 1),
    ("缓存",     ["Redis", "KeyDB", "Memcached"], 0, 1),
    ("消息队列", ["Kafka", "RabbitMQ", "Pulsar", "NATS"], 0, 1),
    ("向量库",   ["Milvus", "Qdrant", "pgvector", "Weaviate"], 0, 1),
    ("Embedding", ["bge-m3", "bge-large-zh-v1.5", "text-embedding-3-large"], 0, 1),
    ("Reranker", ["bge-reranker-base", "bge-reranker-v2-m3", "Cohere rerank-v3"], 0, 1),
    ("前端框架", ["Vue3", "React 18", "SvelteKit"], 0, 1),
    ("UI 库",    ["Ant Design", "shadcn/ui", "MUI"], 0, 1),
    ("打包工具", ["Webpack", "Vite", "Rspack"], 0, 1),
    ("K8s 版本", ["1.26", "1.27", "1.28", "1.29"], 0, 1),
    ("CI 系统",  ["GitLab CI", "GitHub Actions", "Jenkins"], 0, 1),
    ("监控系统", ["Prometheus", "VictoriaMetrics", "Thanos"], 0, 1),
    ("数据仓库", ["ClickHouse", "Doris", "BigQuery"], 0, 1),
    ("调度器",   ["Airflow", "Dagster", "Prefect"], 0, 1),
    ("训练方式", ["LoRA", "QLoRA", "Full FT"], 0, 1),
    ("RPC 框架", ["gRPC", "Thrift", "Dubbo"], 0, 1),
    ("API 网关", ["Kong", "APISIX", "Envoy"], 0, 1),
]

DOMAINS = ["后端", "前端", "运维", "算法", "数据", "测试", "架构", "安全", "平台", "中台"]

DAILY_TALK = [
    "今天调了个 P0 bug，网络抖动导致的重试风暴，排查了大半天",
    "刚开了个会，讨论了下季度的架构演进方向",
    "看了篇论文，关于 KV 缓存压缩的，感觉可以借鉴",
    "同事推荐了本《数据密集型应用系统设计》，正在看",
    "刚部署完新版本，盯着监控看了半小时，暂时没有异常",
    "代码 review 到凌晨，终于过了",
    "新来了个实习生，今天带他熟悉了下系统架构",
    "周末去爬山了，休息得不错，新的一周加油",
    "最近在读《Kubernetes 权威指南》，收获不少",
    "下周要出季度 OKR 汇报，头疼，得准备材料了",
    "刚给开源项目提了个 PR，等 reviewer 反馈",
    "线上做了个灰度，效果不错，准备全量",
    "跟老板讨论了技术选型，他认为应该保守一点",
    "重构了一个老模块，删了几千行代码，感觉很爽",
    "面试了个候选人，感觉水平一般，再看看吧",
]

def gen_persona(pid):
    domain = DOMAINS[pid % len(DOMAINS)]
    persona = f"{domain}工程师-{pid:02d}"

    # 3 个翻转 + 3 个静态
    flipped = random.sample(TOPICS, 3)
    static = random.sample([t for t in TOPICS if t not in flipped], 3)

    sessions = []
    ts = 1735689600  # 2025-01-01
    day = 86400

    # 阶段1：初始声明（6 条）
    for topic, options, idx, _ in static + flipped:
        sessions.append({
            "ts": ts, "role": "user",
            "content": f"我们项目的 {topic} 用 {options[idx]}"
        })
        ts += random.randint(5, 20) * day

    # 阶段2：日常对话（8 条）
    for _ in range(8):
        sessions.append({"ts": ts, "role": "user", "content": random.choice(DAILY_TALK)})
        ts += random.randint(3, 15) * day

    # 阶段3：偏好翻转（3 条）
    flips = []
    for topic, options, idx, new_idx in flipped:
        old_val, new_val = options[idx], options[new_idx]
        reason = random.choice(["性能更好", "社区更活跃", "维护成本更低", "匹配新场景", "团队都熟悉"])
        sessions.append({
            "ts": ts, "role": "user",
            "content": f"我们把 {topic} 从 {old_val} 换成 {new_val} 了，因为{reason}"
        })
        flips.append({"topic": topic, "old": old_val, "new": new_val})
        ts += random.randint(5, 15) * day

    # 阶段4：忘记某个静态 topic
    forget_target = static[0]
    sessions.append({
        "ts": ts, "role": "user",
        "content": f"忘掉之前关于 {forget_target[0]} 的记录，不再参考"
    })
    ts += 3 * day

    # 阶段5：填充至 25 条
    while len(sessions) < 25:
        sessions.append({"ts": ts, "role": "user", "content": random.choice(DAILY_TALK)})
        ts += random.randint(3, 10) * day

    # 生成 10 个问题
    questions = []

    # Q1-Q3：翻转后的值
    for flip in flips:
        questions.append({
            "id": f"q_{pid:02d}_{len(questions):02d}",
            "persona": persona,
            "question": f"我们项目的 {flip['topic']} 现在用什么？",
            "gold": flip["new"],
            "conflict_type": "preference_flip"
        })

    # Q4-Q6：未变化的静态值（跳过被忘记的那个）
    for topic, options, idx, _ in static[1:4]:
        questions.append({
            "id": f"q_{pid:02d}_{len(questions):02d}",
            "persona": persona,
            "question": f"我们的 {topic} 是什么？",
            "gold": options[idx],
            "conflict_type": "none"
        })

    # Q7-Q10：应拒答
    for q_text in [
        f"我们项目的 {forget_target[0]} 用什么？",
        "我叫什么名字？",
        "我们团队有多少人？",
        "我们的办公地点在哪？"
    ]:
        questions.append({
            "id": f"q_{pid:02d}_{len(questions):02d}",
            "persona": persona,
            "question": q_text,
            "gold": "无法确定",
            "conflict_type": "should_reject"
        })

    return {"persona": persona, "domain": domain,
            "sessions": sessions, "questions": questions}

def main():
    personas = [gen_persona(i) for i in range(20)]
    all_q = []
    for p in personas:
        all_q.extend(p["questions"])

    with open("evals/datasets/personas_20.json", "w") as f:
        json.dump(personas, f, ensure_ascii=False, indent=2)

    with open("evals/datasets/questions_200.jsonl", "w") as f:
        for q in all_q:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    total_s = sum(len(p["sessions"]) for p in personas)
    print(f"✅ {len(personas)} 角色，{total_s} 会话，平均 {total_s/len(personas):.1f}/角色")
    print(f"✅ {len(all_q)} 个问题")

    types = {}
    for q in all_q:
        types[q["conflict_type"]] = types.get(q["conflict_type"], 0) + 1
    for t, c in sorted(types.items()):
        print(f"   {t}: {c}")

if __name__ == "__main__":
    main()
