#!/usr/bin/env python3
# /ai/dxos_pilot/backend/heartbeat.py
# 【R7】SIGTERM 优雅退出

import os
import sys
import time
import json
import signal
import subprocess
import logging
import requests
from datetime import datetime

HEALTH_URL = "http://127.0.0.1:9981/health"
CHECK_INTERVAL = 30
MAX_FAILURES = 3
LOG_FILE = "/ai/dxos_pilot/logs/heartbeat.log"

class BackendHeartbeat:
    def __init__(self):
        self.running = True
        self.failure_count = 0
        self.setup_logging()
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        self.log.info(f"收到信号 {signum}，正在优雅退出...")
        self.running = False
    
    def setup_logging(self):
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s"
        )
        self.log = logging.getLogger("heartbeat")
    
    def check_backend(self):
        try:
            resp = requests.get(HEALTH_URL, timeout=5)
            return resp.status_code == 200 and resp.json().get("status") == "healthy"
        except Exception:
            return False
    
    def restart_backend(self):
        self.log.warning("后端连续失败，执行重启...")
        try:
            result = subprocess.run(
                ["systemctl", "restart", "dxos-backend"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                self.log.info("systemctl restart 成功")
            else:
                self.log.error(f"systemctl 重启失败: {result.stderr}")
        except Exception as e:
            self.log.error(f"重启失败: {e}")
    
    def run(self):
        self.log.info("心跳保活守护进程启动")
        self.log.info(f"检查间隔: {CHECK_INTERVAL}s, 最大失败: {MAX_FAILURES}")
        
        while self.running:
            time.sleep(CHECK_INTERVAL)
            
            if not self.check_backend():
                self.failure_count += 1
                self.log.warning(f"后端检查失败 ({self.failure_count}/{MAX_FAILURES})")
                if self.failure_count >= MAX_FAILURES:
                    self.restart_backend()
                    self.failure_count = 0
            else:
                self.failure_count = 0
        
        self.log.info("心跳守护进程正常退出")
        sys.exit(0)

if __name__ == "__main__":
    heartbeat = BackendHeartbeat()
    heartbeat.run()
