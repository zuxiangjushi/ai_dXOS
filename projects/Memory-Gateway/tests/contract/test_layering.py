import ast, pathlib
BANNED = {"qdrant_client", "meilisearch", "httpx", "litellm", "mem0", "crawl4ai",
          "redis", "asyncpg", "fastapi", "sqlalchemy"}
FOR_ROOTS = {"contracts"}
SYNC_IO = ("QdrantClient(", "requests.", "meilisearch.Client(", "time.sleep(")

def _imports(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names: yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module

def test_no_third_party_in_contracts():
    bad = [f"{p}:{n}" for p in pathlib.Path("contracts").rglob("*.py")
           for n in _imports(p) if n.split(".")[0] in BANNED]
    assert not bad, f"契约层禁止第三方依赖：{bad}"

def test_no_sync_io_helpers():
    bad = []
    for p in list(pathlib.Path("contracts").rglob("*.py")):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if any(s in line for s in SYNC_IO) and not line.strip().startswith("#"):
                bad.append(f"{p}:{i}:{line.strip()[:50]}")
    assert not bad, f"禁止同步 IO/阻塞调用：{bad}"
