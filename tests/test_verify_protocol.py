"""Guardian contracts for scripts/verify_protocol.sh (Am+8 T-1c).

Each contract falls individually by its identifier:
  test_self_test_exits_zero            -> --self-test exits 0
  test_unknown_flag_exits_two          -> an unknown flag exits 2
  test_every_reported_violation_has_file_and_line
                                       -> every "- " line matches
                                          "- <path>:<line>: <message>"
The script is executed via ["bash", script, ...]; no interpreter name is
hard-coded in any argument.
"""
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "verify_protocol.sh"


def run_script(*args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


class TestVerifyProtocol(unittest.TestCase):
    def test_self_test_exits_zero(self):
        proc = run_script("--self-test")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_unknown_flag_exits_two(self):
        proc = run_script("--enfroce")
        self.assertEqual(proc.returncode, 2)

    def test_every_reported_violation_has_file_and_line(self):
        proc = run_script()
        self.assertEqual(proc.returncode, 0)
        for line in proc.stdout.splitlines():
            if line.startswith("- "):
                self.assertIsNotNone(re.match(r"^- [^:]+:[0-9]+: .", line), line)


    def test_no_line_escapes_the_violation_format(self):
        out = run_script().stdout
        for line in out.splitlines():
            if not line.strip() or line.startswith("verify_protocol:"):
                continue
            self.assertRegex(line, r"^- .+:[0-9]+: .")

    def test_footer_count_equals_violation_lines(self):
        out = run_script().stdout
        listed = len([l for l in out.splitlines() if l.startswith("- ")])
        m = re.search(r"^verify_protocol: ([0-9]+) violation", out, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), listed)


if __name__ == "__main__":
    unittest.main()
