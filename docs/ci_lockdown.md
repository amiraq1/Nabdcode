# CI Lockdown — Enforced Gates & Bypass Protocol

## What Is Enforced

Every commit runs 6 gates locally (via pre-commit hook). Order is fail-fast
(cheapest that catches the most violations first):

| # | Gate | Tests | ~Time | What It Catches |
|---|------|-------|-------|-----------------|
| 1 | Red team | `test_red_team_phase22.py` | 2s | Security bypass, spoofing, path escape |
| 2 | Schema snapshot | `test_schema_contract_snapshot.py` | <1s | Field added/removed/changed without snapshot update |
| 3 | Event snapshot | `test_event_contract_policy.py` | <1s | New/removed `bus.emit()` without snapshot update |
| 4 | Forbidden changes | `test_forbidden_changes_policy.py` | <1s | Protected module deleted/renamed, heavy import, renamed core API |
| 5 | Exact-action contract | `test_exact_action_contract.py` + `test_exact_action_schema_filtering.py` | <1s | Contract deviation |
| 6 | Claim gate + Arabic | `test_semantic_verifier_phase23.py` + `test_arabic_claim_verification_phase25.py` | <1s | Gate regression |

**Total pre-commit:** ~5s. **Full suite:** `python3 -m pytest -q` (1383 tests, ~120s).

## How to Install the Hook

```bash
# Option A: Symlink (recommended, hook stays updated with repo)
ln -sf ../../scripts/pre_commit_check.sh .git/hooks/pre-commit

# Option B: Manual copy
cp scripts/pre_commit_check.sh .git/hooks/pre-commit
```

## How to Bypass

### Schema / Event Snapshot Update (Intentional Change)
1. Make the schema/event change in source code.
2. Run `python3 tests/_gen_snapshot.py` to regenerate snapshots.
3. `git add tests/snapshots/` — commit the updated `.json` alongside the source change.
4. Commit normally — the snapshot tests now pass against the new state.

### Forbidden-Changes Bypass (Reviewed Exception Only)
1. Add `[POLICY_OVERRIDE]` as the first token in the commit message.
2. Update `SCHEMA_POLICY.md` with the new exception and justification.
3. Run full suite before merging.

### Security Gate Bypass (Red Team, Claim Gate, Exact-Action)
**Forbidden.** Never bypass a security gate. Fix the regression.

## `--no-verify` Policy

Allowed only for intentional snapshot updates and `[POLICY_OVERRIDE]` exceptions.
Subject to pre-push safety net: full suite must pass before merge.

## Fail-Closed

If any gate cannot run (python3 missing, pytest broken, import/syntax error),
the script exits 1 with a clear message. No silent pass.

## No-Hook Detection

Run `[ -x .git/hooks/pre-commit ]` to check if the hook is installed.
The pre-push / manual full suite is the safety net if the hook is absent.
