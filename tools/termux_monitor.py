"""Termux system monitor tool for NABD OS.

A BaseTool that reports memory and disk usage on a Termux/Android host by
running the standard ``free -m`` and ``df -h`` utilities through the hardened
``execute_shell`` tool (security-validated, no shell=True). Outputs are parsed
into structured memory/disk records and returned as a ToolResult.

NOTE: Defined as a BaseTool (not BaseSkill) per the NABD OS tool contract:
every engine-facing tool must subclass BaseTool and return a ToolResult.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool
from tools.shell import ShellTool
from tools.models import ToolResult


class TermuxMonitorTool(BaseTool):
    """Report Termux system memory (free -m) and disk (df -h) usage."""

    name: str = "termux_monitor"
    description: str = (
        "Monitor Termux/Android system health: returns parsed memory usage "
        "(free -m) and disk usage (df -h). Use for 'how much memory/disk is "
        "free', resource checks, or before heavy operations."
    )

    def _run_shell(self, command: str) -> str:
        """Execute a command via the hardened execute_shell tool; return stdout."""
        result = ShellTool().execute(command=command)
        if getattr(result, "success", False):
            return getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        raise RuntimeError(f"{command} failed: {stderr}")

    def _parse_free(self, raw: str) -> dict[str, Any]:
        """Parse `free -m` output into a structured memory report."""
        lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
        report: dict[str, Any] = {"raw": raw.strip()}
        # Header: Mem: total used free shared buff/cache available
        for ln in lines:
            if ln.lower().startswith("mem:"):
                parts = ln.split()
                # parts: ['Mem:', 'total', 'used', 'free', 'shared', 'buff/cache', 'available']
                vals = parts[1:]
                keys = ["total_mb", "used_mb", "free_mb", "shared_mb", "buff_cache_mb", "available_mb"]
                report["memory"] = {
                    keys[i]: int(vals[i]) for i in range(min(len(keys), len(vals)))
                }
            elif ln.lower().startswith("swap:"):
                parts = ln.split()
                vals = parts[1:]
                keys = ["total_mb", "used_mb", "free_mb"]
                report["swap"] = {
                    keys[i]: int(vals[i]) for i in range(min(len(keys), len(vals)))
                }
        return report

    def _parse_df(self, raw: str) -> dict[str, Any]:
        """Parse `df -h` output into a list of filesystem usage records."""
        lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
        records: list[dict[str, str]] = []
        # Header: Filesystem Size Used Avail Use% Mounted on
        for ln in lines[1:]:
            cols = ln.split()
            if len(cols) >= 6:
                records.append({
                    "filesystem": cols[0],
                    "size": cols[1],
                    "used": cols[2],
                    "avail": cols[3],
                    "use_percent": cols[4],
                    "mounted_on": cols[5],
                })
        return {"filesystems": records, "raw": raw.strip()}

    def execute(self, **kwargs) -> ToolResult:
        try:
            mem_raw = self._run_shell("free -m")
            disk_raw = self._run_shell("df -h")
            memory = self._parse_free(mem_raw)
            disk = self._parse_df(disk_raw)

            summary_lines = ["[Termux Monitor]"]
            mem = memory.get("memory", {})
            if mem:
                summary_lines.append(
                    f"Memory: {mem.get('used_mb', '?')}/{mem.get('total_mb', '?')} MB used "
                    f"({mem.get('available_mb', '?')} MB available)"
                )
            for fs in disk.get("filesystems", []):
                summary_lines.append(
                    f"Disk {fs['mounted_on']}: {fs['used']}/{fs['size']} "
                    f"({fs['use_percent']} used, {fs['avail']} avail)"
                )
            stdout = "\n".join(summary_lines)
            return ToolResult(
                success=True,
                stdout=stdout,
                returncode=0,
                status="success",
                metadata={"memory": memory, "disk": disk},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                stderr=f"termux_monitor failed: {exc}",
                returncode=-1,
                status="error",
            )
