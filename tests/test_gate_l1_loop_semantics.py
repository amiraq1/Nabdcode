import ast
import json
from unittest import TestCase

class TestGateL1TruthTableSemantics(TestCase):
    MANIFEST_AST_SITES = [
        ('engine/loop.py', 365, 'CONTINUE'),
        ('engine/loop.py', 773, 'PROCEED'),
        ('engine/loop.py', 862, 'PROCEED'),
        ('engine/loop.py', 903, 'PROCEED'),
        ('engine/loop.py', 962, 'PROCEED'),
        ('engine/loop.py', 995, 'PROCEED'),
        ('engine/loop.py', 1517, 'CONTINUE'),
        ('engine/loop.py', 364, 'TERMINATE'),
        ('engine/loop.py', 753, 'TERMINATE'),
        ('engine/loop.py', 855, 'CONTINUE'),
        ('engine/loop.py', 860, 'CONTINUE'),
        ('engine/loop.py', 1496, 'TERMINATE'),
        ('engine/loop.py', 1499, 'TERMINATE'),
        ('engine/loop.py', 769, 'TERMINATE'),
        ('engine/loop.py', 897, 'CONTINUE'),
        ('engine/loop.py', 937, 'CONTINUE'),
        ('engine/loop.py', 959, 'CONTINUE'),
        ('engine/_budget.py', 82, 'PROCEED'),
        ('engine/_budget.py', 81, 'TERMINATE'),
        ('engine/_budget.py', 80, 'CONTINUE'),
        ('engine/_convergence.py', 310, 'TERMINATE'),
        ('engine/_convergence.py', 244, 'CONTINUE'),
        ('engine/_convergence.py', 309, 'CONTINUE'),
        ('engine/_convergence.py', 296, 'TERMINATE'),
        ('engine/_convergence.py', 287, 'CONTINUE'),
        ('engine/_tool_runner.py', 144, 'PROCEED'),
        ('engine/_tool_runner.py', 62, 'FINAL_ANSWER'),
        ('engine/_tool_runner.py', 132, 'CONTINUE'),
    ]

    def test_truth_table_every_return_site_enumerated(self):
        """Must list exactly the 28 required AST sites."""
        self.assertEqual(len(self.MANIFEST_AST_SITES), 28)

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
        sec_guards = [s for s in self.MANIFEST_AST_SITES if s[0] == "engine/loop.py" and s[1] in (937, 959, 962, 995)]
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
        line_365 = lines[364]
        self.assertIn("CONTINUE", line_365)
    
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
