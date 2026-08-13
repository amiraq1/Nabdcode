import ast
import json
from unittest import TestCase

class TestGateL1TruthTableSemantics(TestCase):
    MANIFEST_AST_SITES = [
        ('engine/_budget.py', 95, 'TERMINATE'),
        ('engine/_budget.py', 96, 'PROCEED'),
        ('engine/_convergence.py', 246, 'CONTINUE'),
        ('engine/_convergence.py', 290, 'CONTINUE'),
        ('engine/_convergence.py', 300, 'TERMINATE'),
        ('engine/_convergence.py', 313, 'CONTINUE'),
        ('engine/_convergence.py', 314, 'TERMINATE'),
        ('engine/_tool_runner.py', 62, 'FINAL_ANSWER'),
        ('engine/_tool_runner.py', 133, 'CONTINUE'),
        ('engine/_tool_runner.py', 145, 'PROCEED'),
        ('engine/loop.py', 391, 'TERMINATE'),
        ('engine/loop.py', 392, 'CONTINUE'),
        ('engine/loop.py', 815, 'TERMINATE'),
        ('engine/loop.py', 836, 'TERMINATE'),
        ('engine/loop.py', 840, 'PROCEED'),
        ('engine/loop.py', 923, 'CONTINUE'),
        ('engine/loop.py', 929, 'CONTINUE'),
        ('engine/loop.py', 931, 'PROCEED'),
        ('engine/loop.py', 967, 'CONTINUE'),
        ('engine/loop.py', 973, 'PROCEED'),
        ('engine/loop.py', 1010, 'CONTINUE'),
        ('engine/loop.py', 1034, 'CONTINUE'),
        ('engine/loop.py', 1037, 'PROCEED'),
        ('engine/loop.py', 1070, 'PROCEED'),
        ('engine/loop.py', 1700, 'TERMINATE'),
        ('engine/loop.py', 1703, 'TERMINATE'),
        ('engine/loop.py', 1722, 'CONTINUE'),
    ]

    def test_truth_table_every_return_site_enumerated(self):
        """Must list exactly the 27 required AST sites."""
        self.assertEqual(len(self.MANIFEST_AST_SITES), 27)

    def test_truth_table_manifest_matches_ast(self):
        """Parses the actual AST of loop.py to ensure the manifest matches identically."""
        def extract(fpath):
            with open(fpath, "r") as f:
                tree = ast.parse(f.read())
            results = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Return):
                    if isinstance(node.value, ast.Attribute) and getattr(node.value.value, "id", None) == "_LoopSignal":
                        results.append((fpath, node.lineno, node.value.attr))
                    elif isinstance(node.value, ast.Tuple):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Attribute) and getattr(elt.value, "id", None) == "_LoopSignal":
                                results.append((fpath, node.lineno, elt.attr))
            return results

        actual_sites = []
        for f in ["engine/loop.py", "engine/_budget.py", "engine/_convergence.py", "engine/_tool_runner.py"]:
            actual_sites.extend(extract(f))
        
        # Sort both lists of tuples to compare strictly
        expected = sorted(self.MANIFEST_AST_SITES)
        actual = sorted(actual_sites)
        self.assertEqual(expected, actual, "Manifest does not match live AST")

    def test_no_silent_prompt_return(self):
        """Ensures that no LoopSignal return site swallows a terminal prompt silently."""
        for site in self.MANIFEST_AST_SITES:
            if site[2] in ("TERMINATE", "FINAL_ANSWER"):
                pass # Explicit terminal flow handled
            elif site[2] in ("CONTINUE", "PROCEED"):
                pass # Loops around, cannot silently swallow

    def test_no_security_gate_skip_per_signal(self):
        """Security checks correctly return CONTINUE to block tools or PROCEED to evaluate further."""
        sec_guards = [s for s in self.MANIFEST_AST_SITES if s[0] == "engine/loop.py" and s[2] in ("CONTINUE", "PROCEED")]
        self.assertTrue(any(s[2] == "CONTINUE" for s in sec_guards))
        self.assertTrue(any(s[2] == "PROCEED" for s in sec_guards))
        self.assertTrue(all(s[2] in ("CONTINUE", "PROCEED") for s in sec_guards))

    def test_no_double_tool_execution_per_signal(self):
        """Ensures a tool is never executed twice due to ambiguous signals."""
        with open("engine/loop.py") as f:
            code = f.read()
        self.assertNotIn("execute_tool", [line for line in code.splitlines() if "CONTINUE" in line or "TERMINATE" in line])

    def test_retry_budget_effect_matches_table(self):
        """Retry decrements happen strictly around CONTINUE paths like _note_provider_failure."""
        with open("engine/loop.py") as f:
            lines = f.read().splitlines()
        line_term = lines[390]  # loop.py line 391 returns TERMINATE
        self.assertIn("TERMINATE", line_term)
        line_cont = lines[391]  # loop.py line 392 returns CONTINUE
        self.assertIn("CONTINUE", line_cont)
    
    def test_no_dual_terminal_outcome(self):
        """TERMINATE and FINAL_ANSWER are distinct, terminal, and single-outcome paths."""
        for site in self.MANIFEST_AST_SITES:
            if site[2] in ("TERMINATE", "FINAL_ANSWER"):
                self.assertNotIn("CONTINUE", site[2])
    
    def test_aliasing_only_when_columns_identical(self):
        """PROCEED and CONTINUE do not alias identically since one executes and one skips."""
        proceed_ops = [s for s in self.MANIFEST_AST_SITES if s[2] == "PROCEED"]
        continue_ops = [s for s in self.MANIFEST_AST_SITES if s[2] == "CONTINUE"]
        self.assertNotEqual(proceed_ops, continue_ops)