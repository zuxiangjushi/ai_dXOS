#!/usr/bin/env python3
import requests, os
OPENWEBUI_URL = "http://localhost:3000"
BACKEND_URL = "http://localhost:9981/api/dashboard"
TOKEN = os.popen('curl -s -X POST http://localhost:3000/api/v1/auths/signin -H "Content-Type: application/json" -d \'{"email":"REPLACE_FROM_ENV_OPENWEBUI_USER","password":"REPLACE_FROM_ENV_OPENWEBUI_PASS"}\' | jq -r ".token"').read().strip()
MODELS = ["qwen3_32b","qwen38_27b_f8","gemma_4","yy38_27b","yy35b_q6","38FN_Q4","deepseek_70b","qwen3_30b"]

def get_status():
    try:
        r=requests.get(BACKEND_URL, timeout=5)
        if r.status_code != 200: return {}
        return {m['api_name']:(m['status']=='running') for m in r.json().get('models', [])}
    except Exception as e:
        print(f"后端状态获取失败: {e}")
        return {}

def sync():
    if not TOKEN or TOKEN == "null":
        print("❌ Token 无效，请确保已登录管理员")
        return
    status = get_status()
    if not status:
        print("❌ 无法获取后端状态，请检查后端是否运行")
        return
    for mid in MODELS:
        enabled = status.get(mid, False)
        for ep in [f"{OPENWEBUI_URL}/api/models", f"{OPENWEBUI_URL}/api/v1/models"]:
            resp = requests.patch(f"{ep}/{mid}",
                                  json={"enabled": enabled},
                                  headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
            if resp.status_code in [200, 204]:
                print(f"{mid} -> {'启用' if enabled else '禁用'} ({resp.status_code})")
                break
            else:
                print(f"{mid} -> 尝试 {ep} 失败 ({resp.status_code})")
if __name__ == "__main__":
    sync()
