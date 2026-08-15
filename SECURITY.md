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

- The `task` delegation path is role-based and **closed-world**. A child loop
  receives a separate runtime state and evidence log, a hard step budget, and a
  filtered tool registry. Adding a tool to the global registry never grants it
  to a delegated role.
- `research` is the default role and can use only workspace reads/lists,
  memory search, web search, and code intelligence. `review` has the same
  read-only surface and is intended for risk, diff, and test assessment.
- `implement` is the only delegated role with access to `file_system`,
  `execute_shell`, and `todo_write`, plus read-oriented analysis tools. It
  cannot invoke `task` itself, and every mutation remains subject to the
  normal Dispatcher consent and Plan/Apply gates; the role is not an approval
  bypass.
- Unknown role names are rejected before a child loop starts. For `research`
  and `review`, the `file_system` capability is wrapped inside the child
  registry and accepts only `read`, `read_many`, and `list`; attempted mutation
  actions fail with status `policy_denied`.

### 7. Explicit Plan/Apply Workflow

- Run `/plan` to enter a runtime-enforced, read-only review phase. The agent
  can explore the workspace and create `todo_write(action='plan')`, but cannot
  execute shell commands, edit files, delegate work, or invoke unknown tools.
- A successful TODO plan becomes an auditable numbered revision in
  `RuntimeState.plan_audit`. Recording a new plan invalidates any previous
  Apply authorization.
- Run `/apply` only after reviewing the recorded plan. It approves the current
  revision exactly; normal consent and per-edit approval gates still apply to
  every sensitive action.
- Run `/mode` or `/plan status` to inspect the active mode and plan revision;
  run `/plan off` to leave the explicit workflow without deleting the record.

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
| Plan/Apply | Runtime allowlist in Plan; revision-bound Apply authorization | `core/plan_apply.py`, `engine/_dispatch.py` |
| Delegated tasks | Role allowlists, read-only defaults, no nested delegation, real step budget | `engine/subagent_policy.py`, `engine/subagent_runner.py`, `tools/task_tool.py` |

### 8. Task Graph Integrity

- Task Graph is a dependency/state model, not an execution-permission surface.
  It accepts only the explicit roles `research`, `review`, and `implement`.
- Duplicate IDs, missing dependencies, self-dependencies, cycles, unknown roles,
  and stale plan revisions are rejected before a graph mutation is committed.
- A task becomes `ready` only after every dependency is `completed`. A failed
  task recursively blocks its dependents; no dependent task is retried or run
  implicitly.
- A task cannot become `completed` without at least one evidence ID. Every state
  transition records the task, revision, reason, and evidence IDs.
- Recording a new Plan/Apply revision replaces the prior graph and revokes all
  prior execution authorization. The graph never bypasses consent or review.

| Task Graph control | Enforcement | Location |
|---|---|---|
| Dependency and cycle validation | Closed-world graph mutations | `core/task_graph.py` |
| Revision binding | New plan creates a new graph | `core/plan_apply.py`, `core/kernel/state.py` |
| Evidence-bound completion | Completion requires evidence IDs | `core/task_graph.py` |
| Failure containment | Failed nodes block dependents | `core/task_graph.py` |

### 9. Pre-Apply Diff and Test Review

- Run `/review` to inspect the current plan revision, affected pending-edit paths, addition/removal counts, redacted diff previews, and a conservative risk level.
- Run `/review run` to execute only repository-local pytest files selected from affected paths. The runner uses `python -m pytest`, never a shell string or a model-supplied command, and sets `NABD_NONINTERACTIVE=1`.
- Run `/review approve` only after inspecting the report. Apply authorization is bound to the exact plan revision and requires passing selected tests, or an explicit `not_applicable` result when no affected-file test exists.
- Recording a new TODO plan invalidates the review and requires a new `/review run` and `/review approve` cycle.
- `/mode` exposes `review`, `review_approved`, and `apply_authorized` fields. Diff previews redact values resembling API keys, tokens, passwords, secrets, or authorization headers.

| Review gate | Enforcement | Location |
|---|---|---|
| Diff/test review before Apply | Revision-bound approval and test status | `core/diff_review.py`, `core/plan_apply.py` |
| Central tool enforcement | Reject Apply without current review | `engine/_dispatch.py` |
| Operator commands | `/review`, `/review run`, `/review approve` | `core/command_dispatcher.py` |
