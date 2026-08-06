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

## Am+8 D-7b — State Colors Moved to the Semantic Layer (CLOSED)

**الحالة:** Closed — commit `0e036ae` (Am+8 D-7b). Human ruling (D-7d):
semantic.py owns `success` / `error` / `warning` / `info`.

- Ownership count: 48 -> 44 (-4 violations) measured by
  `scripts/verify_protocol.sh` after the surgery.
- Scope: Class B ONLY — the four shared state colors in `ui/theme.py`
  (`PALETTE["success"]`, `PALETTE["error"]`, `PALETTE["warning"]`,
  `PALETTE["info"]`) became references to `SEMANTIC.*.hex`.
- NOT included (by ruling): dead-owner removal (that was D-7a / D-7c),
  brand/neon values (`neon_green` #00ff9d, `neon_cyan` #00fff7,
  `neon_amber` #ffcc00) stay literal brand spellings,
  and no remaining value migration.
- Guard: `tests/test_theme_state_colors_are_semantic.py` (3 contracts,
  including `test_brand_spellings_are_not_migrated` which pins the
  ruling boundary).
- Visible change, authorised and declared: neon green -> mint
  (#3ecf8e), vivid red -> brick (#e0524a), cyan -> turquoise (#6fd3d6)
  on the repl_termux path only.

## Am+8 D-7b — Debt Discovered While Measuring (OPEN)

Found by measurement during D-7b. None is D-7b's material; each
carries its location so it is never rediscovered from scratch.

- Two names, one meaning: `SEMANTIC.danger` and `SEMANTIC.error` are
  both `#e0524a` (semantic.py:71,72). Readers disagree:
  `badge.py:13` reads `danger`, `personality.py:88` and
  `ui_state.py:59` read `error`. One meaning must have one name.
- Two names, one meaning: `SEMANTIC.info` and `SEMANTIC.accent` are
  both `#6fd3d6` (semantic.py:68,73).
- False docstring: `semantic.py:5-6` claims the values are aligned to
  the legacy palette so D-0 introduces no visual redesign. Untrue
  since D-0 (`#3ecf8e` vs `#00ff9d`), and void after D-7b.
- Brand has no token: `main.py:876,877` and `ui/repl_termux.py:1274`
  spell the prompt colors by hand. The second copy is the dual-REPL
  divergence made physical. Collapsing them requires a brand token,
  which does not exist (measured: NO_BRAND_TOKEN).
- Badge background has no token: `ui/repl_termux.py:733` `#059669`,
  beside `#D97706`, `#7C3AED`, `#EF4444` at :726-734.
- Correction to an earlier claim: `CUSTOM_THEME` was repeatedly said
  to have nine readers. Measured: one live reader
  (`ui/repl_termux.py:51`), plus its definition and the `nabd_theme`
  alias in `ui/theme.py`. `main.py` does not read it at all, which is
  why D-7b changed only one surface.

## Declared Debt — core/test_runner_wrapper.py:21 hard-codes "python3"

**الحالة:** OPEN — declared in D-7b sheet LAW 0b. Owned by another commit.

`run_tests_as_evidence` spawns `["python3", "-m", "unittest", ...]` with a
literal interpreter name. On a PATH whose first `python3` lacks `rich`
(e.g. a container where `/usr/bin/python3` shadows the Termux interpreter),
the subprocess fails with `ModuleNotFoundError` and the test
`test_run_tests_as_evidence` fails. Proven environmental: the node fails
alone in 3.03s and the root cause is the hard-coded name, not test logic.

Do not fix here; fix with the interpreter-pinning commit.

## Am+8 D-7d - Twin Preset Names (OPEN, human ruling 2B, 2026-08-06 11:15)

`ui/design/typography/presets.py:35` defines DANGER and `:38` defines ERROR.
Both now resolve to SEMANTIC.error: one meaning carrying two preset names -
the same defect the 10:08 token ruling removed one layer below. It was NOT
deleted here because its readers were never measured; the registry keys at
`:49` and `:52` are the only ones known. Measure the readers, then delete
DANGER in a commit of its own.
