import os
import subprocess
import json
import time
import socket
import signal
from typing import Dict, Any, Optional


class LightpandaAdapter:
    """
    مهايئ مخصص للربط بين Nabd OS ومتصفح Lightpanda الصامت عبر بروتوكول MCP.
    يتميز بالتحكم الصارم في دورة حياة العملية وحماية سياق الذاكرة.
    """
    def __init__(self, workspace_dir: str, timeout: int = 30, max_stdout_kb: int = 10):
        self.workspace_dir = workspace_dir
        self.timeout = timeout
        self.max_stdout_cap = max_stdout_kb * 1024
        self.process: Optional[subprocess.Popen] = None
        self.port: Optional[int] = None
        self.mcp_endpoint: Optional[str] = None

    def _get_free_port(self) -> int:
        """البحث الديناميكي عن منفذ متاح لمنع التصادم"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def start(self) -> bool:
        """تشغيل عملية Lightpanda بأمان مع تخصيص منفذ ديناميكي"""
        if self.process and self.process.poll() is None:
            return True

        try:
            self.port = self._get_free_port()
            self.mcp_endpoint = f"http://127.0.0.1:{self.port}"
            
            env = os.environ.copy()
            env["LIGHTPANDA_DISABLE_TELEMETRY"] = "1"
            
            # تشغيل Lightpanda وعزلها في Session Group مخصصة لمنع تسريب العمليات
            self.process = default_guard.spawn_infra(
                ["lightpanda", "mcp", "--port", str(self.port)],
                env=env,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None
            )
            
            time.sleep(0.5)  # إعطاء الخادم فرصة طفيفة للإقلاع
            return True
        except FileNotFoundError:
            return False

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """توجيه الطلب إلى خادم MCP عبر urllib الخفيفة"""
        if not self.start():
            return {"status": "FAILED", "error": "Lightpanda binary not found or failed to start."}

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            },
            "id": int(time.time())
        }

        try:
            import urllib.request
            req = urllib.request.Request(
                f"{self.mcp_endpoint}/call",
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                return self._sanitize_and_compact_result(result)
        except Exception as e:
            return {"status": "FAILED", "error": f"Communication error: {str(e)}"}

    def _sanitize_and_compact_result(self, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        """ضغط حجم المخرجات لحماية نوافذ سياق الـ LLM"""
        text_content = raw_result.get("result", {}).get("content", "")
        if isinstance(text_content, str) and len(text_content.encode('utf-8')) > self.max_stdout_cap:
            truncated_text = text_content[:self.max_stdout_cap // 2] + "\n\n... [TRUNCATED BY NABD ADAPTER TO PROTECT CONTEXT] ..."
            raw_result["result"]["content"] = truncated_text
            raw_result["truncated"] = True
        return raw_result

    def stop(self):
        """إيقاف منظم وفولاذي يقتل كافة العمليات الشقيقة والتابعة"""
        if self.process:
            try:
                # قتل مجموعة العمليات بالكامل لمنع تكوين Zombie Processes
                pgid = os.getpgid(self.process.pid)
                os.killpg(pgid, signal.SIGTERM)
                self.process.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            finally:
                self.process = None
                self.port = None
                self.mcp_endpoint = None
