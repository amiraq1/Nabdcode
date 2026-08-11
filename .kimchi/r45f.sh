#!/data/data/com.termux/files/usr/bin/bash
# R-4.5F — widen _RULED by human ruling (one word), then full green+protocol+tree.
set -o pipefail
cd ~/smart-agent || exit 1
case "${PREFIX:-UNSET}" in *com.termux*) : ;; *) echo HALT_NOT_TERMUX; exit 1;; esac
export GIT_PAGER=cat PAGER=cat
export LOG="${TMPDIR:-$PREFIX/tmp}/nabd-r45f"; mkdir -p "$LOG" || { echo HALT_NO_TMPDIR; exit 1; }
[ "$(git rev-parse --short HEAD)" = "778b213" ] || { echo HALT_HEAD; exit 1; }
echo "=== §0 GATE fp ==="
sha256sum ui/design/primitives/personality.py ui/widgets/status_bar.py tests/test_status_verbs_are_the_ruled_words.py | cut -c1-16,66- | tee "$LOG/fp_pre.txt"
grep -q '^2d0d21425f45b59d' "$LOG/fp_pre.txt" || { echo HALT_TREE_DRIFT; exit 1; }
grep -q '^42b5c014b36d6c18' "$LOG/fp_pre.txt" || { echo HALT_BAR_TOUCHED; exit 1; }
echo SENTINEL_GATE

python3 - <<'PY' 2>&1 | tee "$LOG/widen.txt"
import pathlib
p = pathlib.Path("tests/test_status_verbs_are_the_ruled_words.py")
s = p.read_text(encoding="utf-8")
OLD = '    Personality.DISABLED: "معطّل",\n'
assert s.count(OLD) == 1, f"ANCHOR_NOT_UNIQUE ruled n={s.count(OLD)}"
s = s.replace(OLD, OLD + '    Personality.PENDING: "بانتظار",\n')
DOC = "the contract is the exact ruled word.\n"
assert s.count(DOC) == 1, f"ANCHOR_NOT_UNIQUE doc n={s.count(DOC)}"
s = s.replace(DOC, DOC + '\nWidened by human ruling (Am, 2026-08-08 - seventh face, new neutral verb):\nPersonality.PENDING carries "بانتظار". The contract stays TOTAL - every face must\nstill carry a word Am ruled; no face may carry an empty one.\n')
p.write_text(s, encoding="utf-8")
print("WIDEN_OK")
PY

echo "=== §W1 WIDENED CONTRACT + SCOPE ==="
sed -n '1,34p' tests/test_status_verbs_are_the_ruled_words.py | cat -n
echo "--- scope (diff names / status / status_bar fp) ---"
git diff --name-only
git status --short | grep -v '^?? \.kimchi/'
sha256sum ui/widgets/status_bar.py | cut -c1-16,66-
echo SENTINEL_WIDEN

echo "=== §G1 TARGETED GREEN ==="
python3 -m pytest tests/test_status_verbs_are_the_ruled_words.py tests/test_status_line_faces_are_distinct.py tests/test_status_bar_parity.py tests/test_am8_d1_primitives.py tests/test_a_station_that_has_not_started_is_not_thinking.py tests/test_the_live_bar_speaks_the_ruled_verb.py -p no:cacheprovider 2>&1 | tail -8
echo "TARGETED_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_GREEN1

echo "=== §G2 FULL SUITE - PINNED SEED 3873563924 ==="
python3 -m pytest -p no:cacheprovider -p randomly --randomly-seed=3873563924 2>&1 | tail -6
echo "SUITE1_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_S1

echo "=== §G3 FULL SUITE - PINNED SEED 1 ==="
python3 -m pytest -p no:cacheprovider -p randomly --randomly-seed=1 2>&1 | tail -6
echo "SUITE2_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_S2

echo "=== §G4 FULL SUITE - FREE SEED (printed by pytest) ==="
python3 -m pytest -p no:cacheprovider 2>&1 | grep -E 'randomly-seed|passed|failed' | tail -6
echo "SUITE3_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_S3

echo "=== §G5 PROTOCOL ==="
bash scripts/verify_protocol.sh 2>&1 | tail -3
echo "PROTOCOL_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_PROTOCOL

echo "=== §G6 FINGERPRINTS AFTER ==="
sha256sum ui/design/primitives/personality.py ui/widgets/status_bar.py tests/test_status_verbs_are_the_ruled_words.py tests/test_a_station_that_has_not_started_is_not_thinking.py | cut -c1-16,66-
echo SENTINEL_FP

echo "=== §G7 TREE ==="
git diff --name-only
git status --short
git rev-parse --short HEAD
echo "NO_COMMIT_BY_DESIGN"
echo SENTINEL_FINAL
