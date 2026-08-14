# Security Policy

NABD OS takes security seriously. This document describes the supported
security model, how to report a vulnerability, and the guarantees the
runtime provides.

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.x     | ✅ Yes             |
| < 1.0   | ❌ No              |

## Reporting a Vulnerability

Do **not** open a public issue for security problems. Report privately to
the maintainer (Ammar Al-Tamimi, @amiraq1) via a direct message or a
private security advisory. Include:

- A description of the vulnerability and its impact.
- Steps to reproduce (minimal PoC preferred).
- Affected versions and any proposed fix.

You can expect an acknowledgment within 3 business days and a fix plan
within 14 days.

## Security Model

NABD OS runs inside Termux (Android) as a **zero-trust** local agent.
The security model is **defense-in-depth**:

### 1. Shell Execution — Consent & Whitelist

- Every `execute_shell` call passes the central policy
  `core/kernel/security.validate()`:
  - **Allowlist**: only `SAFE_BINARIES` (ls, cat, grep, git, python3, …)
    may run. Everything else is rejected.
  - **Dangerous operators** (`;`, `&&`, `||`, `$(…)`, backticks, `|` into
    interpreters, newlines) are blocked at the syntactic level.
  - **Path jail**: path-reading binaries and scripts may only touch the
    pinned workspace root.
  - **Install interception**: `pip install`, `ensurepip`, `get-pip.py`
    are blocked and redirected to the architectural import path.
- Interactive approval via `ConsentManager` (`[Y/n]`). **Empty input is
  denied.** A timed-out or unreachable bridge fails closed.
- The DAG terminal node is **fail-closed**: without a wired consent
  callback it refuses to execute.

### 2. Secrets at Rest

- API keys in `~/.config/nabdcode/config.json` are encrypted with
  **AES-256-GCM**.
- The encryption key is derived (PBKDF2-HMAC-SHA256, 100k iterations)
  from the machine ID (`/etc/machine-id`) and a per-user random salt
  (`~/.config/nabdcode/.salt`).
- Both files are written with permissions `0600` / `0700` (owner only).
- Keys never appear in logs; shell output is redacted with
  `redact_secrets_flag=True`.

### 3. Network & LLM Clients

- All LLM API calls (OpenRouter, OrcaRouter, NVIDIA) use HTTPS only.
- Local model (Ollama) probing is **non-blocking** with a 2-second
  timeout; an absent server never stalls startup.
- Set `NABD_NONINTERACTIVE=1` in CI or automation. When a required API key
  is absent, `ConfigManager.get_or_prompt_api_key()` raises a clear error
  instead of opening a `getpass` prompt or waiting for human input.

### 4. Filesystem

- `file_system` operations are jailed to the pinned workspace root
  (`core/kernel/security._validate_path`).
- Pre-write snapshots enable `/undo`; the WAL journal records and
  reconciles applied edits.

### 5. UI / Rendering

- Chain-of-thought and intermediate reasoning are **never** printed to
  the terminal (buffered internally, expandable via Ctrl+O).
- Raw tool-call JSON is stripped from final-answer rendering.

### 6. Delegated Sub-agents

- The `task` delegation path is intentionally **read-only**. A child loop
  receives a separate runtime state and evidence log, a hard step budget,
  and a filtered tool registry.
- The child may use workspace file reads/lists, memory search, web search,
  and code intelligence. It cannot edit files, execute shell commands, or
  delegate another `task`.
- The `file_system` capability is wrapped inside the child registry and
  accepts only `read`, `read_many`, and `list`; attempted mutation actions
  fail with status `policy_denied`.

## Security Hardening Checklist

| Area | Mechanism | Location |
|------|-----------|----------|
| Shell validation | Allowlist + operator scan + path jail | `core/kernel/security.py` |
| Consent | Interactive `[Y/n]`, fail-closed | `engine/consent.py` |
| DAG shell | Fail-closed consent seam | `core/dag/nodes/terminal.py` |
| Secrets | AES-256-GCM at rest | `core/config.py` |
| File jail | Workspace pinning | `core/kernel/security.py` |
| Output redaction | Secret redaction in tool output | `core/sanitize.py`, `tools/shell.py` |
| Reasoning leak | No-op thought display | `ui/repl_termux.py` |
| Ollama boot | Async 2s probe | `core/llm.py` |
| CI key handling | `NABD_NONINTERACTIVE=1` fails fast instead of prompting | `core/config.py`, `tests/conftest.py` |
| Delegated tasks | Read-only registry + real step budget | `engine/subagent_policy.py`, `engine/subagent_runner.py` |
