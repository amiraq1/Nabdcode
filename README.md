# NABD OS (nabdcode)

**The first Mobile-first AI CLI Agent designed for Termux.**

NABD OS is an autonomous, local-first developer agent that turns your Android device (via Termux) into a professional coding workstation. Built with security and efficiency in mind, it allows you to execute complex AI-assisted workflows directly in your terminal.

## Features

- **Mobile-First Architecture:** Optimized for ARM64 and Termux environments.
- **BYOK (Bring Your Own Key):** API keys are encrypted at rest with **AES-256-GCM** (key derived from the machine ID + a per-user salt); keys never touch our code.
- **Consent Loop Security:** The agent always requests permission before executing dangerous shell commands (RCE-protected). The shell executor is fail-closed: no execution without a wired consent callback.
- **Forgiving Parser:** Designed to handle smaller, fast LLMs with high stability.
- **Local-First:** Native integration with local model runners (Ollama, non-blocking 2s probe) and optimized CLI utilities.
- **Arabic-aware UI:** Status messages localized in Arabic; graceful fallback when `arabic-reshaper`/`python-bidi` are unavailable (Termux).

## Installation

Requirements: `python >= 3.8`, a Termux environment (`PREFIX` set).

```bash
pkg install python
pip install nabdcode
```

Optional (better Arabic rendering on desktop Linux only):

```bash
pkg install fribidi   # Termux
pip install arabic-reshaper python-bidi
```

## Quick Start

1. **Initialize:**
   Run the agent for the first time:

   ```bash
   nabdcode
   ```

2. **Setup:** The agent will securely prompt you for your OpenRouter API Key (or other provider). The key is stored **encrypted** in `~/.config/nabdcode/config.json` (permissions `0600`).

3. **Run:** Start coding:

   ```bash
   nabdcode "Create a new Python project structure for a web scraper"
   ```

## CLI Commands

| Command | Description |
|---------|-------------|
| `nabdcode` | Interactive REPL |
| `nabdcode "query"` | One-shot query |
| `/clear` | Reset context & history |
| `/undo <file>` | Revert a file to its pre-edit snapshot |
| `/fix <file> → <function>` | Show & test a function |
| `/refactor <files...>` | DAG-based refactor pipeline |
| `/resume` | Resume an interrupted DAG pipeline |

## Security

Your safety is a priority. NABD OS implements a **defense-in-depth** security model — see [SECURITY.md](SECURITY.md) for the full threat model and policy.

Highlights:

- **Central ConsentPolicy**: any attempt to execute high-risk shell commands (`execute_shell`) is intercepted and requires your explicit `[Y/n]` input. Empty input is denied.
- **Fail-closed DAG terminal**: the DAG shell node refuses to execute when no consent callback is wired.
- **AES-256-GCM key encryption at rest** with per-user salt (`~/.config/nabdcode/.salt`, `0600`).
- **Whitelisted binaries**: only an allowlist of safe commands may run; `curl`, `wget`, `nc`, `base64`, nested shells, and install commands are blocked.
- **Workspace jail**: file access and script execution are pinned to the workspace root.

## Contributing

Built by Ammar Al-Tamimi (@amiraq1). We welcome contributions that improve mobile developer ergonomics.

*License: MIT*
