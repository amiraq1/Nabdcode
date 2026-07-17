# core/kernel/security.py
"""
Security validation engine — self-contained leaf node.

Zero imports from core/ or engine/. All dependencies (SAFE_BINARIES,
_validate_path, get_workspace_root) are inlined here to guarantee
the kernel island has no external coupling.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Final, List, Set, Tuple


# ── Workspace root (inlined from core/parser) ────────────────────────────────
# Pinned once by AppContext.build(); used by _validate_path below.
_WORKSPACE_ROOT: Path | None = None


def pin_workspace_root(root: Path) -> None:
    """Pin the workspace root for path validation."""
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = root.resolve()


def get_workspace_root() -> Path:
    """Return the pinned workspace root, or cwd as fallback."""
    return _WORKSPACE_ROOT.resolve() if _WORKSPACE_ROOT else Path.cwd().resolve()


def _validate_path(path: str) -> bool:
    """Return True if *path* resolves inside the workspace root."""
    try:
        root = get_workspace_root()
        resolved = (root / path).resolve()
        resolved.relative_to(root)
        return True
    except Exception:
        return False


# ── Safe binaries (inlined from core/constants) ──────────────────────────────

SAFE_BINARIES: Final[Set[str]] = {
    "ls", "pwd", "echo", "whoami", "cat", "grep", "date",
    "ps", "uptime", "df", "free", "history", "clear", "find", "wc",
    "du", "sort", "head", "tail", "awk", "top",
    "termux-battery-status", "termux-telephony-deviceinfo",
    "git", "python", "python3", "uname", "id",
    "sleep", "lsof", "pytest",
}


# ── Installation-command interception ────────────────────────────────────────

_INSTALL_PATTERN = re.compile(
    r"(?:^|[\s;|&])(?:pip3?|ensurepip)\b|"
    r"\b(?:pip3?|ensurepip)\s+(?:install|-m\s+pip|install\s+--user|install\s+-r)|"
    r"\bget-pip\.py\b|"
    r"\bpip3?\s+install\b",
    re.IGNORECASE,
)

_INSTALL_BLOCKED_MESSAGE = (
    "Installation blocked by NABD OS Security Layer. You are strictly FORBIDDEN "
    "from installing packages via shell. ARCHITECTURAL PATH: Write your full "
    "Python code block with the required 'import' statements directly inside your "
    "payload. The NABD OS Orchestrator will automatically capture the imports and "
    "provision them via UvIsolationManager."
)


def _is_install_command(command: str) -> bool:
    """Return True if the command attempts to install Python packages."""
    return bool(_INSTALL_PATTERN.search(command))


# ── shlex Tokenizer ─────────────────────────────────────────────────────────

_DEFAULT_PUNCTUATION: str = ";()<>|&"


def _tokenize(command: str) -> Tuple[bool, List[str], str]:
    """
    Tokenize a shell command using shlex with punctuation_chars.
    Returns (ok, tokens, error_reason).
    `;` and `|` appear as separate tokens only when NOT inside quotes.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_DEFAULT_PUNCTUATION)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as e:
        return False, [], f"Unterminated quote: {e}"

    if not tokens:
        return False, [], "Command is empty."
    return True, tokens, ""


# ── Split Pipes (quote-aware) ───────────────────────────────────────────────

def split_pipe_segments(command: str) -> Tuple[bool, List[List[str]], str]:
    """
    Split a shell command into pipe segments, preserving quoted context.
    Returns (ok, list_of_token_lists, error_reason).

    Example:
        echo "a|b" | grep c  →  [["echo", "\"a|b\""], ["grep", "c"]]
    """
    ok, tokens, err = _tokenize(command)
    if not ok:
        return False, [], err

    segments: List[List[str]] = []
    current: List[str] = []

    for t in tokens:
        if t == "|":
            if not current:
                return False, [], "Empty pipe segment."
            segments.append(current)
            current = []
        else:
            current.append(t)

    if not current:
        return False, [], "Empty pipe segment after final pipe."
    segments.append(current)

    return True, segments, ""


# ── Danger Check ────────────────────────────────────────────────────────────

def _dangerous_operators_unquoted(command: str) -> Tuple[bool, str]:
    """
    Scan raw command string for dangerous operators OUTSIDE quotes.
    Tracks single-quote, double-quote, and $'...' contexts.
    Only flags ` ; $( when they appear at the syntactic (unquoted) level.
    """
    i = 0
    n = len(command)
    in_single = False
    in_double = False

    while i < n:
        ch = command[i]

        # Handle escape sequences
        if ch == '\\' and i + 1 < n:
            i += 2
            continue

        # Toggle single-quote
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue

        # Toggle double-quote
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if not in_single and not in_double:
            if ch == ';':
                return False, "Command separator ';' is not allowed."
            if ch == '`':
                return False, "Backtick substitution is not allowed."
            if ch == '\n':
                return False, "Newline inside command is not allowed."
            if ch == '&' and i + 1 < n and command[i + 1] == '&':
                return False, "Logical AND '&&' is not allowed."
            if ch == '|' and i + 1 < n and command[i + 1] == '|':
                return False, "Logical OR '||' is not allowed."
            if ch == '$' and i + 1 < n and command[i + 1] == '(':
                return False, "Command substitution $() is not allowed."

        i += 1

    return True, ""


DANGEROUS_FLAGS = {"-c", "-e", "--eval", "--exec", "--import", "-i", "--interactive"}
INTERPRETERS = {"python", "python3", "bash", "sh", "node"}
BANNED_PYTHON_MODULES = {"pip", "http", "http.server", "urllib", "subprocess", "os", "pty", "eval", "shutil"}

# Nested-shell / hidden-exfiltration interception
_NESTED_SHELL_BINARIES = {"bash", "sh", "csh", "zsh", "ksh", "fish", "tcsh"}
_EXFILTRATION_BINARIES = {"curl", "wget", "nc", "ncat", "netcat", "telnet", "socat"}

# Phase2.1 — obfuscation / decode-and-execute payload banners
_DECODE_BINARIES = {"base64", "xxd", "openssl"}
_DECODE_INTERPRETER_FLAGS = {
    "python", "python3", "-c",
    "perl", "-e",
    "ruby", "-e",
}
_EVAL_INTERPRETERS = {"python", "python3", "perl", "ruby"}

# Phase2.1 — regex heuristics for obfuscated payloads
_BASE64_LIKE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_HEX_ESCAPE = re.compile(r"(\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|u\{[0-9a-fA-F]+\}|[0-7]{1,3})|%[0-9a-fA-F]{2})")
_EVAL_EXEC = re.compile(r"\b(?:eval|exec)\s*\(", re.IGNORECASE)


def _scan_full_argument_vector(command: str) -> Tuple[bool, str]:
    """Block nested shells / exfiltration / obfuscated decode-exec payloads."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False, "Malformed command quoting; refusing to execute."

    lowered = [t.lower() for t in tokens]
    for idx, tok in enumerate(tokens):
        base = tok.split("/")[-1].lower()
        if base in _NESTED_SHELL_BINARIES:
            return False, f"Nested shell interpreter '{tok}' is not allowed anywhere in the command."
        if base in _EXFILTRATION_BINARIES:
            return False, f"Network exfiltration tool '{tok}' is not allowed anywhere in the command."

        if base in _DECODE_BINARIES:
            return False, (
                f"Decode binary '{tok}' is not allowed — it is a common "
                f"obfuscation/encoding-bypass vector for shell payloads."
            )
        if base in ("-c", "-e") and idx > 0:
            prev = lowered[idx - 1].split("/")[-1]
            if prev in _EVAL_INTERPRETERS:
                return False, (
                    f"String-eval flag '{tok}' on interpreter '{prev}' is not "
                    f"allowed — it executes opaque code from a blob."
                )
        if base in _DECODE_INTERPRETER_FLAGS and base in _EVAL_INTERPRETERS:
            if idx + 1 < len(tokens) and tokens[idx + 1] in ("-c", "-e"):
                return False, (
                    f"Interpreter '{base}' with string-eval flag is not allowed "
                    f"(obfuscated payload execution)."
                )

    if _BASE64_LIKE.search(command):
        return False, (
            "Refusing command: long base64-like blob detected — possible "
            "encoded payload (e.g. 'echo <B64> | base64 -d | bash')."
        )
    if len(_HEX_ESCAPE.findall(command)) >= 4:
        return False, (
            "Refusing command: heavy hex/escape smuggling detected "
            "(>=4 '\\xHH'/'%HH' tokens) — possible obfuscated payload."
        )
    if _EVAL_EXEC.search(command):
        return False, (
            "Refusing command: embedded 'eval('/'exec(' inside a shell "
            "string — possible dynamic-code payload."
        )
    return True, ""


def _validate_segment_args(tokens: List[str]) -> Tuple[bool, str]:
    if not tokens:
        return False, "Empty segment."
    bin_name = tokens[0]
    if bin_name == "xargs":
        return False, "Binary 'xargs' is not allowed."
    if bin_name not in SAFE_BINARIES:
        return False, f"Binary '{bin_name}' is not whitelisted."
    for arg in tokens[1:]:
        if arg in DANGEROUS_FLAGS:
            return False, f"Dangerous argument '{arg}' is not allowed for binary '{bin_name}'."
    if bin_name in INTERPRETERS:
        for idx, arg in enumerate(tokens[1:]):
            if arg == "-m" and idx + 1 < len(tokens[1:]):
                mod = tokens[1:][idx + 1]
                if mod in BANNED_PYTHON_MODULES or any(b in mod for b in BANNED_PYTHON_MODULES):
                    return False, f"Banned python module '{mod}' is not allowed."
            if arg.endswith(".py") or arg.endswith(".sh") or arg.endswith(".js"):
                if not _validate_path(arg):
                    return False, f"Script file execution '{arg}' outside workspace is not allowed for '{bin_name}'."
            elif arg.startswith("/") and not _validate_path(arg):
                return False, f"Absolute path '{arg}' outside workspace is not allowed for '{bin_name}'."
    return True, ""


# ── Public API ──────────────────────────────────────────────────────────────

def validate(command: str) -> Tuple[bool, str]:
    if not command or not command.strip():
        return False, "Command is empty."

    cmd_str = command.strip()

    # 0. Installation-command interception
    if _is_install_command(cmd_str):
        return False, _INSTALL_BLOCKED_MESSAGE

    # 1. Check for dangerous operators at the unquoted syntactic level
    safe, reason = _dangerous_operators_unquoted(cmd_str)
    if not safe:
        return False, reason

    # 2. Tokenize (quote-aware) to split pipes
    ok, tokens, err = _tokenize(cmd_str)
    if not ok:
        return False, err

    # 3. Handle pipes
    if "|" in tokens:
        ok, segments, err = split_pipe_segments(cmd_str)
        if not ok:
            return False, err
        for idx, seg_tokens in enumerate(segments):
            if idx > 0 and seg_tokens and seg_tokens[0] in INTERPRETERS:
                return False, f"Piping into interpreter '{seg_tokens[0]}' is not allowed."
            ok_seg, reason = _validate_segment_args(seg_tokens)
            if not ok_seg:
                return False, reason
        safe, reason = _scan_full_argument_vector(cmd_str)
        if not safe:
            return False, reason
        return True, "Safe piped command."

    # 4. Simple command
    ok_seg, reason = _validate_segment_args(tokens)
    if not ok_seg:
        return False, reason
    # 5. Full-vector nested-shell / exfiltration sweep
    safe, reason = _scan_full_argument_vector(cmd_str)
    if not safe:
        return False, reason
    return True, "Safe single command."


def is_safe_command(command: str) -> bool:
    return validate(command)[0]
