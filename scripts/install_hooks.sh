#!/usr/bin/env bash
# install_hooks.sh — Install NABD OS pre-commit hook
# Usage: bash scripts/install_hooks.sh
# Safe to re-run: replaces existing hook with a symlink to scripts/pre_commit_check.sh

set -euo pipefail

HOOK_DIR=".git/hooks"
HOOK_PATH="${HOOK_DIR}/pre-commit"
TARGET="../../scripts/pre_commit_check.sh"

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo '.')"

if [ ! -d "$HOOK_DIR" ]; then
    echo "FATAL: not a git repository (no .git/hooks directory)."
    exit 1
fi

if [ ! -f "scripts/pre_commit_check.sh" ]; then
    echo "FATAL: scripts/pre_commit_check.sh not found."
    exit 1
fi

ln -sf "$TARGET" "$HOOK_PATH"
chmod +x "$HOOK_PATH"

echo "OK: pre-commit hook installed."
echo "  $(readlink -f "$HOOK_PATH") -> $TARGET"
echo ""
echo "The hook runs 6 gates (~6s, offline):"
echo "  1. Red team validation"
echo "  2. Schema snapshot contract"
echo "  3. Event name snapshot contract"
echo "  4. Forbidden-changes policy"
echo "  5. Exact-action contract"
echo "  6. Claim gate + Arabic verification"
echo ""
echo "To bypass intentionally (reviewed changes only):"
echo "  git commit --no-verify -m \"... [POLICY_OVERRIDE] ...\""
echo "Then verify via pre-push or full suite."
echo ""
echo "To check if hook is active:"
echo "  [ -x .git/hooks/pre-commit ] && echo 'active' || echo 'missing'"
