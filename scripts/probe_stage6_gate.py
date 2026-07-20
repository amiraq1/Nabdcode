"""Live proof of Stage-6 verifier gate wiring via the REAL ExecutionLoop path
(that main.py uses). Drives _verify_claim_or_self_correct with seeded evidence.

Monkeypatches llm_router.run_verifier_check + verifier_router.generate_response
ONLY to capture: (A1) the exact prompt (context isolation), (A5) per-run call
count. No production code modified.
"""
import sys
import logging

logging.disable(logging.CRITICAL)

import llm_router

_CAPTURED = []
_CALLS = [0]
_SEEN_TEMP = []
_orig_check = llm_router.run_verifier_check


def _patched_gen(messages, logger=None, **kwargs):
    _SEEN_TEMP.append(kwargs.get("temperature"))
    # Deterministic verdict set by MODE env (pass=A3, fail=A2).
    return _MODE_RESULT


llm_router.verifier_router.generate_response = _patched_gen


def _patched_check(goal_prompt, final_answer, evidence_summary, logger=None, **kwargs):
    _CALLS[0] += 1
    _CAPTURED.append({
        "goal": goal_prompt,
        "final_answer": final_answer,
        "evidence_summary": evidence_summary,
        "leak": ("chat history" in (goal_prompt + final_answer + evidence_summary).lower()
                 and "conversation" in (goal_prompt + final_answer + evidence_summary).lower()),
    })
    return _orig_check(goal_prompt, final_answer, evidence_summary, logger=logger, **kwargs)


llm_router.run_verifier_check = _patched_check

from engine.loop import ExecutionLoop, _LoopCtx, _LoopSignal
from engine.state import RuntimeState
from core.evidence import EvidenceRecord
from core.kernel.events import bus

_MODE = sys.argv[1] if len(sys.argv) > 1 else "A3"
_MODE_RESULT = ('{"verdict": "pass", "reasons": ["grounded"], "missing": []}'
                if _MODE == "A3"
                else '{"verdict": "fail", "reasons": ["not grounded"], "missing": ["src"]}')

_CRIT = []
bus.subscribe("verifier_critique", lambda p: _CRIT.append(p))

state = RuntimeState(session_id=f"probe-{_MODE}-stage6")
loop = ExecutionLoop(state=state)
loop._ctx = _LoopCtx(user_prompt="Trace the API key path from .env through core/_env.py to OpenRouterClient in llm_router.py")

for p in ["core/_env.py", "llm_router.py", "core/config.py"]:
    loop.evidence_log.record(
        tool="file_system", command_or_path=p, action="read",
        success=True, output_snippet=f"content of {p}: API_KEY handling here",
    )

if _MODE == "A3":
    loop._last_response = ("The key is loaded from OPENROUTER_API_KEY in core/_env.py "
                           "and passed to OpenRouterClient in llm_router.py.")
else:
    loop._last_response = ("The smart-agent system uses a PostgreSQL database with "
                           "connection string postgresql://nabd:secret@localhost:5432/store "
                           "and auto-creates a 'users' table on boot.")

sig = loop._verify_claim_or_self_correct()
c = _CAPTURED[0]
print(f"[MODE] {_MODE}")
print(f"[SIGNAL] {sig.name}")
print(f"[REAL_READS] {loop._real_reads()}")
print(f"[VERIFIER_CALLS] {_CALLS[0]}")
print(f"[VERIFIER_CRITIQUE_EVENTS] {len(_CRIT)}")
print(f"[TEMPERATURE_FORCED] {_SEEN_TEMP}")
print(f"[CONTEXT_LEAK_SUSPECTED] {c['leak']}")
print("--- evidence_summary ---")
print(c["evidence_summary"])
