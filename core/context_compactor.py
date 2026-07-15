# core/context_compactor.py
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class CompactionConfig:
    max_bytes: int = 8192  # 8KB default for mobile
    tool_window: int = 2   # keep last N tool calls full
    max_critical_evidence: int = 3
    epsilon: float = 0.1   # 10% headroom


class _ToolInteraction:
    """Helper/Mock interaction representation for compaction tests and tracking."""
    def __init__(
        self,
        step: int = 0,
        tool: str = "",
        ok: bool = True,
        path_hint: Any = "",
        evidence_id: str = "",
        summary: str = "",
        critical: bool = False,
        *,
        exit_code: int = 0,
        output: str = "",
        tool_name: Optional[str] = None,
        success: Optional[bool] = None,
        error: str = ""
    ):
        self.step = step
        self.tool = tool_name or tool
        self.tool_name = self.tool
        self.ok = ok if success is None else success
        self.success = self.ok
        self.path_hint = str(path_hint)
        self.evidence_id = evidence_id
        self.summary = summary
        self.critical = critical
        self.exit_code = exit_code
        self.output = output or error
        self.error = error


class ContextCompactor:
    def __init__(self, config: Optional[CompactionConfig] = None):
        self.config = config or CompactionConfig()

    def should_compact(self, messages: List[dict]) -> bool:
        """Check if context exceeds budget with headroom"""
        total = self._measure(messages)
        limit = int(self.config.max_bytes * (1 - self.config.epsilon))
        return total > limit

    def compact(self, messages: List[dict], state: Any, evidence: Optional[Any] = None) -> List[dict]:
        """Compact context while preserving anchors and critical evidence"""
        if not self.should_compact(messages) and len(messages) <= 4 and not getattr(state, 'active_goal', None) and not getattr(state, 'tool_interactions', None) and not getattr(state, 'past_steps_summary', None) and not evidence:
            return messages

        # 1. Anchors (always preserved)
        anchors = messages[:2]  # system + user task

        # 2. Active goal block
        goal_block = self._build_goal_block(getattr(state, 'active_goal', None)) if getattr(state, 'active_goal', None) else ""

        # 3. Past steps summary (from state or generate)
        interactions = getattr(state, 'tool_interactions', []) or getattr(getattr(state, '_ctx', None), 'tool_interactions', [])
        past_summary = getattr(state, 'past_steps_summary', '') or self._build_tool_summary(interactions)

        # 4. Recent tool window (full)
        tool_window = self._build_tool_window(interactions)

        # 5. Critical evidence snippets
        critical_evidence = self._build_critical_evidence(evidence) if evidence else ""

        # 6. Rebuild compacted messages
        compacted = [anchors[0]] if len(anchors) > 0 else []

        # User task (always anchor[1])
        if len(anchors) > 1:
            compacted.append(anchors[1])

        # Goal block
        if goal_block:
            content = goal_block if "<active_goal" in goal_block else f"<active_goal>\n{goal_block}\n</active_goal>"
            compacted.append({"role": "system", "content": content})

        # Past steps summary
        if past_summary:
            compacted.append({
                "role": "system",
                "content": f"<past_steps_summary untrusted=\"true\">\n{past_summary}\n</past_steps_summary>"
            })

        # Recent tool window
        if tool_window:
            compacted.append({
                "role": "system",
                "content": f"<recent_tools>\n{tool_window}\n</recent_tools>"
            })

        # Critical evidence
        if critical_evidence:
            compacted.append({
                "role": "system",
                "content": f"<critical_evidence>\n{critical_evidence}\n</critical_evidence>"
            })

        return compacted

    def _measure(self, messages: List[dict]) -> int:
        """Estimate total bytes of messages"""
        return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)

    def _build_goal_block(self, goal: Optional[Any]) -> str:
        if not goal:
            return ""
        from engine.state import build_goal_block
        return build_goal_block(goal)

    def _build_tool_summary(self, interactions: List[Any]) -> str:
        """Summarize old tool interactions (outside window)"""
        if not interactions:
            return ""

        lines = []
        old_interactions = interactions[:-self.config.tool_window] if len(interactions) > self.config.tool_window else []

        for i, tool in enumerate(old_interactions):
            ok_val = getattr(tool, 'ok', getattr(tool, 'success', True))
            status = "SUCCESS" if ok_val else "FAIL"
            tool_name = getattr(tool, 'tool', getattr(tool, 'tool_name', 'tool'))
            summary_val = getattr(tool, 'summary', '')
            lines.append(f"Step {i+1}: {tool_name} → {status} - {summary_val}")

        return "\n".join(lines)

    def _build_tool_window(self, interactions: List[Any]) -> str:
        """Keep last N tool interactions full"""
        if not interactions:
            return ""

        lines = []
        for i, tool in enumerate(interactions[-self.config.tool_window:]):
            ok_val = getattr(tool, 'ok', getattr(tool, 'success', True))
            status = "SUCCESS" if ok_val else "FAIL"
            tool_name = getattr(tool, 'tool', getattr(tool, 'tool_name', 'tool'))
            output_snippet = (getattr(tool, 'output', '') or getattr(tool, 'error', '') or getattr(tool, 'summary', ''))[:200]
            lines.append(f"[{tool_name}] {status}\n{output_snippet}")

        return "\n\n".join(lines)

    def _build_critical_evidence(self, evidence: Any) -> str:
        """Include critical evidence snippets"""
        try:
            records = []
            if hasattr(evidence, 'store') and hasattr(evidence.store, '_records'):
                records_attr = evidence.store._records
                records = list(records_attr.values()) if isinstance(records_attr, dict) else list(records_attr)
            elif hasattr(evidence, '_records'):
                records_attr = evidence._records
                records = list(records_attr.values()) if isinstance(records_attr, dict) else list(records_attr)

            critical = [rec for rec in records if getattr(rec, 'critical', False)]
            if not critical:
                return ""

            lines = []
            for rec in critical[-self.config.max_critical_evidence:]:
                rec_id = getattr(rec, 'id', None) or getattr(rec, 'evidence_id', 'E-0')
                snippet = (getattr(rec, 'output', None) or getattr(rec, 'output_snippet', None) or getattr(rec, 'command_or_path', '') or "")[:500]
                lines.append(f"[{rec_id}] {snippet}")

            return "\n\n".join(lines)
        except Exception:
            return ""
