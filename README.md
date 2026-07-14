# NABD OS (nabdcode)

**The first Mobile-first AI CLI Agent designed for Termux.**

NABD OS is an autonomous, local-first developer agent that turns your Android device (via Termux) into a professional coding workstation. Built with security and efficiency in mind, it allows you to execute complex AI-assisted workflows directly in your terminal.

## Features

- **Mobile-First Architecture:** Optimized for ARM64 and Termux environments.
- **BYOK (Bring Your Own Key):** Secure configuration manager; your keys never touch our code.
- **Consent Loop Security:** The agent always requests permission before executing dangerous shell commands (RCE-protected).
- **Forgiving Parser:** Designed to handle smaller, fast LLMs with high stability.
- **Local-First:** Native integration with local model runners and optimized CLI utilities.

## Installation

Requirements: `python >= 3.8`

```bash
pip install nabdcode
```

## Quick Start

1. **Initialize:**
   Run the agent for the first time:

   ```bash
   nabdcode
   ```

2. **Setup:** The agent will securely prompt you for your OpenRouter API Key (or other provider) and store it in `~/.config/nabdcode/config.json`.

3. **Run:** Start coding:

   ```bash
   nabdcode "Create a new Python project structure for a web scraper"
   ```

## Security

Your safety is a priority. NABD OS features a central ConsentPolicy. Any attempt to execute high-risk shell commands (`execute_shell`) is intercepted and requires your explicit `[Y/n]` input.

## Contributing

Built by Ammar Al-Tamimi (@amiraq1). We welcome contributions that improve mobile developer ergonomics.

*License: MIT*
