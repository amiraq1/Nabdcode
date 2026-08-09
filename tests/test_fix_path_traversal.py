"""
S-1: /fix must reject path traversal attempts in both paths.

Covers:
  - one-shot path  (_handle_one_shot_query → engine.run(one_shot_query))
  - interactive path (_process_slash_command → /fix branch)
"""
import subprocess
import sys
import os


def test_fix_rejects_traversal_one_shot():
    """حارس تكاملي: one-shot /fix ../../etc/passwd يجب أن يرفض."""
    result = subprocess.run(
        [sys.executable, "main.py", "/fix ../../etc/passwd -> test_func"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=os.getcwd(),
        stdin=subprocess.DEVNULL,
    )

    combined_output = (result.stdout + result.stderr).lower()

    is_rejected = (
        result.returncode != 0
        or "outside" in combined_output
        or "not allowed" in combined_output
        or "error" in combined_output
    )

    assert is_rejected, (
        f"/fix one-shot لم يرفض المسار الخبيث!\n"
        f"Return Code: {result.returncode}\n"
        f"--- STDOUT ---\n{result.stdout}\n"
        f"--- STDERR ---\n{result.stderr}"
    )


def test_fix_rejects_traversal_interactive():
    """حارس وحدة: _process_slash_command يجب أن يرفض المسار الخبيث."""
    from main import _process_slash_command
    from io import StringIO

    # _process_slash_command(user_input, state, ctx, base_inst) — 4 args.
    # الـ /fix branch (509-560) لا يلمس state/ctx/base_inst، لذا نمرّ (None, None, "")
    # — التصحيح من النسخة الأصلية (1 arg) لتجنب TypeError على الـ signature الثابتة.
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        _process_slash_command("/fix ../../etc/passwd -> test_func", None, None, "")
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    assert (
        "outside" in output.lower()
        or "error" in output.lower()
        or "not allowed" in output.lower()
    ), f"_process_slash_command لم يرفض المسار الخبيث: {output}"
