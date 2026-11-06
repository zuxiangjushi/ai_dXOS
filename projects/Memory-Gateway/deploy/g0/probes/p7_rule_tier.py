import sys, os
sys.path.insert(0, os.getcwd())
from contracts.t0_rules import classify_tier
from .base import ProbeResult

CASES = [("记住，我们只用Qdrant", True), ("以后都返回503", True),
         ("我不再喜欢pgvector", True), ("已经改成SGLang了", True),
         ("忘掉之前那条", True), ("删除关于Milvus的记忆", True),
         ("从现在起温度设0.2", True), ("我叫老张", True),
         ("我们项目用整洁架构", True), ("别再用Milvus", True),
         ("今天天气不错", False), ("帮我解释一下HNSW", False),
         ("这段代码怎么写", False), ("你好", False),
         ("随便聊聊", False), ("max_context是什么", False),
         ("帮我总结上文", False), ("这个报错什么意思", False),
         ("重构一下这个函数", False), ("继续", False)]

async def run(cfg):
    r = ProbeResult("P7", "T0规则层")
    hit = sum(1 for s, want in CASES if classify_tier(s).is_a == want)
    cov = hit / len(CASES)
    lim = cfg["budgets"]["rule_tier_coverage"]
    r.metrics = {"正确": hit, "总数": len(CASES), "覆盖率": round(cov, 3)}
    r.passed = cov >= lim
    r.reason = "规则判定正确率 {:.0%} (门禁 {:.0%})".format(cov, lim)
    if not r.passed:
        r.hint = "补正则：显式记忆动词/否定翻转/删除意图/结构化声明"
    return r
