# Known Limitations

## TOCTOU in Path Validation (Low Severity)
**الحالة:** Known limitation, non-goal for current phase.

`_guard_path_jail` verifies the path at dispatch time, while `_validate_path` in
`file_system.py` also validates at execution time. A TOCTOU window exists
between these two checks. `os.path.realpath()` alone does not close TOCTOU
(a symlink can be swapped after the check but before the `open()` call).
A proper fix requires `openat()` + `O_NOFOLLOW` + fd-based validation.

The Termux single-user environment mitigates practical risk.

## Turn ID on EvidenceRecord

`EvidenceRecord` has no `turn_id` field; temporal tracking uses `timestamp` +
`action` (which carries `step_count`). A proper `session_id`/`turn_id` field
would require a schema change to `EvidenceRecord.__init__`. This is acceptable
because step_count + timestamp provide enough temporal resolution for consent
auditing.

## Directory fsync Best-Effort in SessionManager.save()

`SessionManager.save()` performs a best-effort `os.fsync()` on the parent
directory after `os.replace()`. If this directory fsync fails (e.g. on F2FS
filesystems common on Android/Termux, or when `O_RDONLY` on a directory fd
is unsupported), the save still succeeds and returns `True`. The file contents
are fsync'd before rename, so the data itself is durable; only the directory
entry ordering may not be crash-atomic in edge cases.

## TUI Layer (ui/) — Frozen Without Dedicated Tests

The TUI layer (`ui/`) is frozen as-is alongside the engineering closure.
It has no dedicated automated test suite. This is an accepted trade-off:
the TUI is a rendering layer that wraps the engine, and most logic lives
in engine/ and core/ which are fully tested.

## Exact-Action Tool Output Checked by Claim Gate (Fail-Closed)

In exact-action mode, the investigation gates (verify_fresh, read-count) are
bypassed — the tool output is emitted directly as the final answer after a
single shell execution. However, the **claim gate** (test/commit spoofing) is
still active: if the tool output accidentally matches a claim pattern
(e.g. "all 99999 tests passed" as literal output), it is rejected and prevents
emission.

This is **safe by design**: the claim gate errs on the side of rejecting
ambiguous output. The user can retry with a command whose output does not
look like a claim. This is a deliberate trade-off: investigation gates are
bypassed for efficiency, but the claim gate remains as the last line of
defense against narrative spoofing.

## UI-LIMIT: Loop-Phase, Budget, and Max Step (V-04)

The `AgentStatusBar` currently subscribes to kinetic activity (`tool_started`, `llm_request_started`, etc.) and accurately displays the agent's current step (`Step N`).
However, the UI does NOT display the true underlying `loop_phase` (e.g. PLAN/COLLECT/SYNTHESIZE/FINALIZE), the `budget` ratio, or the `/max` steps limit. 
This is because the `loop.py` engine currently does not emit these state pieces to the event bus. To avoid visual fabrication (inventing state that the engine didn't broadcast), the UI explicitly omits these indicators. This limitation is deferred to a future engineering phase (`ENGINE-OBS-01`), which will securely add emits for these items in the engine layer, at which point the UI can safely render them.

## UI-CHANGE: Visual Line Wrapping Changes Default Collapse Behavior (V-07a)

V-07a introduced visual line estimation in `ToolResultWidget._count_visible_lines` (folding long lines into multiple visual lines based on console width). This means very long single-line outputs (e.g. minified JSON, base64, long stack traces) now collapse by default.

**Contract change:** Truncation testing for long outputs must explicitly set `w._collapsed = False` to force the expanded rendering path, as the default behavior for long visual lines is now collapsed.
