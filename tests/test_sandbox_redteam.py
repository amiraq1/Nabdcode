import pytest
from pathlib import Path
from core.self_refinement import SafeExecutionSandbox
import ast

def test_class_a_rejections():
    attacks = [
        "import os",
        "from os import system",
        "__import__('os')",
        "open('/data/x').read",
        "eval('1')",
        "exec('pass')",
        "import subprocess",
        "import socket",
        "import shutil",
        "import builtins",
        "().__class__.__bases__[0].__subclasses__()",
        "getattr(object, '__subclasses__')()",
        "lambda: __import__('os')",
        "[c for c in ().__class__.__bases__[0].__subclasses__()]"
    ]
    for attack in attacks:
        valid, _ = SafeExecutionSandbox._validate_code(attack)
        assert valid is False, f"Attack allowed: {attack}"

def test_class_b_boundaries():
    assert "os" not in SafeExecutionSandbox._ALLOWED_MODULES
    assert "sys" not in SafeExecutionSandbox._ALLOWED_MODULES
    assert "subprocess" not in SafeExecutionSandbox._ALLOWED_MODULES
    assert "socket" not in SafeExecutionSandbox._ALLOWED_MODULES
    assert "builtins" not in SafeExecutionSandbox._ALLOWED_MODULES
    assert "shutil" not in SafeExecutionSandbox._ALLOWED_MODULES

    assert "__subclasses__" in SafeExecutionSandbox._FORBIDDEN_ATTRIBUTES
    assert "__globals__" in SafeExecutionSandbox._FORBIDDEN_ATTRIBUTES
    assert "__builtins__" in SafeExecutionSandbox._FORBIDDEN_ATTRIBUTES
    assert "__class__" in SafeExecutionSandbox._FORBIDDEN_ATTRIBUTES

    assert "__import__" in SafeExecutionSandbox._FORBIDDEN_NAMES
    assert "eval" in SafeExecutionSandbox._FORBIDDEN_NAMES
    assert "exec" in SafeExecutionSandbox._FORBIDDEN_NAMES
    assert "open" in SafeExecutionSandbox._FORBIDDEN_NAMES
    assert "compile" in SafeExecutionSandbox._FORBIDDEN_NAMES
    assert "input" in SafeExecutionSandbox._FORBIDDEN_NAMES

def test_class_c_worker_isolation():
    worker_code = Path("core/sandbox_worker.py").read_text()
    assert "runpy" in worker_code
    assert "exec(" not in worker_code
    assert "eval(" not in worker_code

def test_class_d_runtime_constraints():
    sr_code = Path("core/self_refinement.py").read_text()
    assert "timeout=timeout" in sr_code
    assert "env=" in sr_code

def test_class_e_evidence_freshness():
    dna_code = Path("ARCHITECTURE_DNA.md").read_text()
    assert "core/self_refinement.py:59 (DYNAMIC_CODE_EXECUTION)" not in dna_code
