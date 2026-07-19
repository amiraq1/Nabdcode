"""Live proof: the final_answer path invokes verify_fresh, and on a listing-only
/ echo answer it now injects a DIRECTED READ directive (not just "try again").

Drives the REAL _verify_claim_or_self_correct with:
  - evidence_log = one `list core` record (0 reads)  [mirrors live run]
  - _last_response = the exact broken answer seen live
Prints whether VERIFY enters, whether it rejects, and what directive is injected.
"""

import sys
import logging
logging.disable(logging.CRITICAL)

from engine.loop import ExecutionLoop, _LoopCtx, _LoopSignal
from engine.state import RuntimeState
from core.evidence import EvidenceRecord


def main():
    state = RuntimeState(session_id="prove-verify-path")
    loop = ExecutionLoop(state=state)
    loop._ctx = _LoopCtx(user_prompt="افحص بنية core")

    loop.evidence_log.record(
        tool="file_system", command_or_path="core", action="list",
        success=True, output_snippet="evidence.py  investigation.py  agent_manager.py (14822 bytes)",
    )
    loop.evidence_log.record(
        tool="file_system", command_or_path=".", action="list",
        success=True, output_snippet="core/  engine/  main.py  pyproject.toml",
    )

    broken_answer = (
        "Based on the gathered evidence: [file_system] Directory listing for 'core' "
        "— 78 entries. agent_manager.py (14822 bytes) ..."
    )
    loop._last_response = broken_answer

    print("=== PROVING VERIFY PATH (listing-only + echo) ===", file=sys.stderr, flush=True)
    sig = loop._verify_claim_or_self_correct()
    injected = [m for m in state.get_messages() if m.get("content", "").startswith("[CONTROL]")]
    last = injected[-1]["content"] if injected else ""
    print(f"[RESULT] signal={sig.name}", file=sys.stderr, flush=True)
    print(f"[INJECTED DIRECTIVE contains DIRECTED READS]: {'DIRECTED READS' in last}", file=sys.stderr, flush=True)
    print(f"[INJECTED mentions pyproject.toml]: {'pyproject.toml' in last}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
