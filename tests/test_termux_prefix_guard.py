"""tests/test_termux_prefix_guard.py — A.2 guard for Termux PREFIX environment."""

from __future__ import annotations

import os
import sys
import subprocess
from unittest.mock import patch
import pytest

def test_termux_prefix_guard_exits_when_not_in_termux():
    """A.2: main.py must exit with code 1 if PREFIX does not contain com.termux."""
    env = os.environ.copy()
    if "PREFIX" in env:
        del env["PREFIX"]

    # Run main.py as a subprocess to verify the fast exit
    # Python -c to import and run main() avoids hanging if it actually starts
    code = (
        "import sys\n"
        "import os\n"
        "import main\n"
        "main.main()\n"
    )
    
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 1
    assert "SECURITY VIOLATION: NABD OS requires a Termux environment" in result.stdout

def test_termux_prefix_guard_passes_in_termux():
    """A.2: main.py should NOT exit if PREFIX contains com.termux."""
    env = os.environ.copy()
    env["PREFIX"] = "/data/data/com.termux/files/usr"
    
    # We mock _check_cli_flags to return True so main() returns cleanly
    # without starting the actual REPL loop or hanging.
    code = (
        "import sys\n"
        "import os\n"
        "from unittest.mock import patch\n"
        "import main\n"
        "with patch('main._check_cli_flags', return_value=True):\n"
        "    main.main()\n"
    )
    
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0
    assert "SECURITY VIOLATION" not in result.stdout
