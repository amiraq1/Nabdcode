#!/usr/bin/env bash
# pre_commit_check.sh — Pre-commit gate runner for NABD OS
# Exit code: 0 = pass, non-zero = blocked (commit prevented)
# set -euo pipefail: any failure in any gate or pipeline aborts immediately

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo '.')"
cd "$ROOT"

# ── Pre-flight: verify Python and pytest are available ─────────────────
if ! command -v python3 &>/dev/null; then
    echo "FATAL: python3 not found. Cannot run pre-commit checks."
    exit 1
fi
if ! python3 -m pytest --version &>/dev/null; then
    echo "FATAL: pytest not found or broken. Run: pip install pytest"
    exit 1
fi

# ── Gate runner: any failure = blocked ─────────────────────────────────
run_gate() {
    local num="$1" name="$2" fix="${@: -1}"
    # Gather test files (all args between $3 and second-to-last)
    local targets=()
    for arg in "${@:3:$#-3}"; do
        targets+=("$arg")
    done
    echo "[${num}/6] ${name} ..."
    if ! python3 -m pytest "${targets[@]}" -q; then
        echo "BLOCKED: ${name} failed."
        echo "  ${fix}"
        echo "  To bypass intentionally (reviewed only):"
        echo "  git commit --no-verify -m \"... [POLICY_OVERRIDE] ...\""
        echo "  Then verify via pre-push or full suite."
        exit 1
    fi
    echo "  OK"
}

echo ":: NABD OS pre-commit ::"
echo ""

run_gate 1 "Red team validation"           "tests/test_red_team_phase22.py" \
    "Inspect the specific failure before committing."

run_gate 2 "Schema snapshot contract"      "tests/test_schema_contract_snapshot.py" \
    "Run: python3 tests/_gen_snapshot.py ; git add tests/snapshots/"

run_gate 3 "Event name snapshot contract"  "tests/test_event_contract_policy.py" \
    "Run: python3 tests/_gen_snapshot.py ; git add tests/snapshots/"

run_gate 4 "Forbidden-changes policy"      "tests/test_forbidden_changes_policy.py" \
    "See SCHEMA_POLICY.md. If intentional: add [POLICY_OVERRIDE] to commit msg + update SCHEMA_POLICY.md"

run_gate 5 "Exact-action contract"         "tests/test_exact_action_contract.py" "tests/test_exact_action_schema_filtering.py" \
    "See core/_exact_action_contract.py"

run_gate 6 "Claim gate + Arabic verification" \
    "tests/test_semantic_verifier_phase23.py" "tests/test_arabic_claim_verification_phase25.py" \
    "Inspect the specific failure before committing."

echo ""
echo ":: All 6 checks passed. Commit allowed. ::"
