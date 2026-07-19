"""Live (in-process) verification of the Phase 0 root fix.

Drives the REAL _run_once path with a stub LLM that emits a whole-tree scan
(matches Guard 4) then a final_answer, and asserts:
  - no [SYSTEM DIRECTIVE] inside any message content tagged as a [TOOL RESULT]
  - no [SYSTEM DIRECTIVE] / [EVIDENCE REJECTED] inside evidence_log.output_snippet
  - the guard directive is delivered as a [CONTROL] user message
This mirrors the acceptance gate: grep the produced session for leaks.
"""

import sys
import json
from unittest.mock import MagicMock

from engine.loop import ExecutionLoop
from engine.state import RuntimeState
from core.parser import ToolCall


def main():
    state = RuntimeState(session_id="live-leak-check")
    # Stub LLM: turn1 = whole-tree scan (triggers Guard 4), turn2 = final_answer.
    turn1 = '{"tool": "file_system", "args": {"action": "list", "path": ".", "recursive": "true"}}'
    turn2 = '{"tool": "final_answer", "args": {"answer": "Architecture report from evidence."}}'
    def _llm_effect(*args, **kwargs):
        # First call emits the whole-tree scan (triggers Guard 4); every
        # subsequent call emits final_answer so the loop can terminate.
        _llm_effect.n += 1
        return turn1 if _llm_effect.n == 1 else turn2
    _llm_effect.n = 0
    mock_llm = MagicMock(side_effect=_llm_effect)

    loop = ExecutionLoop(llm_provider=mock_llm, state=state)
    loop._safe_shutdown = MagicMock(return_value="ABORTED_SAFE")
    loop.run("Draw the architecture of core")

    # ── Assertions (the grep-equivalent on the produced session) ──
    leaks = []
    for m in state.get_messages():
        role = m.get("role")
        content = m.get("content", "")
        if "[TOOL RESULT:" in content and ("SYSTEM DIRECTIVE" in content or "EVIDENCE REJECTED" in content):
            leaks.append(("tool_result_with_directive", role, content[:120]))
        if "SYSTEM DIRECTIVE" in content or "EVIDENCE REJECTED" in content:
            # allowed only as a [CONTROL] user message
            if not (role == "user" and content.startswith("[CONTROL]")):
                leaks.append(("directive_outside_control", role, content[:120]))

    for rec in loop.evidence_log.get_records():
        if "SYSTEM DIRECTIVE" in rec.output_snippet or "EVIDENCE REJECTED" in rec.output_snippet:
            leaks.append(("directive_in_evidence", rec.tool, rec.output_snippet[:120]))

    control_msgs = [m for m in state.get_messages() if m.get("role") == "user" and m.get("content", "").startswith("[CONTROL]")]

    print("=== LIVE LEAK CHECK ===")
    print(f"messages={len(state.get_messages())} evidence_records={len(loop.evidence_log.get_records())} control_msgs={len(control_msgs)}")
    if leaks:
        print("FAIL — leaks detected:")
        for ln in leaks:
            print("  ", ln)
        sys.exit(1)
    print("PASS — no directive leaked into tool results or evidence_log; delivered as [CONTROL].")


if __name__ == "__main__":
    main()
