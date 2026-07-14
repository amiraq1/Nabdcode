import sys
from rich.console import Console
from rich.markup import escape as _rich_escape
from core.sanitize import sanitize

# Centralized Rich console — deprecates raw sys.stdout for UI rendering.
console = Console()

# تعريف الألوان البصرية الحصيرة من صورك (Rich markup)
BG_PURPLE = "[on #3d3d5c #ffffff]"
BG_BLUE = "[on #1a1a42 #ffffff]"
BG_GREEN = "[on #1c4700 #ffffff]"
BG_MAGENTA = "[on #7f1f7f #ffffff]"
RESET = "[/]"
DIM_GRAY = "[#9a9a9a]"
CYAN = "[#00ffff]"
GREEN_TEXT = "[#00ff00]"
RED_BG = "[on #580000 #ffffff]"
GREEN_BG = "[on #164400 #ffffff]"

def print_badge(badge_text, info_text):
    """يطبع الرايات المصمتة مثل READ و EDIT حرفياً كما في الصور"""
    # The dynamic info is wrapped in literal [] brackets to mirror the UI mock.
    # Under Rich markup, those brackets (and any [] inside info_text) are parsed
    # as tags and stripped — so escape the entire wrapped span. The color tags
    # (BG_PURPLE/DIM_GRAY/RESET) are real Rich markup and must remain unescaped.
    info_escaped = _rich_escape(str(info_text))
    wrapped = _rich_escape(f"[{info_escaped}]")
    # Render to whatever stdout is currently bound (so tests that patch
    # sys.stdout capture the output; the console file tracks sys.stdout live).
    console.file = sys.stdout
    if badge_text in ["READ", "TODOS"]:
        console.print(f"{BG_PURPLE} {badge_text} {RESET} {DIM_GRAY}{wrapped}{RESET}")
    elif badge_text == "DELEGATE":
        # New visual logic for Multi-Agent handoff
        info_escaped2 = _rich_escape(str(info_text))
        console.print(f"{BG_MAGENTA} {badge_text} {RESET} {info_escaped2}")
    else:
        info_escaped3 = _rich_escape(str(info_text))
        console.print(f"{BG_BLUE} {badge_text} {RESET} {info_escaped3}")

def print_thought(seconds=1):
    """كتل التفكير الخافتة القابلة للتوسيع"""
    console.file = sys.stdout
    console.print(f"{DIM_GRAY}* Thought for {seconds} second {_rich_escape('[ctrl+o to expand]')}{RESET}")

def print_status_bar(status_text, tokens="24.2k"):
    """شريط الحالة السفلي اللحظي قبل خانة الإدخال"""
    console.file = sys.stdout
    console.print(f"\n{BG_PURPLE} • {status_text}... {RESET} {DIM_GRAY}{tokens}{RESET}")
    console.print(f"{DIM_GRAY}{'─' * 56}{RESET}")

def render_mock_execution(task):
    """محاكاة بصرية جراحية مطابقة تماماً للصور المرفقة"""
    print_status_bar("Contemplating", "47.1k")
    print_thought(1)
    print_badge("DELEGATE", "Manager handing off task to Executor...")
    console.print(f"{DIM_GRAY}:: Let me verify Python syntax is clean across all modified files.{RESET}")

    # راية التشييد والقراءة
    print_badge("READ", "engine/state.py")
    console.print(f"   {GREEN_TEXT}OK{RESET} main.py")
    console.print(f"   {GREEN_TEXT}OK{RESET} engine/state.py")

    print_thought(1)

    # عرض الـ TODOS المشطوبة والجاهزة كما في الصورة الثالثة ورقم 4
    print_badge("TODOS", "10 items")
    console.print(f" {DIM_GRAY}[x] Step 1: Remove hardcoded API key from core/llm.py (Done){RESET}")
    console.print(f" [ ] Step 2: Add token-aware context pruning to state.py")

    print_thought(1)

    # محاكاة لكتلة تعديل الكود الجراحي (EDIT Block) باللون الأحمر والأخضر
    print_badge("EDIT", "[engine/state.py]")
    console.print(f"{RED_BG}- # Maximum conversation message kept in context.{RESET}")
    console.print(f"{GREEN_BG}+ # Maximum context size in estimated tokens.{RESET}")
    console.print(f"{CYAN}  + # Uses a simple heuristic: ~4 chars per token.{RESET}")

    print_badge("DELEGATE", "Executor returning execution results to Manager...")
    print_status_bar("Resolving", "6.4k")

def launch_stream_tui(agent_runner_func=None, mode: str = "repl"):
    """الواجهة الحية التفاعلية.

    تعتمد على وضع الـ REPL المتسلسل المخصص لـ Termux (ui/repl_termux.py)،
    مع تراجع آمن إلى حلقة ANSI العادية.
    """
    if mode in ("repl", "auto") or "--repl" in sys.argv:
        try:
            import asyncio
            import importlib
            repl_mod = importlib.import_module("ui.repl_termux")
            asyncio.run(repl_mod.run_repl(agent=None, agent_runner_func=agent_runner_func))
            return
        except Exception:
            pass

    console.print("\033c", end="")  # Hard ANSI reset — consistent Termux clear
    console.print("🤖 Nabd Agent OS — Powered by Secure smolagents Engine")
    console.print("Status: Workspace Clean | Protection: Zero Trust Active")
    console.print()

    while True:
        try:
            raw_task = input("❯ Ask your question... \n? for shortcuts\n\n❯ ")
            task = sanitize(raw_task[:10000])
            if task.strip().lower() in ["exit", "quit"]:
                break

            console.print(f"\n{DIM_GRAY}[Executing Surgical Task...]{RESET}")

            if agent_runner_func:
                print_status_bar("Contemplating", "47.1k")
                print_badge("DELEGATE", "Manager handing off task to Executor...")
                result = agent_runner_func(task)
                print_badge(
                    "DELEGATE",
                    "Executor returning execution results to Manager...",
                )
                console.print(f"\n🏆 Final Result:\n{result}\n")
            else:
                render_mock_execution(task)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting Nabd Agent OS Cleanly.")
            break


def main():
    import argparse

    parser = argparse.ArgumentParser(description="NABD - Zero-Trust AI Code Agent")
    parser.add_argument(
        "--repl",
        action="store_true",
        help="تشغيل النظام في وضع الـ REPL المتسلسل (الأفضل لـ Termux والكيبورد)",
    )
    args, _ = parser.parse_known_args()

    mock_agent_runner = lambda text: f"تم تحليل الأمر: {text}"

    console.print("⚡ توجيه الإقلاع: وضع REPL (Sequential Mode)")
    launch_stream_tui(agent_runner_func=mock_agent_runner, mode="repl")


if __name__ == "__main__":
    main()
