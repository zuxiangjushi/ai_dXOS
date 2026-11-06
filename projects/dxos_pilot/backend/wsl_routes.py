#!/usr/bin/env python3
"""WSL2 远程模型接口 —— 独立模块，避免修改 main.py"""
import subprocess
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

WIN11_IP = "192.168.10.208"
WIN11_USER = "ypb"
WIN11_PASSWORD = "738104"


@router.get("/api/wsl/gpu")
async def get_wsl_gpu_stats():
    """获取 WSL2 主机（Win11）的 GPU 状态"""
    try:
        cmd = [
            "sshpass", "-p", WIN11_PASSWORD,
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            f"{WIN11_USER}@{WIN11_IP}",
            "nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return JSONResponse({"error": "SSH failed", "detail": result.stderr[:200]}, status_code=500)
        gpus = []
        for idx, line in enumerate(result.stdout.strip().split("\n")):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                gpus.append({
                    "index": idx,
                    "name": parts[0],
                    "used_mb": int(parts[1]),
                    "total_mb": int(parts[2]),
                    "utilization": int(parts[3]),
                    "temperature": int(parts[4])
                })
        return JSONResponse({"gpus": gpus, "host": WIN11_IP})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/wsl/restart-gateway")
async def restart_litellm_gateway():
    """重启 LiteLLM 网关"""
    try:
        result = subprocess.run(["docker", "restart", "litellm-gateway"],
                                capture_output=True, text=True, timeout=30)
        return JSONResponse({"success": result.returncode == 0, "output": result.stdout})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@router.post("/api/wsl/clean-gpu")
async def clean_wsl_gpu():
    """清理 WSL2 容器（停止 vLLM 并释放显存）"""
    try:
        cmd = [
            "sshpass", "-p", WIN11_PASSWORD,
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{WIN11_USER}@{WIN11_IP}",
            "docker stop vllm-qwen-coder"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return JSONResponse({"success": result.returncode == 0, "output": result.stdout})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})
