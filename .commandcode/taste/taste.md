# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# evidence
See [evidence/taste.md](evidence/taste.md)
# termios
- Set `mouse_support=False` in PromptSession configurations to prevent keyboard input issues. Confidence: 0.65
- Call `renderer.flush()` before entering the main input loop to display buffered output (e.g. logo, system info). Confidence: 0.65
- Use `termios.TCSANOW` instead of `TCSADRAIN` when applying termios attribute changes during active execution. Confidence: 0.65

# architecture
- Restore terminal attributes and flush input buffer using `termios.tcflush()` inside a `finally` block, then call `renderer.flush()` after the block, not inside it. Confidence: 0.65
- Avoid alternate screen mode in the launcher script; use the standard terminal screen to preserve scrollback history and allow scrolling through conversation output. Confidence: 0.65

# rendering
- Use `textwrap.wrap()` for word-wrapping text in terminal output to avoid truncating words mid-character on word boundaries. Confidence: 0.70
- Use dedicated `think_start`/`think_pulse`/`think_end` methods with `\r`-based single-line rewriting for THINK indicators, instead of printing new lines per pulse, to prevent scrollback pollution. Confidence: 0.70

# event
- Wire `llm_request_started` to call `renderer.think_start()` and `llm_request_completed` to call `renderer.think_end()` directly, rather than using spinner_start/spinner_stop + badge_line("THINK") for cleaner think lifecycle. Confidence: 0.65

# rendering
- Render agent response text in a distinct color (soft/bright white or light gray) from user input to make the speaker distinction glanceable without banners, labels, or horizontal rules. Confidence: 0.80

# code-editing
- When adding a new constant/function/block to a file, append it at the end of the file without modifying, reordering, or touching any existing constants, blocks, or lines unless explicitly instructed to change them. Confidence: 0.75

# system-prompt
- Require tool usage: if a task needs filesystem inspection, code analysis, shell execution, or memory retrieval, the tool must be used — never infer or fabricate project names, files, architectures, test frameworks, or statistics. Confidence: 0.60
- Back factual statements with tool results, file reads, or previous verified memory; respond "I don't have sufficient evidence" when evidence is lacking. Confidence: 0.60

