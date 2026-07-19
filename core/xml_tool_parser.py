"""Convert XML-style tool calls (emitted by deepseek/OrcaRouter) to canonical JSON."""
from __future__ import annotations

import json
import re

_XML_TOOL_NAMES = (
    "execute_shell", "shell", "file_system", "web_search", "search_memory",
    "todo_write", "browser_action", "termux_monitor", "evidence_log", "final_answer",
)
_XML_PRIMARY_ARG = {
    "execute_shell": "command", "shell": "command", "web_search": "query",
    "search_memory": "query", "final_answer": "answer", "file_system": "path",
}
_OPEN_TAG_ATTR_RE = re.compile(r'([A-Za-z_][\w\-]*)\s*=\s*"([^"]*)"')
_SUBTAG_RE = re.compile(r"<([a-zA-Z_][\w\-]*)\s*>(.*?)</\1>", re.DOTALL)


def xml_tool_to_json(text: str) -> str | None:
    """Return canonical JSON for the first recognized XML tool tag, else None.

    Captures (1) attributes on the opening tag, (2) child subtags, and
    (3) bare inner text — so models that emit <tool attr="v"/> or
    <tool><sub>v</sub></tool> or bare text all normalize to the same shape.
    """
    if not text or "<" not in text:
        return None
    for tool in _XML_TOOL_NAMES:
        m = re.search(r"<%s\b([^>]*)>(.*?)</%s>" % (tool, tool), text, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        attr_str, inner = m.group(1) or "", m.group(2).strip()
        args: dict[str, str] = {}
        for k, v in _OPEN_TAG_ATTR_RE.findall(attr_str):  # (1) tag attributes
            args[k] = v
        for sm in _SUBTAG_RE.finditer(inner):  # (2) child subtags
            args[sm.group(1).strip().lower()] = sm.group(2).strip()
        if not args:  # (3) bare text
            bare = re.sub(r"<[^>]+>", "", inner).strip()
            if bare:
                args[_XML_PRIMARY_ARG.get(tool.lower(), "input")] = bare
        canonical = "execute_shell" if tool.lower() == "shell" else tool.lower()
        return json.dumps({"tool": canonical, "args": args}, ensure_ascii=False)
    return None


# ── OpenAI-style function-calling (raw tool_call.function.name / .arguments) ──
_OPENAI_FC_RE = re.compile(r'"tool_call"\s*:\s*\{', re.DOTALL)


def openai_fc_to_json(text: str) -> str | None:
    """Convert OpenAI function-calling payload to canonical tool JSON.

    Handles both:
      {"tool_call":{"function":{"name":"X","arguments":{...}}}}
      {"tool_call":{"function":{"name":"X","arguments":"{...json string...}"}}}
    """
    if not text or '"tool_call"' not in text:
        return None
    try:
        payload = json.loads(text) if text.strip().startswith("{") else None
    except (json.JSONDecodeError, TypeError):
        payload = None
    if payload is None:
        # Try to extract the tool_call object from a larger response.
        m = _OPENAI_FC_RE.search(text)
        if not m:
            return None
        start = m.start()
        # Find the matching closing brace by depth scan.
        depth = 0
        end = None
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            return None
        try:
            payload = json.loads(text[start:end])
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(payload, dict):
        return None
    tc = payload.get("tool_call")
    if not isinstance(tc, dict):
        return None
    fn = tc.get("function")
    if not isinstance(fn, dict):
        return None
    tool = fn.get("name")
    if not isinstance(tool, str):
        return None
    raw_args = fn.get("arguments", {})
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            args = {"input": raw_args}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    canonical = "execute_shell" if tool.lower() == "shell" else tool.lower()
    return json.dumps({"tool": canonical, "args": args}, ensure_ascii=False)


# ── Anthropic-style <function>/<invoke> function calls ──────────────────────
_FUNC_WRAPPER_RE = re.compile(
    r"<(?:function|invoke)\b[^>]*>(.*?)</(?:function|invoke)>", re.DOTALL | re.IGNORECASE
)
_FUNC_NAME_TAG_RE = re.compile(
    r"<(?:task|name|tool_name)\b[^>]*>(.*?)</(?:task|name|tool_name)>",
    re.DOTALL | re.IGNORECASE,
)
# Tolerant of stray pseudo-attributes like name="action" string="true":
_PARAM_RE = re.compile(
    r"<parameter\b[^>]*\bname\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</parameter>",
    re.DOTALL | re.IGNORECASE,
)


def function_xml_to_json(text: str) -> str | None:
    """Convert <function><task>TOOL</task><parameter name=k>v</parameter></function> to JSON."""
    if not text or "<" not in text:
        return None
    m = _FUNC_WRAPPER_RE.search(text)
    if not m:
        return None
    inner = m.group(1)
    tool = None
    tm = _FUNC_NAME_TAG_RE.search(inner)
    if tm:
        tool = tm.group(1).strip()
    if not tool:
        am = re.search(
            r"<(?:function|invoke)\b[^>]*\bname\s*=\s*[\"']([^\"']+)[\"']",
            text,
            re.IGNORECASE,
        )
        if am:
            tool = am.group(1).strip()
    if not tool:
        return None
    args: dict[str, str] = {}
    for pm in _PARAM_RE.finditer(inner):
        args[pm.group(1).strip()] = pm.group(2).strip()
    if not args:
        for sm in _SUBTAG_RE.finditer(inner):
            k = sm.group(1).strip().lower()
            if k in ("task", "name", "tool_name"):
                continue
            args[k] = sm.group(2).strip()
    canonical = "execute_shell" if tool.lower() == "shell" else tool.lower()
    return json.dumps({"tool": canonical, "args": args}, ensure_ascii=False)
