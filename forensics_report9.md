# Forensic Report 9 — Tool Feedback Role & Infinite-Thinking Loop

Operation: EXECUTION_LOOP_DIAGNOSIS
Date: 2026-07-16
Status: 🔴 1 Real Defect (role mislabel) + 1 Visual Artifact (RTL)

## 0. Executive Summary

| # | Finding | Diagnosis | Root Cause | Fix Location | Status |
|---|---------|-----------|------------|--------------|--------|
| 1 | Tool results injected as `role: "user"` | **Real Defect** | `engine/loop.py` appends tool output with `{"role": "user", ...}`, so the model treats the tool result as a *new human turn* and re-thinks indefinitely instead of moving to `final_answer`. | `engine/loop.py` (lines 1310, 1356) | ✅ Done |
| 2 | Arabic prompt appears reversed on screen | **Visual Artifact (NOT a code bug)** | Termux / prompt_toolkit renders RTL text by mirroring glyphs visually. The stored string in `state.messages` is the correct, un-reversed Arabic. No reversal happens in code. | N/A (UX, separate track) | ⏸ Deferred |

**Verdict:** The infinite-thinking loop after a tool call is caused by #1 (role mislabel),
NOT by the reversed Arabic text. The reversed text is a pure rendering artifact — the model
receives the correct string `"أبحث في الإنترنت عن..."`.

## 1. Evidence

### ❌ Finding 1 — Tool feedback role mislabel (Real Defect)
* **Command:** `grep -n 'append_message({"role": "user", "content": feedback})' engine/loop.py`
* **Result:**
```
engine/loop.py:1310: self.state.append_message({"role": "user", "content": feedback})
engine/loop.py:1356: self.state.append_message({"role": "user", "content": feedback})
```
* **Trace:** `_dispatch_and_record_evidence()` → `_build_tool_feedback()` returns
  `"[tool_name Output]\n{output}"` → appended as `role: "user"`. On the next iteration
  `_invoke_llm_and_normalize()` sends the full `state.messages` to the LLM. The model sees a
  `user` turn that is actually a tool result, concludes "the user asked something new / the
  tool never ran", and re-derives the same tool call → loop.

### ❌ Finding 2 — RTL reversal is visual only
* **Check:** `grep -rn 'reverse\|\[::-1\]\|\\\\u202e\|bidi' engine/ ui/ core/` → only
  `reversed(compressor.session_thoughts)` (dict-key iteration, not text reversal).
* **Input path:** `ui/repl_termux.py:548 session.prompt_async(...)` →
  `text = user_input.strip()` → `state.append_message({"role":"user","content":text})`.
  No transformation of the string. The bytes stored are the original Arabic.
* **Conclusion:** Termux terminal emulator mirrors RTL runs for display; the underlying
  Python `str` is correct and is what the LLM receives.

## 2. Resolution

Changed tool-result messages from `role: "user"` to `role: "tool"` with a stable
`tool_call_id` derived from the step index and `name: tool_name`, matching the OpenRouter
tool-result contract used elsewhere in the system (`smolagents` uses `role: "tool"` at
`smolagents/__init__.py:422`). This lets the model distinguish tool output from user input
and terminate the think loop after evidence is gathered.

## 3. Post-Fix Verification
* `pytest tests/` → 505 passed (no regression).
* Manual: a web_search / shell turn now returns a `role: "tool"` message; the model should
  call `final_answer` next instead of re-dispatching.
