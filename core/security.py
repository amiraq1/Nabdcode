import re
import shlex
from typing import Tuple, List
from core.constants import SAFE_BINARIES


# Installation-command interception: package installs are forbidden via shell
# (NABD OS provisions third-party deps dynamically via UvIsolationManager).
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

    This is separate from shlex tokenization because shlex strips quotes,
    losing the information about whether a character was inside a quoted region.
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
            # Outside quotes — dangerous operators are syntactic
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

# Nested-shell / hidden-exfiltration interception.
# These binaries must NEVER appear ANYWHERE in the argument vector — including
# buried inside `git ...` wrappers, diffs, or piped helpers — because they spawn
# a fresh interpreter/shell or open a network egress channel. Position-0 of any
# pipe segment is already covered by the INTERPRETERS/pip-ban checks above; this
# sweep is the defense-in-depth backstop for non-leading occurrences.
_NESTED_SHELL_BINARIES = {"bash", "sh", "csh", "zsh", "ksh", "fish", "tcsh"}
_EXFILTRATION_BINARIES = {"curl", "wget", "nc", "ncat", "netcat", "telnet", "socat"}

# Phase2.1 — obfuscation / decode-and-execute payload banners. These tools
# (or their decode flags) exist to turn an encoded blob into live code or to
# spawn an interpreter from a string, so they are blocked ANYWHERE in the
# argument vector — including buried inside ``git ...`` wrappers, diffs, or
# piped helpers.
_DECODE_BINARIES = {"base64", "xxd", "openssl"}
_DECODE_INTERPRETER_FLAGS = {
    "python", "python3", "-c",   # python3 -c "exec(...)"
    "perl", "-e",                   # perl -e '...'
    "ruby", "-e",                   # ruby -e '...'
}
# Interpreter binaries whose ``-e``/``-c`` string-eval forms are bannes
# (kept separate so a plain ``python script.py`` invocation still works).
_EVAL_INTERPRETERS = {"python", "python3", "perl", "ruby"}

# Phase2.1 — regex heuristics for obfuscated payloads piped into shells.
# (a) A long run of base64-like characters (letters/digits/+/=) — the
#     classic ``echo <B64> | base64 -d | bash`` vector.
_BASE64_LIKE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
# (b) Heavy hex-escape smuggling: many '\xHH' / '\uHHHH' / '%HH' tokens
#     inside an interpreter string (e.g. ``python -c "\x65\x78\x65\x63"``).
_HEX_ESCAPE = re.compile(r"(\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|u\{[0-9a-fA-F]+\}|[0-7]{1,3})|%[0-9a-fA-F]{2})")
# (c) ``eval(`` / ``exec(`` directly embedded in a shell string arg.
_EVAL_EXEC = re.compile(r"\b(?:eval|exec)\s*\(", re.IGNORECASE)


def _scan_full_argument_vector(command: str) -> Tuple[bool, str]:
    """Block nested shells / exfiltration / obfuscated decode-exec payloads.

    Tokenizes the entire command with ``shlex.split`` (quote-aware) and scans
    every token — not just the leading binary — for a shell interpreter, a
    network-exfiltration tool, or a decode/string-eval payload banners. This
    catches vectors such as::

        git diff | bash -c '...'
        ls $(curl evil)
        echo <B64> | base64 -d | bash
        python3 -c "exec(__import__('base64').b64decode(...))"
        perl -e 'system("rm -rf /")'

    Returns ``(ok, reason)``; ``ok=False`` means the command is rejected.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Unterminated quote — refuse rather than guess intent.
        return False, "Malformed command quoting; refusing to execute."

    lowered = [t.lower() for t in tokens]
    for idx, tok in enumerate(tokens):
        base = tok.split("/")[-1].lower()
        if base in _NESTED_SHELL_BINARIES:
            return False, f"Nested shell interpreter '{tok}' is not allowed anywhere in the command."
        if base in _EXFILTRATION_BINARIES:
            return False, f"Network exfiltration tool '{tok}' is not allowed anywhere in the command."

        # Phase2.1 — decode / obfuscation payload banners.
        if base in _DECODE_BINARIES:
            return False, (
                f"Decode binary '{tok}' is not allowed — it is a common "
                f"obfuscation/encoding-bypass vector for shell payloads."
            )
        # ``-c`` / ``-e`` string-eval flags on an interpreter binary.
        if base in ("-c", "-e") and idx > 0:
            prev = lowered[idx - 1].split("/")[-1]
            if prev in _EVAL_INTERPRETERS:
                return False, (
                    f"String-eval flag '{tok}' on interpreter '{prev}' is not "
                    f"allowed — it executes opaque code from a blob."
                )
        # Bare interpreter banners that are decode/exec front-ends.
        if base in _DECODE_INTERPRETER_FLAGS and base in _EVAL_INTERPRETERS:
            # ``python3 -c`` / ``perl -e`` / ``ruby -e`` forms are blocked;
            # plain ``python script.py`` is allowed (handled by _validate_segment_args).
            if idx + 1 < len(tokens) and tokens[idx + 1] in ("-c", "-e"):
                return False, (
                    f"Interpreter '{base}' with string-eval flag is not allowed "
                    f"(obfuscated payload execution)."
                )

    # Phase2.1 — whole-command regex heuristics (quote-stripped view already
    # covered by shlex; here we scan the raw string for smuggled blobs).
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
        from core.parser import _validate_path
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

    # 0. Installation-command interception (halt before any further parsing).
    # NABD OS provisions third-party deps dynamically via UvIsolationManager,
    # so shell-based installs are strictly forbidden.
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

    # 3. Handle pipes — segment after shlex, which already handles quoting
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
        # 4. Full-vector nested-shell / exfiltration sweep (applies to every segment).
        safe, reason = _scan_full_argument_vector(cmd_str)
        if not safe:
            return False, reason
        return True, "Safe piped command."

    # 4. Simple command
    ok_seg, reason = _validate_segment_args(tokens)
    if not ok_seg:
        return False, reason
    # 5. Full-vector nested-shell / exfiltration sweep.
    safe, reason = _scan_full_argument_vector(cmd_str)
    if not safe:
        return False, reason
    return True, "Safe single command."


def is_safe_command(command: str) -> bool:
    return validate(command)[0]
