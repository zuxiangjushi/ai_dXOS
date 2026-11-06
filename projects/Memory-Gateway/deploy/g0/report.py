import asyncio, importlib, sys, time, traceback
import yaml

ORDER = [("p1_embedding", "P1"), ("p2_rerank", "P2"), ("p3_retrieval", "P3"),
         ("p4_pg_owner", "P4"), ("p5_extraction", "P5"), ("p6_lease", "P6"),
         ("p7_rule_tier", "P7"), ("p8_eventloop", "P8")]
NAMES = dict(ORDER)
NAMES.update({"p1_embedding": "嵌入通路", "p2_rerank": "CPU重排", "p3_retrieval": "一万条检索",
              "p4_pg_owner": "PG归属+盘位", "p5_extraction": "LLM抽取", "p6_lease": "GPU租约",
              "p7_rule_tier": "T0规则层", "p8_eventloop": "事件循环"})

def fallback(pid, mod, exc):
    r = ProbeLike()
    r.pid, r.name, r.passed = pid, NAMES.get(mod, mod), None
    r.metrics = {"异常": "{}: {}".format(type(exc).__name__, exc)[:150]}
    r.reason = "探针自身异常（不计达标）"
    r.hint = traceback.format_exc(limit=2).strip().splitlines()[-1][:140]
    return r

class ProbeLike:
    hint = ""

async def main():
    cfg = yaml.safe_load(open("deploy/g0/config/g0.yaml"))
    print("=" * 78)
    print(" Memory-Gateway G0 预研体检")
    print("=" * 78)
    results = []
    for mod, pid in ORDER:
        t0 = time.perf_counter()
        try:
            m = importlib.import_module("deploy.g0.probes." + mod)
            res = await m.run(cfg)
        except Exception as e:
            res = fallback(pid, mod, e)
        results.append(res)
        mark = {True: "PASS", False: "FAIL", None: "SKIP"}[res.passed]
        print("{}  {:4}  {:<12} {}".format(res.pid, mark, res.name, res.reason))
        for k, v in res.metrics.items():
            print("        . {} = {}".format(k, v))
        if res.passed is False and getattr(res, "hint", ""):
            print("        -> {}".format(res.hint))
        print()
    n = sum(1 for x in results if x.passed)
    need = cfg["pass_min_items"]
    print("=" * 78)
    verdict = "G0 通过，进入 G2 实现" if n >= need else "G0 未通过，先修阻塞项"
    print("结论：{} / {} 达标（门禁 >={}）-> {}".format(n, len(results), need, verdict))
    print("=" * 78)
    return 0 if n >= need else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
