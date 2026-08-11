# Changelog

All notable changes to NABD OS are documented in this file, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Am+9 hardening pass — SEC / UX / ARCH / TERM / DOC)

- **SEC-2** — AES-256-GCM encryption for API keys at rest
  (`core/config.py`): PBKDF2 key derivation from machine-id + per-user
  salt, transparent encrypt-on-save / decrypt-on-load, automatic
  migration of pre-existing plaintext keys. New
  `tests/test_config_security.py` (13 tests).
- **UX-2** — Section C in the base system prompt (`main.py`): the agent
  must summarize shell output directly instead of re-reading files after
  `execute_shell`. New `tests/test_agent_shell_behavior.py` (3 tests).
- **UX-3** — Emergency Stop: a second Ctrl+C during generation saves the
  session and exits cleanly with code 0 (no raw traceback). New
  `tests/test_emergency_stop.py` (7 tests).
- **UX-1** — `format_status_message()` in `ui/repl_termux.py`: Arabic
  status lines with step counts ("جاري التفكير... (الخطوة N)") wired into
  the thinking/tool/done event handlers. New
  `tests/test_ui_status_formatter.py` (16 tests).
- **ARCH-1** — `TfIdfIndex` versioning (`core/semantic_index.py`):
  `version` property, `serialize()`/`deserialize()` with version check,
  `needs_rebuild()` for stale indexes. New
  `tests/test_semantic_index_versioning.py` (8 tests).
- **ARCH-2** — `CodeIntelligenceTool` now parses C++ (`.cpp/.cc/.cxx/.h/.hpp`)
  and Rust (`.rs`) via tree-sitter when available, with a regex fallback
  for Termux. New `tests/test_code_parser_arch2.py` (7 tests).
- **ARCH-3** — `CircuitBreaker` (`core/agent_manager.py`): depth-limited
  recursion guard with SQLite checkpoint persistence, `rollback()`
  recovery, `resume()`, and `circuit_opened` bus events. New
  `tests/test_circuit_breaker_recovery.py` (8 tests).
- **TERM-1** — `render_arabic()` (`core/text_utils.py`): proper
  arabic-reshaper/bidi shaping when the packages are present, graceful
  bidi-isolation fallback otherwise. New
  `tests/test_termux_compatibility.py` (7 tests).
- **TERM-2** — Non-blocking Ollama availability probe (`core/llm.py`):
  2-second timeout in a daemon thread, kicked off at
  `AppContext.build()`; `ollama_available()` defaults to False until the
  probe succeeds. New `tests/test_ollama_startup.py` (8 tests).
- **DOC-1** — Rewrote `README.md` (features, install, CLI table,
  security summary) and added `SECURITY.md` (reporting policy, threat
  model, hardening checklist).
- **DOC-2** — Added this `CHANGELOG.md`.

## [2026-08-10] — UI-CC: Claude Code Style Interface

### Added
- **UI-CC-1** (d6e78a1): Pure rendering primitives in `ui/cc_style.py`
  - `badge_for_tool()` — READ/EDIT/SHELL/LIST/SEARCH/KILL badges
  - `collapse_lines()` — output truncation with `[ctrl+o to expand]` footer
  - `diff_pairs()`, `todo_line()`, `format_tokens()`, `next_status_verb()`
- **UI-CC-2** (37fb45b): Wired into TerminalVisualizer
  - Tool header lines with colored badges and primary argument preview
  - Thought completion indicators with duration
  - Status lines with animated verbs (Drafting, Conjuring, Choreographing, etc.)
- **UI-CC-3** (9eefa52): Footer hints and collapse expansion
  - `hint_for_mode()` — plan/accept/default mode hints in bottom toolbar
  - `CollapseStore` — persistent storage for collapsed output blocks
  - `/expand [id]` slash command to retrieve collapsed content
  - `ctrl+o` keybinding to expand most recent collapsed block

### Technical Notes
- All colors use `SEMANTIC` tokens (no raw hex literals)
- `ui/widgets/status_bar.py` unchanged (protected file)
- 18 new tests across 3 test files (1903 passed, 0 failed)

## [1.0.0] — 2026-07

### Added

- Initial public release of NABD OS — the first Mobile-first AI CLI Agent
  for Termux.
- BYOK config manager with chmod-0600 config file.
- Central ConsentPolicy gate for high-risk shell execution.
- Forgiving multi-strategy parser (JSON / Action / Bash / ReAct) for
  small & fallback LLMs.
- Provider router with automatic failover (Orca / OpenRouter / NVIDIA)
  and per-session state isolation.
- Local-first architecture: local model client, semantic memory
  (SQLite FTS5 + TF-IDF), workspace context injection.
