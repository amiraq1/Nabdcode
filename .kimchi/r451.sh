#!/data/data/com.termux/files/usr/bin/bash
# R-4.5.1 — seventh face PENDING distinctness (idle no longer wears THINKING's verb)
# probe: temporarily make PENDING visually equal to THINKING, expect the widened
# guard to turn RED naming IDLE; then restore personality.py byte-for-byte.
set -o pipefail
cd ~/smart-agent || exit 1
case "${PREFIX:-UNSET}" in *com.termux*) : ;; *) echo HALT_NOT_TERMUX; exit 1;; esac
export GIT_PAGER=cat PAGER=cat
export LOG="${TMPDIR:-$PREFIX/tmp}/nabd-r451"; mkdir -p "$LOG" || { echo HALT_NO_TMPDIR; exit 1; }
[ "$(git branch --show-current)" = "am8/d-0" ] || { echo HALT_BRANCH; exit 1; }
[ "$(git rev-parse --short HEAD)" = "10531e7" ] || { echo HALT_HEAD; exit 1; }
git status --short | grep -v '^?? \.kimchi/$' | grep . && { echo HALT_DIRTY; exit 1; }
sha256sum ui/design/primitives/personality.py ui/widgets/status_bar.py tests/test_status_line_faces_are_distinct.py | cut -c1-16,66- | tee "$LOG/fp_pre.txt"
grep -q '^2d0d21425f45b59d' "$LOG/fp_pre.txt" || { echo HALT_PROD_DRIFT; exit 1; }
grep -q '^42b5c014b36d6c18' "$LOG/fp_pre.txt" || { echo HALT_BAR_DRIFT; exit 1; }
echo "PREDICTION_1: widened guard GREEN immediately (IDLE is genuinely distinct)"
echo "PREDICTION_2: under probe IDLE<->THINKING collapse, guard RED naming IDLE"
echo SENTINEL_GATE

cd ~/smart-agent
{
echo "=== A1 THE CONTRACT TO BE WIDENED, IN FULL ==="
cat -n tests/test_status_line_faces_are_distinct.py
echo "=== A1 BASELINE - MUST BE GREEN ==="
python3 -m pytest tests/test_status_line_faces_are_distinct.py -p no:cacheprovider 2>&1 | tail -4
echo "BASE_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_RECON
} 2>&1 | tee "$LOG/a1.txt"

cd ~/smart-agent
python3 - <<'PY' 2>&1 | tee "$LOG/widen.txt"
import pathlib
p = pathlib.Path("tests/test_status_line_faces_are_distinct.py")
s = p.read_text(encoding="utf-8")

# widen: the seventh face
OLD = "    UIState.DISABLED,\n"
assert s.count(OLD) == 1, f"ANCHOR_NOT_UNIQUE disabled n={s.count(OLD)}"
s = s.replace(OLD, OLD + "    UIState.IDLE,\n")

# SIX -> FACES everywhere
n = s.count("_SIX")
assert n >= 2, f"ANCHOR _SIX n={n}"
s = s.replace("_SIX", "_FACES")
assert "_SIX" not in s, "RENAME_INCOMPLETE"

# docstrings / fn name
for old, new in [
    ("the six visible faces must stay six.", "the seven visible faces must stay seven."),
    ("test_six_states_render_six_distinct_lines", "test_seven_states_render_seven_distinct_lines"),
]:
    c = s.count(old)
    assert c == 1, f"ANCHOR_NOT_UNIQUE {old!r} n={c}"
    s = s.replace(old, new)

# upgrade the assertion message so a probe that collapses IDLE with another
# face fails in a message that literally NAMES the colliding face ("IDLE").
anch = "assert len(set(lines)) == len(_FACES), lines"
assert s.count(anch) == 1, f"ANCHOR assertion n={s.count(anch)}"
s = s.replace(anch,
              "assert len(set(lines)) == len(_FACES), dict(zip((st.name for st in _FACES), lines))")

s = s.rstrip("\n") + '\n\n\n# Widened by human ruling (Am, 2026-08-08 - R-4.5.1): the seventh face\n# Personality.PENDING (UIState.IDLE) now carries distinctness coverage.\n'
p.write_text(s, encoding="utf-8")
print("WIDEN_OK")
PY

{
echo "=== A2 WIDENED CONTRACT ==="
cat -n tests/test_status_line_faces_are_distinct.py
echo "=== A3 SCOPE - ONE TEST FILE, NO PRODUCTION ==="
git diff --name-only
sha256sum ui/design/primitives/personality.py ui/widgets/status_bar.py | cut -c1-16,66-
echo SENTINEL_WIDEN
} 2>&1 | tee "$LOG/a2.txt"

cd ~/smart-agent
{
echo "=== A4 GREEN AS WIDENED (PREDICTION 1) ==="
python3 -m pytest tests/test_status_line_faces_are_distinct.py tests/test_a_station_that_has_not_started_is_not_thinking.py tests/test_status_verbs_are_the_ruled_words.py tests/test_am8_d1_primitives.py tests/test_status_bar_parity.py -p no:cacheprovider 2>&1 | tail -5
echo "WIDE_GREEN_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_GREEN1
} 2>&1 | tee "$LOG/a3.txt"

cd ~/smart-agent
cp ui/design/primitives/personality.py "$LOG/personality.bak" || { echo HALT_NO_BACKUP; exit 1; }
python3 - <<'PY' 2>&1 | tee "$LOG/probe.txt"
import re, pathlib
p = pathlib.Path("ui/design/primitives/personality.py")
s = p.read_text(encoding="utf-8")
m = re.search(r'[ \t]*Personality\.PENDING: PersonalityStyle\(.*?\n[ \t]*\),\n', s, re.S)
assert m, "ANCHOR_NOT_FOUND pending block"
blk = m.group(0)
new = blk.replace('"بانتظار"', '"يفكّر"')
assert new != blk, "PROBE_VERB_FAILED"
new2 = new.replace("SEMANTIC.text_muted", "SEMANTIC.thinking").replace("Icon.IDLE", "Icon.THINKING")
assert new2 != new, "PROBE_PAIR_FAILED"
p.write_text(s[:m.start()] + new2 + s[m.end():], encoding="utf-8")
print("PROBE_APPLIED")
PY

{
echo "=== A5 THE PROBE MUST REDDEN THE WIDENED GUARD (PREDICTION 2) ==="
python3 -m pytest tests/test_status_line_faces_are_distinct.py -p no:cacheprovider 2>&1 | tail -20
echo "PROBE_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_PROBE
} 2>&1 | tee "$LOG/a4.txt"

cd ~/smart-agent
{
echo "=== A6 RESTORE AND PROVE THE RESTORE ==="
cp "$LOG/personality.bak" ui/design/primitives/personality.py
sha256sum ui/design/primitives/personality.py | cut -c1-16,66- | tee "$LOG/fp_post_personality.txt"
sha256sum ui/design/primitives/personality.py | cut -c1-16 | grep -qx '2d0d21425f45b59d' && echo RESTORE_OK || echo HALT_RESTORE_FAILED
echo "--- git diff --name-only (should mention test_status_line_faces_are_distinct.py only) ---"
git diff --name-only
git status --short
echo "=== A7 GREEN AGAIN AFTER RESTORE (target set) ==="
python3 -m pytest tests/test_status_line_faces_are_distinct.py tests/test_a_station_that_has_not_started_is_not_thinking.py tests/test_status_verbs_are_the_ruled_words.py tests/test_am8_d1_primitives.py tests/test_status_bar_parity.py -p no:cacheprovider 2>&1 | tail -5
echo "TARGETED_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_RESTORE
} 2>&1 | tee "$LOG/a5.txt"

cd ~/smart-agent
{
echo "=== A8 FULL SUITE - PINNED SEED 3873563924 ==="
python3 -m pytest -p no:cacheprovider -p randomly --randomly-seed=3873563924 2>&1 | tail -5
echo "SUITE1_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_S1
} 2>&1 | tee "$LOG/s1.txt"

cd ~/smart-agent
{
echo "=== A9 FULL SUITE - PINNED SEED 1 ==="
python3 -m pytest -p no:cacheprovider -p randomly --randomly-seed=1 2>&1 | tail -5
echo "SUITE2_EXIT=${PIPESTATUS[0]}"
echo SENTINEL_S2
} 2>&1 | tee "$LOG/s2.txt"

cd ~/smart-agent
{
echo "=== A10 FULL SUITE - FREE SEED ==="
python3 -m pytest -p no:cacheprovider 2>&1 | grep -E 'randomly-seed|passed|failed' | tail -5
echo "SUITE3_EXIT=${PIPESTATUS[0]}"
echo "=== A11 PROTOCOL ==="
bash scripts/verify_protocol.sh 2>&1 | tail -3
echo "PROTOCOL_EXIT=${PIPESTATUS[0]}"
echo "=== A12 FINAL FINGERPRINTS ==="
sha256sum tests/test_status_line_faces_are_distinct.py ui/design/primitives/personality.py ui/widgets/status_bar.py | cut -c1-16,66-
echo "=== A13 TREE ==="
git diff --name-only
git status --short
git rev-parse --short HEAD
echo "NO_COMMIT_BY_DESIGN"
echo SENTINEL_FINAL
} 2>&1 | tee "$LOG/s3.txt"
