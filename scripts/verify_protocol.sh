#!/usr/bin/env bash
# verify_protocol.sh — report protocol debt; use --enforce to block.
#
# Am+8 T-1c — report-mode only. Rewritten under NUCLEAR EXECUTION PROTOCOL v2.
#
# ARMING CONDITION: --enforce is wired to block (exit 1) ONLY while a violation
#   is reported, and it is NOT connected to pre_commit_check.sh in this stage.
#   Arming (wiring into the pre-commit flow) is conditional on count == 0.
# NON-DROPPABLE TODAY (documented, not removed):
#   - ui/design/theme/semantic.py is the legitimate semantic color owner; the
#     color scan excludes it BY NAME (never by pattern).
#   - _subscribe_with_fallback (ui/repl_termux.py:1590) is live production
#     code; its removal belongs to a separate stage.
#
# Exit codes:
#   0  report mode (always); --self-test success; --enforce with 0 violations
#   1  --enforce with violations; --self-test on the first failed step
#   2  usage error, or not inside a git work tree

set -u -o pipefail

usage() {
    cat <<'EOF'
Usage: verify_protocol.sh [--enforce | --self-test | --help]

  (no args)   report protocol debt (always exits 0)
  --enforce   exit 1 while a violation is reported (UNARMED: not wired to
              pre_commit_check.sh in this stage)
  --self-test plant a real violation, verify report/enforce behavior, clean up
  --help      print this text
EOF
}

# --- argument parsing: explicit and exhaustive (contract 3) ---------------
[ "$#" -le 1 ] || { usage >&2; exit 2; }
mode="report"
case "${1:-}" in
    "")          mode="report" ;;
    --enforce)   mode="enforce" ;;
    --self-test) mode="self-test" ;;
    --help)      usage; exit 0 ;;
    *)           usage >&2; exit 2 ;;
esac

# --- ROOT: fail loudly, never scan cwd silently (contract 2) --------------
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "verify_protocol: git rev-parse failed — not inside a git work tree" >&2
    exit 2
}
cd "$ROOT" || exit 2

REPORT_COUNT=0
emit() { printf '%s\n' "$1"; REPORT_COUNT=$((REPORT_COUNT + 1)); }

# --- color scan (contract 5): all *.py except tests/ and semantic.py ------
# Patterns anchored on 38|48 keep key sequences (27;2;13…) out of the scan.
color_scan() {
    grep -rEn \
        '#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3}\b|\b(38|48);2;[0-9]+;[0-9]+;[0-9]+|\b(38|48);5;[0-9]+' \
        --include='*.py' \
        --exclude-dir=tests \
        --exclude-dir=.git \
        --exclude-dir=__pycache__ \
        . 2>/dev/null \
        | grep -v '^\./ui/design/theme/semantic\.py:' \
        | sed -E 's#^\./([^:]+):([0-9]+):(.*)$#- \1:\2: raw color: \3#' \
        | cut -c1-160
}

# --- fallback scan (contract 7): literal identifier only ------------------
fallback_scan() {
    grep -RIn '_subscribe_with_fallback' --include='*.py' \
        --exclude-dir=tests --exclude-dir=.git --exclude-dir=__pycache__ \
        . 2>/dev/null \
        | sed -E 's#^\./([^:]+):([0-9]+):(.*)$#- \1:\2: live _subscribe_with_fallback#'
}

# --- snapshot scan (contract 8): existence + cmp -s -----------------------
# Two byte-identical captures mean the machine did not measure (§12).
snapshot_scan() {
    local a="docs/before_t1_badges.ansi" b="docs/after_t1_badges.ansi"
    for cap in "$a" "$b"; do
        [ -f "$cap" ] || printf '%s\n' "- $cap:1: missing visual capture"
    done
    if [ -f "$a" ] && [ -f "$b" ] && cmp -s "$a" "$b"; then
        printf '%s\n' "- $a:1: byte-identical to $b — machine did not measure"
    fi
}

# --- subscriber scan (contract 6): path:line per subscriber, not wc -l ----
subscriber_scan() {
    grep -RIn 'show_final_answer' --include='*.py' ui/ 2>/dev/null \
        | grep -E 'subscribe|on_final_answer' \
        | awk -F: 'NR > 1 { print "- " $1 ":" $2 ": extra show_final_answer subscriber" }'
}

# --- core report: prints violations, sets REPORT_COUNT --------------------
run_checks() {
    REPORT_COUNT=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        emit "$line"
    done < <({ color_scan; fallback_scan; snapshot_scan; subscriber_scan; })
}

# --- report mode (contract 10): always exits 0 ----------------------------
report_mode() {
    local tmp
    tmp="$(mktemp "${TMPDIR:-/tmp}/vp_report.XXXXXX")"
    run_checks > "$tmp"
    cat "$tmp"
    if [ "$REPORT_COUNT" -eq 0 ]; then
        echo "verify_protocol: clean"
    else
        echo "verify_protocol: $REPORT_COUNT violation(s)"
    fi
    rm -f "$tmp"
    exit 0
}

# --- enforce mode: exit 1 while a violation is reported -------------------
enforce_mode() {
    local tmp
    tmp="$(mktemp "${TMPDIR:-/tmp}/vp_enforce.XXXXXX")"
    run_checks > "$tmp"
    if [ "$REPORT_COUNT" -eq 0 ]; then
        echo "verify_protocol: clean — 0 violations"
        rm -f "$tmp"
        exit 0
    fi
    cat "$tmp"
    echo "verify_protocol: enforce BLOCKS — $REPORT_COUNT violation(s) (UNARMED)"
    rm -f "$tmp"
    exit 1
}

# --- self-test (contract 9): plants, verifies, cleans ---------------------
PLANT=""
self_test() {
    local step="" base="" planted="" ec=""
    PLANT="$ROOT/verify_protocol_selftest_probe.py"
    cleanup() { rm -f "$PLANT"; }
    trap cleanup EXIT INT TERM

    # (a) base report count
    step="base-count"
    run_checks >/dev/null
    base="$REPORT_COUNT"

    # (b) plant a real violation inside the scan scope
    step="plant"
    printf '# selftest probe: raw color #059669\n' > "$PLANT"
    [ -f "$PLANT" ] || { echo "self-test FAIL: step=$step (plant not created)"; exit 1; }

    # (c) same report function: count must increase by exactly one
    step="count-increased"
    run_checks >/dev/null
    planted="$REPORT_COUNT"
    if [ $((planted - base)) -ne 1 ]; then
        echo "self-test FAIL: step=$step (base=$base planted=$planted)"
        exit 1
    fi

    # (d) --enforce path returns 1 while the violation is planted
    step="enforce-returns-1"
    bash "$0" --enforce >/dev/null 2>&1
    ec=$?
    if [ "$ec" -ne 1 ]; then
        echo "self-test FAIL: step=$step (enforce_exit=$ec)"
        exit 1
    fi

    # (e) delete the plant; verify gone and count back to base
    step="cleanup"
    rm -f "$PLANT"
    [ -e "$PLANT" ] && { echo "self-test FAIL: step=$step (plant still exists)"; exit 1; }
    step="count-returned"
    run_checks >/dev/null
    if [ "$REPORT_COUNT" -ne "$base" ]; then
        echo "self-test FAIL: step=$step (base=$base now=$REPORT_COUNT)"
        exit 1
    fi

    echo "self-test OK: base=$base planted=$((base + 1)) enforce_exit=1 restored=$base"
    exit 0
}

case "$mode" in
    report)    report_mode ;;
    enforce)   enforce_mode ;;
    self-test) self_test ;;
esac
