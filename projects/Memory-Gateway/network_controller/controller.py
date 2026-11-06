"""Network Controller - FastAPI 服务（端口 9983）"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from singbox_adapter import get_singbox
from health_probe import probe_all

app = FastAPI(title="Network Controller", version="6.5")


# ★ v10.3: 允许跨域（9984 静态页 fetch 9983 API）
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 局域网环境
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/network/status")
async def network_status(force: bool = False):
    sb = get_singbox()
    service = sb.status()
    port = sb.port_listening()
    node = sb.current_node()
    probe = await probe_all(force=force)
    return {
        "singbox": {
            "service_active": service["active"],
            "port_listening": port,
            "current_node": node,
            "port": sb.PROXY_PORT,
        },
        "direct": probe["direct"],
        "proxy": probe["proxy"],
        "ts": probe["ts"],
    }


@app.post("/network/proxy/start")
async def proxy_start():
    return get_singbox().start()


@app.post("/network/proxy/stop")
async def proxy_stop():
    return get_singbox().stop()


@app.post("/network/proxy/restart")
async def proxy_restart():
    return get_singbox().restart()


@app.get("/network/nodes")
async def list_nodes():
    sb = get_singbox()
    nodes = sb.list_nodes()
    return {"current": sb.current_node(), "count": len(nodes), "nodes": nodes}


@app.post("/network/proxy/switch")
async def switch_node(payload: dict):
    tag = (payload or {}).get("tag")
    if not tag:
        raise HTTPException(400, "missing tag")
    return get_singbox().switch_node(tag)


@app.get("/network/proxy/logs", response_class=PlainTextResponse)
async def proxy_logs(lines: int = 30):
    return get_singbox().logs(lines)


@app.get("/network/probe")
async def probe_now():
    return await probe_all(force=True)


@app.get("/network/config")
async def raw_config():
    sb = get_singbox()
    return {"path": sb.CONFIG_PATH, "config": sb.read_raw_config()}


# ★ v10.4: 节点管理 API
@app.post("/network/nodes/add")
async def add_node(payload: dict):
    """添加自定义 vless 节点"""
    url = (payload or {}).get("url", "").strip()
    if not url:
        raise HTTPException(400, "missing url")
    if not url.startswith("vless://"):
        raise HTTPException(400, "仅支持 vless:// 链接")
    return get_singbox().add_custom_node(url)


@app.delete("/network/nodes/custom/{tag}")
async def remove_node(tag: str):
    """删除自定义节点"""
    from urllib.parse import unquote
    return get_singbox().remove_custom_node(unquote(tag))


@app.get("/network/nodes/custom")
async def list_custom_nodes():
    """列出所有自定义节点"""
    sb = get_singbox()
    return {
        "nodes": sb._load_custom(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9983, log_level="info")
