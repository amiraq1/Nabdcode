"""
V3 Performance Guard: on_final_answer must not use blocking time.sleep
with a small chunk_size that causes excessive loop iterations.

Problem:
- chunk_size=3 + time.sleep(0.04) → 600 words = 200 iterations ≈ 8s blocking
- time.sleep blocks the worker thread entirely

Fix contract:
- chunk_size >= 10 (reduces iterations by 3.3×)
- time.sleep delay <= 0.01s (4× faster per iteration)
- Total: ≥ 13× improvement (8s → <1s for 600 words)
"""
import ast
import pathlib


def _get_on_final_answer_node(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "on_final_answer":
            return node
    raise AssertionError("on_final_answer not found in ui/repl_termux.py")


def test_on_final_answer_chunk_size_is_at_least_10():
    """V3: chunk_size must be >= 10 to avoid 200+ iterations for 600-word answers.

    UI-CC-5: the animated chunked Live loop was removed entirely — the answer
    is printed in one shot (no loop at all), which is strictly better than any
    chunk_size. Absence of chunk_size is therefore acceptable (even better).
    """
    src = pathlib.Path("ui/repl_termux.py").read_text()
    tree = ast.parse(src)
    node = _get_on_final_answer_node(tree)

    for child in ast.walk(node):
        if isinstance(child, ast.Assign):
            for t in child.targets:
                if isinstance(t, ast.Name) and t.id == "chunk_size":
                    value = child.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, int):
                        assert value.value >= 10, (
                            f"chunk_size={value.value} is too small — "
                            "must be >= 10 to avoid excessive blocking iterations. "
                            "V3 fix: change chunk_size to 10."
                        )
                        return
    # No chunk_size found: the chunked loop was removed (UI-CC-5) —
    # a single-shot print is even better than a large chunk_size.
    return


def test_on_final_answer_sleep_delay_is_at_most_0_02():
    """V3: time.sleep delay must be <= 0.02s to limit per-iteration blocking."""
    src = pathlib.Path("ui/repl_termux.py").read_text()
    tree = ast.parse(src)
    node = _get_on_final_answer_node(tree)

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if not (isinstance(child.func, ast.Attribute) and child.func.attr == "sleep"):
            continue
        if not (isinstance(child.func.value, ast.Name) and child.func.value.id == "time"):
            continue
        if child.args:
            arg = child.args[0]
            if isinstance(arg, ast.Constant):
                assert arg.value <= 0.02, (
                    f"time.sleep({arg.value}) is too large — "
                    "must be <= 0.02s per iteration. "
                    "V3 fix: reduce to 0.01."
                )
                return
    # If no time.sleep found, that is also acceptable (even better)
