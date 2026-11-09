#!/usr/bin/env python3
# /ai/dxos_pilot/backend/main.py
# Dxos_Pilot Backend v6.0

import json
import os
import subprocess
import re
import asyncio
import time
import psutil
from datetime import datetime, timedelta
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(title="Dxos_Pilot API", version="6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ★ 挂载 WSL2 远程路由
try:
    from wsl_routes import router as wsl_router
    app.include_router(wsl_router)
    print("[BOOT] WSL routes mounted")
except Exception as e:
    print(f"[BOOT] WSL routes failed: {e}")

# ===== 路径常量 =====
BASE_PATH = "/ai/ai_dxos"
PILOT_PATH = "/ai/dxos_pilot"
CONF_PATH = f"{BASE_PATH}/configs"
MODELS_CONF = f"{CONF_PATH}/models.conf"
STATE_FILE = f"{CONF_PATH}/state/state.json"
SCRIPTS_PATH = f"{BASE_PATH}/scripts"
SCHEDULER = f"{SCRIPTS_PATH}/scheduler/scheduler.sh"
ACTIONS_PATH = f"{SCRIPTS_PATH}/actions"
LOG_PATH = f"{BASE_PATH}/logs"
KEYS_CONF = f"{BASE_PATH}/secrets/keys.conf"
FRONTEND_DIR = "/ai/dxos_pilot/frontend"

# ====== 工具函数 ======
def run_cmd(cmd):
    env = os.environ.copy()
    env["MODELS_CONF_FILE"] = MODELS_CONF
    env["STATE_FILE"] = STATE_FILE
    env["SCHEDULER_LOCK"] = "/var/run/dxos_scheduler.lock"
    env["MODEL_LOCK_DIR"] = "/run/dxos/model_locks"
    env["BASE_DIR"] = "/ai/ai_dxos"
    proc = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        cwd="/ai/ai_dxos", env=env
    )
    return proc.returncode, proc.stdout, proc.stderr

def parse_models_conf():
    models = []
    if not os.path.exists(MODELS_CONF):
        return models
    with open(MODELS_CONF, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split('|')
            if len(parts) >= 7:
                models.append({
                    "api_name": parts[0],
                    "container_name": parts[1],
                    "physical_model": parts[2],
                    "port": int(parts[3]) if parts[3].isdigit() else 0,
                    "gpu_ids": parts[4],
                    "engine": parts[5],
                    "pool": parts[6],
                })
    return models

def get_model_status(model_id):
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        return data.get('running_models', {}).get(model_id, {}).get('status', 'stopped')
    except:
        return 'stopped'

def get_model_progress(model_id):
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        return data.get('running_models', {}).get(model_id, {}).get('progress', 0)
    except:
        return 0

def get_gpu_stats():
    stats = []
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            stats.append({
                "index": i,
                "used_gb": round(mem.used / 1024**3, 1),
                "total_gb": round(mem.total / 1024**3, 1),
                "utilization": util.gpu,
                "temperature": temp,
                "processes": []
            })
    except Exception as e:
        print(f"GPU stats error: {e}")
    return stats

def get_system_stats():
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        swap = psutil.swap_memory()
        return {
            "cpu_usage": psutil.cpu_percent(interval=0.5),
            "memory_used_gb": round(mem.used / 1024**3, 1),
            "memory_total_gb": round(mem.total / 1024**3, 1),
            "memory_percent": mem.percent,
            "swap_used_gb": round(swap.used / 1024**3, 1),
            "swap_total_gb": round(swap.total / 1024**3, 1),
            "swap_percent": swap.percent,
            "disk_used_gb": round(disk.used / 1024**3, 1),
            "disk_total_gb": round(disk.total / 1024**3, 1),
            "disk_percent": disk.percent
        }
    except:
        return {k: 0 for k in [
            'cpu_usage', 'memory_used_gb', 'memory_total_gb', 'memory_percent',
            'swap_used_gb', 'swap_total_gb', 'swap_percent',
            'disk_used_gb', 'disk_total_gb', 'disk_percent']}

# ====== API 端点 ======
@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/dashboard")
async def get_dashboard():
    models = parse_models_conf()
    for m in models:
        status = get_model_status(m['api_name'])
        progress = get_model_progress(m['api_name'])
        m["status"] = status
        m["progress"] = progress
        m["container_status"] = "running" if status in ['running', 'starting', 'loading'] else "stopped"
    gpus = get_gpu_stats()
    system = get_system_stats()
    return JSONResponse({"models": models, "gpus": gpus, "system": system})

@app.get("/api/models")
async def get_models():
    models = parse_models_conf()
    for m in models:
        m["status"] = get_model_status(m["api_name"])
        m["progress"] = get_model_progress(m["api_name"])
    def extract_num(name):
        match = re.search(r'^M(\d+)', name or "")
        return int(match.group(1)) if match else 999
    models.sort(key=lambda m: extract_num(m.get("container_name", "")))
    return JSONResponse(models)

@app.post("/api/models/{model_id}/start")
async def start_model(model_id: str):
    code, out, err = run_cmd(f"{SCHEDULER} switch {model_id}")
    return JSONResponse({"success": code == 0, "message": out + err})


@app.post("/api/stop/all")
async def stop_all():
    code, out, err = run_cmd(f"{SCHEDULER} stop_all")
    return JSONResponse({"success": code == 0, "message": out + err})

@app.post("/api/gpu/clean")
async def clean_gpu(target: str = "all"):
    code, out, err = run_cmd(f"{ACTIONS_PATH}/clean_gpu.sh {target}")
    return JSONResponse({"success": code == 0, "output": out + err})

@app.get("/api/gateway/status")
async def gateway_status():
    code, out, err = run_cmd("docker ps --filter 'name=litellm-gateway' --format '{{.Status}}'")
    if code == 0 and out.strip():
        return JSONResponse({"status": "running", "detail": out.strip()})
    elif code == 0:
        return JSONResponse({"status": "stopped", "detail": "Container not found"})
    else:
        return JSONResponse({"status": "error", "detail": err})

@app.post("/api/gateway/restart")
async def restart_gateway():
    result = subprocess.run(
        ["docker", "restart", "litellm-gateway"],
        capture_output=True, text=True, timeout=30
    )
    return JSONResponse({
        "success": result.returncode == 0,
        "message": result.stdout + result.stderr
    })

@app.get("/api/keys")
async def get_keys():
    keys = []
    if os.path.exists(KEYS_CONF):
        with open(KEYS_CONF, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if '=' in line:
                    key_name, key_value = line.split('=', 1)
                    key_name = key_name.replace('KEY_', '').strip('"\'')
                    key_value = key_value.strip('"\'')
                    masked = key_value[:4] + '****' + key_value[-4:] if len(key_value) > 8 else key_value
                    endpoint = f"http://192.168.10.132:9980/{key_name}"
                    keys.append({
                        "model_name": key_name,
                        "api_key": masked,
                        "endpoint": endpoint,
                        "expires_at": "2027-08-30",
                        "is_active": True
                    })
    return JSONResponse(keys)

# ====== 前端静态文件托管 ======
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
@app.get("/dashboard")
async def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))



@app.post("/api/models/{model_id}/stop")
async def stop_model(model_id: str, background_tasks: BackgroundTasks):
    def run_stop():
        run_cmd(f"{SCHEDULER} stop {model_id}")
    background_tasks.add_task(run_stop)
    return JSONResponse({"success": True, "message": f"已发送后台停止指令: {model_id}"})



import time
import httpx
import re

# 全局缓存，用于计算真实 TPS
_LAST_TPS_STATE = {}

@app.get("/api/usage/stats")
async def get_usage_stats():
    import json, os
    from pathlib import Path
    
    state_file = "/ai/ai_dxos/configs/state/state.json"
    models_data = []
    
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            async with httpx.AsyncClient(timeout=2.0) as client:
                for name, info in state.get("running_models", {}).items():
                    if info.get("status") == "running":
                        port = info.get("port")
                        engine = info.get("engine")
                        
                        tps = 0.0
                        total_tokens = 0
                        
                        # 如果是 SGLang 引擎，去抓取真实 metrics
                        if engine == "sglang" and port:
                            try:
                                resp = await client.get(f"http://127.0.0.1:{port}/metrics")
                                if resp.status_code == 200:
                                    # 解析 SGLang 的真实解码 token 数
                                    match = re.search(r'sglang:realtime_tokens_total\{[^}]*mode="decode"[^}]*\}\s+([\d\.]+)', resp.text)
                                    if match:
                                        total_tokens = float(match.group(1))
                                        
                                        # 计算 TPS (当前时间 - 上次时间)
                                        now = time.time()
                                        last_state = _LAST_TPS_STATE.get(name, {"tokens": total_tokens, "time": now})
                                        
                                        time_diff = now - last_state["time"]
                                        token_diff = total_tokens - last_state["tokens"]
                                        
                                        # 避免除零和负数（比如模型重启导致 token 归零）
                                        if time_diff > 0.5 and token_diff >= 0:
                                            tps = round(token_diff / time_diff, 1)
                                        
                                        # 更新缓存
                                        _LAST_TPS_STATE[name] = {"tokens": total_tokens, "time": now}
                            except Exception:
                                pass

                        models_data.append({
                            "api_name": name,
                            "container": info.get("container", "-"),
                            "gpu_ids": info.get("gpu", "-"),
                            "pool": info.get("pool", "-"),
                            "throughput_tps": str(tps),
                            "total_tokens": int(total_tokens),
                            # Agent 数据目前暂留空，等待下一步接入真实流量
                            "agents": [] 
                        })
        except Exception as e:
            print("Error fetching stats:", e)

    # 检查网关状态
    gateway_status = "Down"
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            r = await client.get("http://127.0.0.1:9980/health")
            if r.status_code == 200:
                gateway_status = "Up"
    except Exception:
        pass
            
    return JSONResponse({
        "gateway_status": gateway_status,
        "models": models_data
    })


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9981)
