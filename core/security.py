import shlex
from typing import Tuple, List
from core.constants import SAFE_BINARIES


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
            if ch == '$' and i + 1 < n and command[i + 1] == '(':
                return False, "Command substitution $() is not allowed."

        i += 1

    return True, ""


# ── Public API ──────────────────────────────────────────────────────────────

def validate(command: str) -> Tuple[bool, str]:
    if not command or not command.strip():
        return False, "Command is empty."

    cmd_str = command.strip()

    # 1. Check for dangerous operators at the unquoted syntactic level
    safe, reason = _dangerous_operators_unquoted(cmd_str)
    if not safe:
        return False, reason

DANGEROUS_FLAGS = {"-c", "-e", "--eval", "--exec"}


def _validate_segment_args(tokens: List[str]) -> Tuple[bool, str]:
    if not tokens:
        return False, "Empty segment."
    bin_name = tokens[0]
    if bin_name not in SAFE_BINARIES:
        return False, f"Binary '{bin_name}' is not whitelisted."
    for arg in tokens[1:]:
        if arg in DANGEROUS_FLAGS:
            return False, f"Dangerous argument '{arg}' is not allowed for binary '{bin_name}'."
    return True, ""


def validate(command: str) -> Tuple[bool, str]:
    if not command or not command.strip():
        return False, "Command is empty."

    cmd_str = command.strip()

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
        for seg_tokens in segments:
            ok_seg, reason = _validate_segment_args(seg_tokens)
            if not ok_seg:
                return False, reason
        return True, "Safe piped command."

    # 4. Simple command
    ok_seg, reason = _validate_segment_args(tokens)
    if not ok_seg:
        return False, reason
    return True, "Safe single command."


def is_safe_command(command: str) -> bool:
    return validate(command)[0]
