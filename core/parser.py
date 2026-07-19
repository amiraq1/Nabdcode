# core/parser.py
"""
Tool call parsing, JSON extraction, forgiving fallback for small/fallback models.

**Phase 10 — validate_tool_call CC refactor:**
The orchestrator ``validate_tool_call`` has been decomposed into two pure
helper functions (CC ≤ 3 each) that delegate self-validation entirely to
the tool's own ``validate_and_parse`` via the ``ToolCallable`` protocol.
Tool schemas are now sourced exclusively from the live ``ToolRegistry``
(``engine.tool_registry.registry.get_all_schemas()``); no legacy fallback dict.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Optional, Tuple

from core.sanitize import sanitize
from core.utils import safe_strip

# ── Workspace root — delegated to core.kernel.security (single source of truth)
from core.kernel.security import (  # noqa: F401
    pin_workspace_root,
    get_workspace_root,
    _validate_path,
)

# ---------------------------------------------------------------------
# Regular Expressions
# ---------------------------------------------------------------------

JSON_PATTERN = re.compile(
    r"```json\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)

BASH_PATTERN = re.compile(
    r"```(?:bash|sh)?\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)

# ── Normalization ───────────────────────────────────────────────────────────

_COMMAND_MAX_LENGTH: int = 4096


def normalize(text: str) -> str:
    """
    Normalize user-facing input:
      - NFKC (Unicode homoglyph prevention)
      - Strip ANSI sequences and illegal control characters except \n, \t
    Returns the normalized string.  Non-strings are returned as-is.
    """
    if not isinstance(text, str):
        return text
    normalized = unicodedata.normalize("NFKC", text)
    return sanitize(normalized)


# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------


@dataclass(slots=True)
class ToolCall:
    tool: str
    args: dict[str, Any]
# =========================================================================
# validate_tool_call — pure structural gatekeeper (CC ≤ 3)
# =========================================================================

# --- Helper 1: Payload normalization (CC ~ 3) ---

def _parse_payload(payload: Any) -> tuple[Optional[dict], Optional[str]]:
    """Normalise *payload* (string or dict) into a parsed tool-call dict.

    Returns ``(parsed_dict, None)`` on success or ``(None, error_message)``.
    The returned dict always has keys ``"tool"`` and ``"args"``.
    """
    if isinstance(payload, str):
        try:
            obj = json.loads(sanitize(payload))
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e.msg}"
    else:
        obj = payload

    if not isinstance(obj, dict):
        return None, "Root must be a JSON object."

    if "name" in obj and "tool" not in obj:
        obj["tool"] = obj.pop("name")
    if "action" in obj and "tool" not in obj and isinstance(obj["action"], str) and obj["action"] in (
        "web_search", "execute_shell", "file_system", "search_memory", "todo_write", "termux_monitor", "browser_action", "final_answer"
    ):
        obj["tool"] = obj.pop("action")
    if "arguments" in obj and "args" not in obj:
        obj["args"] = obj.pop("arguments")
    if "parameters" in obj and "args" not in obj:
        obj["args"] = obj.pop("parameters")

    tool = obj.get("tool")
    args = obj.get("args")

    if not isinstance(tool, str):
        return None, "'tool' must be a string."
    if not isinstance(args, dict):
        return None, "'args' must be an object."

    return obj, None


# --- Helper 2: Tool-existence check (CC = 2) ---

def _validate_tool_name(tool_name: str, registry: Any) -> Tuple[bool, str]:
    """Check that *tool_name* is registered in *registry*.

    Returns ``(True, "")`` on success or ``(False, error_message)``.
    """
    if tool_name not in registry:
        return False, f"Tool '{tool_name}' is not registered in the system"
    return True, ""


# --- Helper 3: Delegate to tool's own validate_and_parse (CC = 3) ---

def _validate_tool_schema(tool: Any, args: dict) -> Tuple[bool, str]:
    """Full delegation to the tool's own Pydantic schema (100% self-validation).

    The kernel trusts every registered tool to protect its own arguments via
    ``validate_and_parse`` — no fallback, no escape hatch. Every tool inherits
    ``validate_and_parse`` from ``BaseTool`` by default (even those without a
    Pydantic ``args_schema``), so the ``hasattr`` guard is intentionally absent
    (Type-Erasure: the kernel knows nothing about tool internals).

    Returns ``(True, "")`` on success or ``(False, error_message)``.
    """
    try:
        tool.validate_and_parse(args)
        return True, ""
    except ValueError as e:
        return False, f"Schema constraint violation: {e}"


# --- 🎯 Orchestrator — pure & stateless (CC = 3) ---

def validate_tool_call(
    payload: Any,
    registry: Any,
) -> Tuple[bool, str]:
    """Pure structural gatekeeper for tool-call payloads.

    **Responsibilities:**

    1. ``_parse_payload`` — normalise string/dict, extract tool + args.
    2. ``_validate_tool_name`` — check the tool is registered.
    3. ``_validate_tool_schema`` — delegate to tool's own ``validate_and_parse``.

    **Non-responsibilities (enforced by the execution loop, not here):**

    * Security validation (path escaping, shell injection) → ``core.security``
    * Permission authorisation (allow/deny policies) → ``core.permissions``
    * Resource constraints → the tool's own Pydantic ``args_schema``

    Returns ``(True, "")`` on success or ``(False, error_message)``.
    """
    # 1. Parse + normalise
    parsed, err = _parse_payload(payload)
    if err is not None:
        return False, err

    tool_name: str = parsed["tool"]
    args: dict = parsed["args"]

    # 2. Check tool exists in registry
    name_ok, name_err = _validate_tool_name(tool_name, registry)
    if not name_ok:
        return False, name_err

    # 3. Get tool and delegate schema validation entirely to validate_and_parse
    tool = registry.get_tool(tool_name)
    schema_ok, schema_err = _validate_tool_schema(tool, args)
    if not schema_ok:
        return False, schema_err

    return True, ""


# ---------------------------------------------------------------------
# Internal validators (used by extract_command pipeline)
# ---------------------------------------------------------------------


def _validate_payload(payload: dict, registry: Any) -> ToolCall | None:
    """Validate a *payload* dict and return a ``ToolCall`` or ``None``."""
    ok, err = validate_tool_call(payload, registry)
    if not ok:
        return None
    return ToolCall(tool=payload["tool"], args=payload.get("args", {}))


# ---------------------------------------------------------------------
# JSON Strategy
# ---------------------------------------------------------------------


def _parse_json(text: str, registry: Any) -> ToolCall | None:
    match = JSON_PATTERN.search(text)
    if not match:
        return None
    try:
        inner = sanitize(match.group(1), strip_control=True)
        payload = json.loads(inner)
    except json.JSONDecodeError:
        return None
    return _validate_payload(payload, registry)


# ---------------------------------------------------------------------
# Action: {JSON} Strategy (Simulated ReAct / Hallucination Interception)
# ---------------------------------------------------------------------

_ACTION_JSON_RE = re.compile(r"Action\s*:\s*(\{.*?\})", re.DOTALL | re.IGNORECASE)
_ACTION_FENCE_RE = re.compile(r"Action\s*:\s*```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _parse_action_json(text: str, registry: Any) -> ToolCall | None:
    """Catch simulated ReAct loops where the model outputs Action: {JSON} followed by hallucinated Observation:.
    Extracts the JSON payload right after 'Action:' and dispatches it immediately, cutting off any fake observation chain.
    """
    m_fence = _ACTION_FENCE_RE.search(text)
    if m_fence:
        candidate = safe_strip(m_fence.group(1))
        try:
            payload = json.loads(candidate)
            res = _validate_payload(payload, registry)
            if res is not None:
                return res
        except json.JSONDecodeError:
            pass

    pos = re.search(r"Action\s*:\s*", text, re.IGNORECASE)
    if pos:
        sub = text[pos.end():]
        candidate = extract_first_json_object(sub)
        if candidate:
            try:
                payload = json.loads(candidate)
                res = _validate_payload(payload, registry)
                if res is not None:
                    return res
            except json.JSONDecodeError:
                pass

        m = _ACTION_JSON_RE.search(text)
        if m:
            try:
                payload = json.loads(m.group(1))
                res = _validate_payload(payload, registry)
                if res is not None:
                    return res
            except json.JSONDecodeError:
                pass

    return None


# ---------------------------------------------------------------------
# Bash Strategy
# ---------------------------------------------------------------------

TOOL_NAMES_IN_CODE: Final[tuple[str, ...]] = (
    "todo_write", "file_system", "evidence_log", "shell", "execute_shell",
)


def _is_hallucinated_python_tool_call(cmd: str) -> bool:
    c = safe_strip(cmd)
    if not c.startswith("python "):
        return False
    if "import " in c and "(" in c and ")" in c:
        return True
    if any(f" {t}(" in c or f" {t}." in c or c.startswith(f"python {t}.") for t in TOOL_NAMES_IN_CODE):
        return True
    return False


def _parse_bash(text: str, registry: Any) -> ToolCall | None:
    match = BASH_PATTERN.search(text)
    if not match:
        return None
    candidate = safe_strip(match.group(1))
    if not candidate or _is_hallucinated_python_tool_call(candidate):
        return None
    payload = {"tool": "execute_shell", "args": {"command": candidate}}
    ok, err = validate_tool_call(payload, registry)
    if not ok:
        return None
    return ToolCall(tool="execute_shell", args={"command": candidate})


# ---------------------------------------------------------------------
# Forgiving parser
# ---------------------------------------------------------------------

_FORGIVING_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_LEGACY_SHELL_PATTERN = re.compile(
    r"""(?:shell|execute_shell)\s*\(\s*(?:cmd|command)\s*=\s*["'](.+?)["']\s*\)""",
    re.IGNORECASE | re.DOTALL,
)


def extract_first_json_object(text: str) -> str | None:
    if not text:
        return None
    m = _FORGIVING_JSON_FENCE.search(text)
    if m:
        return safe_strip(m.group(1))
    start = text.find("{")
    while start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    if '"tool"' in candidate or "'tool'" in candidate or '"name"' in candidate or "'name'" in candidate or '"action"' in candidate or "'action'" in candidate:
                        return candidate
                    break
        start = text.find("{", start + 1)
    return None


def extract_legacy_shell(text: str) -> dict[str, Any] | None:
    m = _LEGACY_SHELL_PATTERN.search(text)
    if not m:
        return None
    return {"tool": "execute_shell", "args": {"command": safe_strip(m.group(1))}}


def _forgiving_json_tool_call(text: str, registry: Any) -> ToolCall | None:
    raw = extract_first_json_object(text)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _validate_payload(payload, registry)


def _forgiving_legacy_shell(text: str, registry: Any) -> ToolCall | None:
    payload = extract_legacy_shell(text)
    if not payload:
        return None
    return _validate_payload(payload, registry)


# ---------------------------------------------------------------------
# ReAct-style fallback (loose, model-tolerant)
# ---------------------------------------------------------------------

# Catches small/fallback models (e.g. Llama-3.1) that emit ReAct-style
# actions like `SEARCH "python 3.12 feature"` or `FINAL_ANSWER "..."`
# instead of the canonical JSON tool call. These would otherwise fail every
# parser strategy and spin the model into a frustration loop. Accept optional
# brackets / quotes / whitespace around the argument.

_REACT_SEARCH_RE = re.compile(
    r"""
    \bSEARCH\b\s*
    \[?
    ['"]?
    \s*
    (.+?)
    (?=\s*['"]?\s*\]?$)
    """,
    re.VERBOSE | re.IGNORECASE,
)

_REACT_FINAL_RE = re.compile(
    r"""
    (?:FINAL_ANSWER|FINAL\s*ANSWER|Final\s*Answer)\b\s*
    \[?
    ['"]?
    \s*
    (.+?)
    (?=\s*['"]?\s*\]?$)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Bare "Final Answer: <text>" prose form (no brackets/quotes).
_REACT_FINAL_PROSE_RE = re.compile(
    r"""
    (?:FINAL_ANSWER|FINAL\s*ANSWER|Final\s*Answer)\s*:\s*
    (.+)
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _parse_react_style(text: str, registry: Any) -> ToolCall | None:
    """Last-resort parser for loose ReAct-style model output.

    Converts ``SEARCH "query"`` → web_search tool call, and
    ``FINAL_ANSWER "text"`` / ``Final Answer: text`` → final_answer termination.
    Returns ``None`` when no recognizable action is present.

    Note: ``final_answer`` is a termination convention, NOT a registered tool,
    so we return the ToolCall directly (bypassing ``_validate_payload`` which
    would reject it as an unknown tool and loop forever). ``web_search`` still
    goes through validation so malformed queries are rejected cleanly.
    """
    # Try the explicit "Final Answer: <text>" prose form first (most precise),
    # then the bracketed/quoted FINAL_ANSWER form, so the colon is consumed
    # correctly rather than leaking into the captured answer.
    final_match = _REACT_FINAL_PROSE_RE.search(text) or _REACT_FINAL_RE.search(text)
    if final_match:
        answer = safe_strip(final_match.group(1))
        if answer:
            return ToolCall(tool="final_answer", args={"answer": answer})

    search_match = _REACT_SEARCH_RE.search(text)
    if search_match:
        query = safe_strip(search_match.group(1))
        if query:
            payload = {"tool": "web_search", "args": {"query": query}}
            return _validate_payload(payload, registry)

    return None


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def extract_json_from_response(text: str) -> str | None:
    """Extract a JSON object from an LLM response, tolerating prose prefixes.

    Priority:
      1. ```json fenced block (canonical)
      2. First balanced ``{...}`` object found anywhere in the text (forgiving)
      3. Whole-string ``{...}`` (legacy)
    """
    if not text or not safe_strip(text):
        return None
    text = normalize(str(text))

    # 1. Fenced ```json block
    match = JSON_PATTERN.search(text)
    if match:
        return safe_strip(match.group(1))

    # 1b. OpenAI function-calling payload ({"tool_call":{"function":{"name":..,"arguments":..}}}).
    #     Must run before the generic JSON extractor (#2) because the whole
    #     text is valid JSON keyed by "tool_call", not the canonical "tool".
    try:
        from core.xml_tool_parser import openai_fc_to_json

        _fc = openai_fc_to_json(text)
        if _fc is not None:
            return _fc
    except Exception:
        pass

    # 2. Forgiving: find first balanced {...} object anywhere in prose
    balanced = _extract_first_json_object(text)
    if balanced is not None:
        return balanced

    # 3. Legacy whole-string object
    text_stripped = safe_strip(text)
    if text_stripped.startswith("{") and text_stripped.endswith("}"):
        return text_stripped

    # 4. XML-style tool call (e.g. <execute_shell><command>ls</command></execute_shell>),
    #    emitted by some fallback models. Convert the first recognized tag to
    #    canonical JSON so the rest of the pipeline (validation / final_answer)
    #    works unchanged.
    try:
        from core.xml_tool_parser import xml_tool_to_json

        _xml = xml_tool_to_json(text)
        if _xml is not None:
            return _xml
    except Exception:
        pass

    # 4b. OpenAI function-calling payload ({"tool_call":{"function":{"name":..,"arguments":..}}}).
    try:
        from core.xml_tool_parser import openai_fc_to_json

        _fc = openai_fc_to_json(text)
        if _fc is not None:
            return _fc
    except Exception:
        pass

    # 4c. Anthropic <function>/<invoke> wrapper with <parameter name="k">v</parameter>.
    try:
        from core.xml_tool_parser import function_xml_to_json

        _fx = function_xml_to_json(text)
        if _fx is not None:
            return _fx
    except Exception:
        pass

    return None


def _extract_first_json_object(text: str) -> str | None:
    """Return the first balanced JSON object substring starting at '{'.

    Handles braces nested inside string literals by tracking quotes. Returns
    ``None`` when no balanced object is found (e.g. unclosed brace).
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract_command(text: str, registry: Any = None) -> ToolCall | None:
    """Parse an LLM response and extract a tool call.

    Priority:
        1. JSON Tool Call (clean ```json fence)
        2. Bash Code Block (with hallucinated Python guard)
        3. Forgiving JSON scan (tool call buried in prose)
        4. Forgiving legacy-shell scan (shell(cmd=...))
        5. None

    *registry* defaults to the global ``engine.tool_registry.registry`` singleton
    when not provided (backward-compatible).
    """
    if not text or not safe_strip(text):
        return None
    text = normalize(str(text))

    if registry is None:
        from engine.tool_registry import registry as _reg
        registry = _reg

    result = _parse_json(text, registry)
    if result is not None:
        return result
    result = _parse_action_json(text, registry)
    if result is not None:
        return result
    result = _parse_bash(text, registry)
    if result is not None:
        return result
    result = _forgiving_json_tool_call(text, registry)
    if result is not None:
        return result
    result = _forgiving_legacy_shell(text, registry)
    if result is not None:
        return result
    # Last resort: loose ReAct-style output (SEARCH / FINAL_ANSWER) emitted by
    # small/fallback models that deviate from the canonical JSON tool call.
    return _parse_react_style(text, registry)
