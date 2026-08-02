# R5_BASELINE.md — NABD OS Release Preparation (R4.9) Baseline Snapshot

Date: 2026-08-02
Purpose: document-only baseline for R5 System Qualification. No code changes in
this phase. This file is the freeze reference for Phase-0.

---

## 1. Repository Identity

| Item | Value |
|---|---|
| Branch | `ui/chapter2-visual-fixes` |
| HEAD SHA | `1b90da22e53acc1e365c37f3dde902c6583cd3c9` |
| HEAD tree SHA | `a70d0b4b36e477fb956d026c714e71ba7ee3bac0` |
| Upstream | `origin/ui/chapter2-visual-fixes` |
| V-07b | Committed — `1b90da2` (3 files: `main.py` 5+/9-, `scan_display.py` new, `test_ui_scan_display.py` new) |
| Worktree | CLEAN (verified `git status --porcelain` = empty) |

## 2. Qualification Status at Freeze Point

| Phase | Status |
|---|---|
| R4 (V-02/V-03/V-04/V-05/V-07a) | CLOSED — VERIFIED_COMPONENT_LEVEL |
| V-07b | CLOSED — committed `1b90da2`, live on-device evidence captured (real scan path, width 40) |
| R4.9 Release Preparation | IN PROGRESS |
| PAT rotation | **PENDING — Release Authority action (blocking R5 Gate 2)** |
| R5 Phase-0 baseline | READY to record once PAT is confirmed |

## 3. Baseline Evidence Inventory

- Full suite (pre-V-07b-commit state, 2026-08-02): `1581 passed, 1 skipped, 1 warning, 16 subtests passed in 180.61s` — 0 failed.
- V-07b focused tests: 6/6 passed, stable across consecutive runs (incl. golden snapshot).
- Live on-device runtime evidence (V-07b): real `_process_slash_command('فحص')` path with
  `SECURE_REPO_SCANNER()._deep_scan()` on the actual workspace, rendered at width 40 —
  output showed marked truncation (`…/NabdBootloader`), overflow collapse
  (`… 91 more lines (full data preserved)`), zero mid-word tearing. `SCAN_RETURN: True`.
- Patch identity (pre-commit): `/tmp/opencode/v07b_full.patch` SHA-256 `65a26106c28c22b1dfc039599be43ee3cad73be508d5ec0e3c17a69fb2c74548`.
- flake8 (E9/F63/F7/F82): clean on all three files.
- New dependencies: none.

## 4. Known Issues (pre-existing, independent of R4.x)

- `core/` prompts for an openrouter key + git credential on import; full suite must
  run with `< /dev/null`. Environmental blocker, documented Known Issue.
- Historical test-count anomaly (24→0) — separate Known Issue, not attributed to
  R4 phases.
- UI does not display true `loop_phase`/budget/max-steps (UI-LIMIT V-04, documented).

## 5. R5 Freeze Checklist (remaining)

- [ ] **PAT rotation** — Release Authority: delete exposed `ghp_01gs2…` at
      GitHub → Settings → Developer settings → Personal access tokens; create a new
      token with least privilege; update local usage; NEVER commit it.
- [ ] Record this file's SHA at freeze time (this file itself is a candidate for the
      freeze pin alongside HEAD/tree SHAs).
- [ ] Re-run full suite on the frozen HEAD and record output in the R5 record.
- [ ] Begin R5 Phase 1 (Runtime E2E strategy — replay-first recommendation pending
      evidence; see R5_FOUNDATION_REPORT.md).

## 6. Qualification Order (unchanged, no skipping)

```
Phase-0 Repository Validation → (R4.9 gates: worktree/PAT/V-07b evidence)
Freeze Baseline → Runtime E2E → Security → Recovery → Performance →
Multi-Agent → Release Candidate
```
