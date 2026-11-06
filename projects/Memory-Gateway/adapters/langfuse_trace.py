"""TraceAdapter：本地 JSONL + 可选 Langfuse 远程上报"""
import os
import time
import json


class TraceAdapter:
    def __init__(self, enabled=True, remote=False):
        self.enabled = enabled
        self.remote = remote or os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
        self._spans = []
        self._lf = None

        if self.remote:
            try:
                from langfuse import Langfuse
                self._lf = Langfuse(
                    public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
                    secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
                    host=os.environ.get("LANGFUSE_HOST", "http://192.168.10.132:3001"),
                )
                print("✅ Langfuse 已连接", flush=True)
            except Exception as e:
                print(f"⚠️ Langfuse 连接失败，降级为本地: {e}", flush=True)
                self.remote = False

    def start_span(self, name, attrs=None):
        span = {"name": name, "start": time.time(), "attrs": attrs or {}, "events": []}
        if self.remote and self._lf:
            try:
                span["_lf"] = self._lf.trace(name=name, metadata=attrs or {})
            except Exception:
                pass
        self._spans.append(span)
        return span

    def end_span(self, span, attrs=None):
        if span:
            span["end"] = time.time()
            span["duration_ms"] = (span["end"] - span["start"]) * 1000
            if attrs:
                span["attrs"].update(attrs)
            if self.remote and span.get("_lf"):
                try:
                    span["_lf"].update(output=attrs or {},
                                       metadata={"duration_ms": span["duration_ms"]})
                except Exception:
                    pass

    def log_event(self, span, event, data=None):
        if span:
            span["events"].append({"event": event, "data": data, "ts": time.time()})

    def export(self):
        if not self.enabled:
            return
        os.makedirs("docs", exist_ok=True)
        safe = []
        for span in self._spans:
            s = {k: v for k, v in span.items() if not k.startswith("_")}
            safe.append(s)
        with open("docs/traces.jsonl", "a") as f:
            for s in safe:
                f.write(json.dumps(s, default=str) + "\n")
        self._spans.clear()


def langfuse_enabled() -> bool:
    return os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
