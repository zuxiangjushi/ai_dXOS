"""
sing-box 适配器
- 启动/停止/重启 sing-box 服务
- 读写配置文件（/ai/Memory-Gateway/network_controller/singbox_config.json）
- 切换节点（99 个 vless 可选）
"""
import json
import os
import shutil
import socket
import subprocess
import time
from typing import Dict, List, Optional


class SingboxAdapter:
    SERVICE = "sing-box"
    CONFIG_PATH = "/ai/Memory-Gateway/network_controller/singbox_config.json"
    PROFILE_SRC = "/home/paxen/.local/share/hiddify/configs/1a94798d-aba1-40c7-b599-83726775b100.json"
    PROXY_PORT = 12334
    PROXY_HOST = "0.0.0.0"

    # ─── 服务控制 ───
    def start(self) -> Dict:
        try:
            r = subprocess.run(["systemctl", "start", self.SERVICE],
                               capture_output=True, text=True, timeout=15)
            time.sleep(2)
            return {"ok": r.returncode == 0 and self.port_listening(),
                    "port_listening": self.port_listening()}
        except Exception as e:
            return {"ok": False, "msg": f"{type(e).__name__}: {e}"}

    def stop(self) -> Dict:
        try:
            r = subprocess.run(["systemctl", "stop", self.SERVICE],
                               capture_output=True, text=True, timeout=15)
            time.sleep(1)
            return {"ok": r.returncode == 0,
                    "port_listening": self.port_listening()}
        except Exception as e:
            return {"ok": False, "msg": f"{type(e).__name__}: {e}"}

    def restart(self) -> Dict:
        try:
            r = subprocess.run(["systemctl", "restart", self.SERVICE],
                               capture_output=True, text=True, timeout=20)
            time.sleep(3)
            return {"ok": r.returncode == 0 and self.port_listening(),
                    "port_listening": self.port_listening()}
        except Exception as e:
            return {"ok": False, "msg": f"{type(e).__name__}: {e}"}

    def status(self) -> Dict:
        try:
            r = subprocess.run(["systemctl", "is-active", self.SERVICE],
                               capture_output=True, text=True, timeout=5)
            return {"active": r.stdout.strip() == "active",
                    "raw": r.stdout.strip()}
        except Exception as e:
            return {"active": False, "raw": str(e)}

    # ─── 端口探测 ───
    def port_listening(self) -> bool:
        for host in ["127.0.0.1", "0.0.0.0"]:
            try:
                s = socket.create_connection((host, self.PROXY_PORT), timeout=2)
                s.close()
                return True
            except Exception:
                continue
        return False

    # ─── 节点管理 ───
    CUSTOM_NODES_PATH = "/ai/Memory-Gateway/network_controller/custom_nodes.json"

    # ─── 自定义节点 ───
    def _load_custom(self) -> List[Dict]:
        """加载自定义节点"""
        import json as _json
        if not os.path.exists(self.CUSTOM_NODES_PATH):
            return []
        try:
            with open(self.CUSTOM_NODES_PATH) as f:
                data = _json.load(f)
            return data.get("nodes", [])
        except Exception as e:
            print(f"   [adapter] 加载自定义节点失败: {e}", flush=True)
            return []

    def _save_custom(self, nodes: List[Dict]) -> bool:
        """保存自定义节点"""
        import json as _json
        try:
            with open(self.CUSTOM_NODES_PATH, "w") as f:
                _json.dump({"nodes": nodes}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"   [adapter] 保存自定义节点失败: {e}", flush=True)
            return False

    def parse_vless(self, url: str) -> Optional[Dict]:
        """解析 vless:// 链接"""
        if not url or not url.startswith("vless://"):
            return None

        try:
            from urllib.parse import urlparse, parse_qs, unquote

            # vless://uuid@server:port?params#tag
            rest = url[8:]

            # 提取 tag
            tag = ""
            if "#" in rest:
                rest, tag = rest.split("#", 1)
                tag = unquote(tag).strip()

            # 提取 query
            params = {}
            if "?" in rest:
                rest, query_str = rest.split("?", 1)
                raw_params = parse_qs(query_str)
                params = {k: v[0] if v else "" for k, v in raw_params.items()}

            # userinfo@host:port
            if "@" not in rest:
                return None
            userinfo, hostport = rest.rsplit("@", 1)

            if ":" not in hostport:
                return None
            host, port = hostport.rsplit(":", 1)

            if not tag:
                tag = f"custom-{host[:15]}"

            node = {
                "uuid": userinfo,
                "server": host,
                "server_port": int(port),
                "tag": tag,
                "params": params,
            }
            return node

        except Exception as e:
            print(f"   [adapter] 解析 vless 失败: {type(e).__name__}: {e}", flush=True)
            return None

    def vless_to_singbox(self, node: Dict) -> Dict:
        """把解析后的 vless 节点转成 sing-box outbound"""
        params = node.get("params", {})

        ob = {
            "type": "vless",
            "tag": node["tag"],
            "server": node["server"],
            "server_port": node["server_port"],
            "uuid": node["uuid"],
            "packet_encoding": "xudp",
        }

        # flow
        if params.get("flow"):
            ob["flow"] = params["flow"]

        # TLS
        security = params.get("security", "")
        if security == "tls":
            tls = {"enabled": True}

            sni = params.get("sni", "") or params.get("host", "")
            if sni:
                tls["server_name"] = sni

            if params.get("allowInsecure") == "1" or params.get("insecure") == "1":
                tls["insecure"] = True

            fp = params.get("fp", "")
            if fp:
                tls["utls"] = {"enabled": True, "fingerprint": fp}

            alpn = params.get("alpn", "")
            if alpn:
                tls["alpn"] = alpn.split(",")

            ob["tls"] = tls

        # 传输层
        net_type = params.get("type", "tcp")
        if net_type == "ws":
            transport = {
                "type": "ws",
                "path": params.get("path", "/"),
            }
            host = params.get("host", "")
            if host:
                transport["headers"] = {"Host": host}
            ob["transport"] = transport
        elif net_type == "grpc":
            ob["transport"] = {
                "type": "grpc",
                "service_name": params.get("serviceName", ""),
            }
        elif net_type == "http":
            ob["transport"] = {
                "type": "http",
                "host": [params.get("host", "")] if params.get("host") else [],
                "path": params.get("path", "/"),
            }

        return ob

    def add_custom_node(self, url: str) -> Dict:
        """添加自定义节点"""
        node = self.parse_vless(url)
        if not node:
            return {"ok": False, "msg": "无效的 vless 链接"}

        custom = self._load_custom()

        # 检查 tag 冲突
        for n in custom:
            if n.get("tag") == node["tag"]:
                return {"ok": False, "msg": f"tag 已存在：{node['tag']}"}

        custom.append(node)
        if self._save_custom(custom):
            return {"ok": True, "tag": node["tag"], "server": node["server"]}
        return {"ok": False, "msg": "保存失败"}

    def remove_custom_node(self, tag: str) -> Dict:
        """删除自定义节点"""
        custom = self._load_custom()
        before = len(custom)
        custom = [n for n in custom if n.get("tag") != tag]
        if len(custom) == before:
            return {"ok": False, "msg": f"未找到：{tag}"}
        if self._save_custom(custom):
            return {"ok": True, "removed": tag}
        return {"ok": False, "msg": "保存失败"}

    def list_nodes(self) -> List[Dict]:
        # Hiddify 节点
        hiddify_nodes = []
        if os.path.exists(self.PROFILE_SRC):
            try:
                with open(self.PROFILE_SRC) as f:
                    d = json.load(f)
                hiddify_nodes = [
                    {"tag": ob.get("tag"),
                     "server": ob.get("server"),
                     "port": ob.get("server_port"),
                     "source": "hiddify"}
                    for ob in d.get("outbounds", [])
                    if ob.get("type") == "vless" and ob.get("server")
                ]
            except Exception:
                pass

        # 自定义节点
        custom_nodes = []
        for n in self._load_custom():
            custom_nodes.append({
                "tag": n.get("tag"),
                "server": n.get("server"),
                "port": n.get("server_port"),
                "source": "custom",
            })

        # 合并：自定义优先显示（用户添加的应该显眼）
        return custom_nodes + hiddify_nodes

    def current_node(self) -> Optional[str]:
        if not os.path.exists(self.CONFIG_PATH):
            return None
        try:
            with open(self.CONFIG_PATH) as f:
                d = json.load(f)
            for ob in d.get("outbounds", []):
                if ob.get("type") == "vless":
                    return ob.get("tag")
        except Exception:
            return None
        return None

    def switch_node(self, tag: str) -> Dict:
        if not os.path.exists(self.PROFILE_SRC):
            return {"ok": False, "msg": f"profile not found: {self.PROFILE_SRC}"}
        try:
            with open(self.PROFILE_SRC) as f:
                profile = json.load(f)
        except Exception as e:
            return {"ok": False, "msg": f"read profile: {e}"}

        # ★ v10.4: 优先在自定义节点中查找
        custom = self._load_custom()
        target = None
        for n in custom:
            if n.get("tag") == tag:
                target = self.vless_to_singbox(n)
                print(f"   [adapter] 从自定义节点加载：{tag}", flush=True)
                break

        # 回退到 Hiddify profile
        if not target:
            for ob in profile.get("outbounds", []):
                if ob.get("tag") == tag and ob.get("type") == "vless":
                    target = ob
                    print(f"   [adapter] 从 Hiddify profile 加载：{tag}", flush=True)
                    break

        if not target:
            return {"ok": False, "msg": f"node not found: {tag}"}

        keep = ("type", "tag", "server", "server_port", "uuid",
                "flow", "tls", "transport", "packet_encoding")
        clean_target = {k: v for k, v in target.items() if k in keep}

        existing = {}
        if os.path.exists(self.CONFIG_PATH):
            try:
                with open(self.CONFIG_PATH) as f:
                    existing = json.load(f)
            except Exception:
                pass

        if existing.get("inbounds"):
            inbounds = existing["inbounds"]
            for ib in inbounds:
                if "listen" in ib:
                    ib["listen"] = self.PROXY_HOST
        else:
            inbounds = [{"type": "mixed", "tag": "mixed-in",
                         "listen": self.PROXY_HOST,
                         "listen_port": self.PROXY_PORT}]

        new_cfg = {
            "log": {"level": "warn"},
            "inbounds": inbounds,
            "outbounds": [clean_target, {"type": "direct", "tag": "direct"}],
        }

        if os.path.exists(self.CONFIG_PATH):
            shutil.copy2(self.CONFIG_PATH,
                         f"{self.CONFIG_PATH}.bak_{int(time.time())}")

        with open(self.CONFIG_PATH, "w") as f:
            json.dump(new_cfg, f, ensure_ascii=False, indent=2)

        return self.restart()

    def read_raw_config(self) -> Optional[Dict]:
        if not os.path.exists(self.CONFIG_PATH):
            return None
        try:
            with open(self.CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            return None

    def logs(self, lines: int = 30) -> str:
        try:
            r = subprocess.run(
                ["journalctl", "-u", self.SERVICE, "-n", str(lines),
                 "--no-pager"],
                capture_output=True, text=True, timeout=5)
            return r.stdout
        except Exception as e:
            return f"log error: {e}"


_adapter = None


def get_singbox() -> SingboxAdapter:
    global _adapter
    if _adapter is None:
        _adapter = SingboxAdapter()
    return _adapter
