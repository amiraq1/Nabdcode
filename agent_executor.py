import re
import subprocess
import shlex
import os
from pathlib import Path
from llm_router import execute_agent_with_memory, CYAN, PURPLE, RED, RESET

YELLOW = "\033[93m"
GREEN = "\033[92m"

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
if not SKILLS_DIR.exists():
    SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

SAFE_BINARIES = {
    "ls", "pwd", "echo", "whoami", "cat", "grep", "date", 
    "ps", "uptime", "df", "free", "history", "clear", "find", "wc",
    "du", "sort", "head", "tail", "awk", "top",
    "termux-battery-status", "termux-telephony-deviceinfo",
    "git", "xargs"
}
def extract_bash_command(text: str) -> str:
    match = re.search(r"```bash\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match_fallback = re.search(r"```\n(.*?)```", text, re.DOTALL)
    if match_fallback:
        return match_fallback.group(1).strip()
    return ""

def is_safe_command(command: str) -> bool:
    """
    Evaluates command safety. Allows pipes '|' ONLY if all commands in the chain are whitelisted.
    """
    # 1. Strictly forbid redirection and background/chaining operators
    DANGEROUS_STRICT = {">", ">>", "&", ";"}
    for op in DANGEROUS_STRICT:
        if op in command:
            return False

    # 2. Handle piped commands securely
    if "|" in command:
        piped_segments = command.split("|")
        for segment in piped_segments:
            try:
                parts = shlex.split(segment.strip())
                if not parts or parts[0] not in SAFE_BINARIES:
                    return False
            except ValueError:
                return False
        return True

    # 3. Handle standard single commands
    try:
        parts = shlex.split(command)
        if not parts:
            return False
        return parts[0] in SAFE_BINARIES
    except ValueError:
        return False

def truncate_output(output: str, max_lines: int = 50) -> str:
    lines = output.split("\n")
    if len(lines) <= max_lines:
        return output
    truncated = lines[:max_lines]
    truncated.append(f"\n... (truncated {len(lines) - max_lines} lines)")
    return "\n".join(truncated)

def execute_in_terminal(command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return truncate_output(result.stdout.strip())
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return f"[ERROR] Return Code: {result.returncode}\n{error_msg}"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT] Command took too long to execute."
    except Exception as e:
        return f"[SYSTEM ERROR] {str(e)}"

def load_skill(skill_name: str) -> str:
    skill_file = SKILLS_DIR / f"{skill_name}.md"
    if not skill_file.exists():
        return None
    return skill_file.read_text().strip()

def run_agent_loop():
    print(f"{YELLOW}[DEPRECATION WARNING] agent_executor.py is deprecated. Use `python main.py` instead.{RESET}")
    print(f"{YELLOW}This entry point will be removed in a future version.{RESET}\n")
    
    system_instruction = (
        "You are an expert CLI assistant running in a Linux/Termux environment. "
        "When asked to perform a task, output ONLY the exact bash command needed inside a ```bash block. "
        "Do not provide explanations unless explicitly asked."
    )
    
    # Base conversation messages (memory)
    conversation_messages = [{"role": "system", "content": system_instruction}]
    active_skill = None
    
    print(f"{GREEN}[AGENT STARTED] Ready to execute commands.{RESET}")
    print(f"{YELLOW}Commands: /skill <name> to load a skill, /clear to reset memory, /status to show active skill.{RESET}")
    
    while True:
        user_input = input(f"\n{CYAN}Ammar's Agent:> {RESET}")
        if user_input.lower() in ['exit', 'quit']:
            print(f"{PURPLE}Shutting down...{RESET}")
            break

        # --- Commands: /skill, /clear, /status ---
        if user_input.startswith("/"):
            parts = user_input.strip().split(maxsplit=1)
            cmd = parts[0].lower()

            if cmd == "/status":
                if active_skill:
                    print(f"{GREEN}[SKILL] Active: {active_skill}{RESET}")
                else:
                    print(f"{YELLOW}[SKILL] No active skill. Default system prompt in use.{RESET}")
                continue

            if cmd == "/clear":
                conversation_messages = [{"role": "system", "content": system_instruction}]
                active_skill = None
                print(f"{GREEN}[MEMORY] Conversation reset.{RESET}")
                continue

            if cmd == "/skill":
                if len(parts) < 2:
                    available = [f.stem for f in SKILLS_DIR.glob("*.md")]
                    print(f"{YELLOW}Available skills: {', '.join(available) if available else '(none)'}{RESET}")
                    continue
                skill_name = parts[1].strip().lower()
                skill_content = load_skill(skill_name)
                if skill_content is None:
                    print(f"{RED}[SKILL] '{skill_name}' not found in skills/{RESET}")
                    continue
                # Load skill: reset memory and inject skill as system prompt
                conversation_messages = [{"role": "system", "content": skill_content}]
                active_skill = skill_name
                print(f"{GREEN}[SKILL] Loaded '{skill_name}'. Memory reset for fresh context.{RESET}")
                continue

        # Append user message to memory
        conversation_messages.append({"role": "user", "content": user_input})
        
        # Send full context through the router
        try:
            llm_response = execute_agent_with_memory(conversation_messages)
        except Exception as err:
            print(f"{RED}[ERROR] Execution halted: {err}{RESET}")
            if conversation_messages and conversation_messages[-1].get("role") == "user":
                conversation_messages.pop()
            continue
        
        # Save AI response to memory
        conversation_messages.append({"role": "assistant", "content": llm_response})
        
        command_to_run = extract_bash_command(llm_response)
        
        if command_to_run:
            print(f"\n{PURPLE}Agent suggests:{RESET} {command_to_run}")
            
            if is_safe_command(command_to_run):
                print(f"{GREEN}[AUTO-EXECUTING SAFE COMMAND]{RESET}")
                output = execute_in_terminal(command_to_run)
                if output:
                    print(f"{CYAN}--- Output ---{RESET}\n{output}")
                    # Feed output back to memory (System Feedback)
                    conversation_messages.append({
                        "role": "system",
                        "content": f"Command executed successfully. Output:\n{output}"
                    })
            else:
                confirm = input(f"{YELLOW}Command requires privileges or modifies files. Execute? (y/n): {RESET}").strip().lower()
                if confirm == 'y':
                    output = execute_in_terminal(command_to_run)
                    if output:
                        print(f"{CYAN}--- Output ---{RESET}\n{output}")
                        conversation_messages.append({
                            "role": "system",
                            "content": f"Command executed successfully. Output:\n{output}"
                        })
                else:
                    print(f"{RED}[CANCELLED] User aborted execution.{RESET}")
        else:
            print(f"\n{CYAN}--- Agent Reply ---{RESET}\n{llm_response}")

if __name__ == "__main__":
    run_agent_loop()
