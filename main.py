import os
import sys
import atexit
import shutil
import textwrap

import threading
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.formatted_text import ANSI

from engine.state import RuntimeState
from engine.loop import ExecutionLoop
from engine.tool_registry import registry
from engine.events import bus
from tools import ShellTool, FileSystemTool, WebSearchTool, SearchMemoryTool
from core.session import SessionManager
from core.logger import Logger
from core.metrics import MetricsEngine
from core.config import AgentConfig
from core.utils import truncate
from core.memory import MemoryManager

# 📐 القياس الموحد الصارم للمنظومة بالكامل بداخل تيرمكس
CANVAS_WIDTH = 48


def get_layout_margin():
    """حساب الهامش الأيسر ديناميكياً لتركيز المنظومة بالكامل على مستوى واحد"""
    term_cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    effective_width = min(term_cols, CANVAS_WIDTH)
    margin_size = max(0, (term_cols - effective_width) // 2)
    return " " * margin_size, effective_width


class CyberSpinner:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def _spin(self):
        # 🛡️ درع الأمان: ننتظر 0.2 ثانية لتسمح للمحرك الرئيسي بإنهاء طباعة فواصل الخطوات
        time.sleep(0.2)
        idx = 0
        # 📌 [تكتيك الصدمات] - حفظ موقع الكرسر الحالي بذاكرة الطرفية فوراً عند البدء
        sys.stdout.write("\033[s")
        sys.stdout.flush()

        while not self._stop_event.is_set():
            padding_left, _ = get_layout_margin()
            frame = self.frames[idx % len(self.frames)]
            # 🛡️ السحر هنا: استدعاء الموقع المحفوظ (u) + تنظيف السطر بالكامل (K)
            sys.stdout.write(f"\033[u\033[K{padding_left}\033[1;37;45m {frame} Examining... \033[0m \033[90mProcessing context payload...\033[0m")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.08)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=1.0)
            # تنظيف نهائي مطلق للسطر عند التوقف لترك المكان صافي
            sys.stdout.write("\033[u\033[K")
            sys.stdout.flush()
            self._thread = None


def render_user_prompt_panel(text):
    """رسم صندوق سؤال المستخدم الممتلئ ملتزماً بالمستوى الموحد"""
    if not text.strip():
        return
    padding_left, eff_width = get_layout_margin()
    wrapper = textwrap.TextWrapper(
        width=max(20, eff_width - 4),
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=True,
    )

    formatted_lines = []
    for paragraph in text.splitlines():
        if paragraph.strip() == "":
            formatted_lines.append("")
        else:
            formatted_lines.extend(wrapper.wrap(paragraph))

    bg_ansi = "\033[48;5;237m"
    text_ansi = "\033[38;5;253m"
    reset_ansi = "\033[0m"

    print(f"{reset_ansi}")
    for line in formatted_lines:
        padded_line = f" {line}".ljust(max(1, eff_width - 2))
        print(f"{padding_left}{bg_ansi}{text_ansi}{padded_line}{reset_ansi}")
    print(f"{reset_ansi}")


# ============================================================================
# ============================================================================
# 1. RAW EVENT WIRING (شلال البيانات المنسق بالمليمتر - Continuous Stream TUI)
# ============================================================================

def format_action_badge(tool: str, args: dict) -> str:
    """تحديد شارة العملية والألوان بناءً على نوع الأداة والإجراء"""
    if tool == "execute_shell":
        return "\033[1;37;41m EXEC \033[0m"
    elif tool == "file_system":
        action = str(args.get("action", "")).lower()
        if action in ("read", "list", "exists"):
            return "\033[1;37;44m READ \033[0m"
        else:
            return "\033[1;37;42m WRITE \033[0m"
    elif tool == "web_search":
        return "\033[1;37;45m SEARCH \033[0m"
    elif tool == "search_memory":
        return "\033[1;37;43m MEMORY \033[0m"
    return "\033[1;37;46m TOOL \033[0m"


def render_diff(diff_text: str) -> str:
    """تحويل أسطر الـ Diff إلى بلوكات ملونة باللون الأحمر والأخضر ومحاذاتها على المستوى الموحد"""
    padding_left, _ = get_layout_margin()
    formatted_lines = []
    for line in diff_text.splitlines():
        if line.startswith('---') or line.startswith('+++'):
            formatted_lines.append(f"{padding_left}\033[1;36m{line}\033[0m")
        elif line.startswith('@@'):
            formatted_lines.append(f"{padding_left}\033[1;33m{line}\033[0m")
        elif line.startswith('-'):
            formatted_lines.append(f"{padding_left}\033[1;37;41m{line}\033[0m")
        elif line.startswith('+'):
            formatted_lines.append(f"{padding_left}\033[1;37;42m{line}\033[0m")
        else:
            formatted_lines.append(f"{padding_left}\033[90m{line}\033[0m")
    return "\n".join(formatted_lines)


def render_todos(todo_list: list[dict]) -> None:
    """طباعة قائمة المهام مع ميزة الشطب ومحاذاتها على المستوى الموحد"""
    padding_left, _ = get_layout_margin()
    print(f"\n{padding_left}\033[1;37;45m TODOS \033[0m \033[90m[{len(todo_list)} items]\033[0m")
    for item in todo_list:
        is_done = item.get('done', False)
        task_text = item.get('task', '')
        if is_done:
            print(f"{padding_left}  \033[32m☑ \033[9m{task_text}\033[29m\033[0m")
        else:
            print(f"{padding_left}  \033[37m☐ {task_text}\033[0m")


def wire_raw_events(metrics: MetricsEngine):
    """ربط أحداث المحرك بشلال بيانات منسق ومحاذي على مستوى عمودي واحد"""
    spinner = CyberSpinner()

    def _on_llm_started(p):
        padding_left, eff_width = get_layout_margin()
        step = p.get('step', 0) + 1
        print(f"\n{padding_left}\033[90m{'─' * eff_width}\033[0m")
        line_fill = max(0, eff_width - len(f"── [ Step {step} ] ──"))
        print(f"{padding_left}\033[90m── [ Step {step} ] {'─' * line_fill}\033[0m")
        spinner.start()

    def _on_llm_completed(p):
        spinner.stop()
        padding_left, _ = get_layout_margin()
        metrics.record_api_call(duration=p.get('duration', 1.0))
        dur = p.get('duration', 0.0)
        chars = p.get('length', 0)
        print(f"{padding_left}\033[90m  └─ Thought structured ({chars} chars) in {dur:.2f}s [ctrl+o to expand]\033[0m")

    def _on_tool_started(p):
        padding_left, _ = get_layout_margin()
        tool = p.get('tool', '')
        args = p.get('args', {})
        badge = format_action_badge(tool, args)
        target = args.get('path') or args.get('command') or args.get('query') or 'system'
        print(f"{padding_left}\033[1;37;45m ◆ {tool.upper()}ING... \033[0m \033[90m| Ready\033[0m")
        print(f"{padding_left}{badge} \033[1m{tool}\033[0m \033[32m[{truncate(str(target), 28)}]\033[0m")

    def _on_tool_completed(p):
        padding_left, eff_width = get_layout_margin()
        success = p.get('success', False)
        code = p.get('returncode', -1)
        diff_text = p.get('diff', '')
        result_obj = p.get('result')
        output_text = getattr(result_obj, 'output', '') or p.get('output', '') or getattr(result_obj, 'stdout', '')
        status_badge = "\033[1;37;42m OK \033[0m" if success else "\033[1;37;41m FAIL \033[0m"
        if diff_text:
            print(render_diff(diff_text))
        elif output_text:
            lines = str(output_text).splitlines()
            safe_lines = lines[:10]
            print("\n".join(f"{padding_left}\033[90m  │ \033[0m{line[:eff_width-6]}" for line in safe_lines))
            if len(lines) > 10:
                print(f"{padding_left}\033[90m  │ ... +{len(lines) - 10} lines [ctrl+o to expand]\033[0m")
        print(f"{padding_left}  └─ {status_badge} \033[90mCode: {code}\033[0m")

    bus.subscribe("llm_request_started", _on_llm_started)
    bus.subscribe("llm_request_completed", _on_llm_completed)
    bus.subscribe("show_todo_list", lambda p: render_todos(p.get("todos", [])))
    bus.subscribe("tool_started", _on_tool_started)
    bus.subscribe("tool_completed", _on_tool_completed)
    bus.subscribe("loop_max_steps_reached", lambda p: print(f"\n{get_layout_margin()[0]}\033[1;37;41m PAUSED \033[0m Max steps reached!"))
    bus.subscribe("loop_error", lambda p: print(f"\n{get_layout_margin()[0]}\033[1;37;41m ERROR \033[0m Engine encountered an error: {p.get('error', 'Unknown')}"))


def setup_system():
    config = AgentConfig()
    session_mgr = SessionManager(root=config.session_dir)
    logger = Logger(log_dir=config.log_dir)
    metrics = MetricsEngine()
    memory_mgr = MemoryManager(db_path=os.path.join(config.root_dir, "workspace_memory.db"))

    for tool_cls in [ShellTool, FileSystemTool, WebSearchTool, SearchMemoryTool]:
        tool = tool_cls(workspace=config.root_dir) if tool_cls is FileSystemTool else (
            SearchMemoryTool(memory_manager=memory_mgr) if tool_cls is SearchMemoryTool else tool_cls()
        )
        try:
            registry.register(tool)
        except ValueError:
            pass

    atexit.register(logger.shutdown)
    atexit.register(memory_mgr.close)
    return session_mgr, logger, metrics, config, memory_mgr


# ============================================================================
# 2. MAIN EXECUTION LOOP
# ============================================================================

def main():
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

    # ── [حقن الشعار الأسطوري] ──
    # سيتم طباعة الشعار وبيانات المستودع فوراً عند تشغيل البرنامج
    try:
        import nabd_logo
        nabd_logo.draw()
    except Exception as e:
        print(f"[WARN] Failed to render splash logo: {e}")

    # ── نظام الإقلاع القياسي المستقر ──
    session_mgr, logger, metrics, config, memory_mgr = setup_system()
    deleted = session_mgr.enforce_retention_policy(config.max_sessions)

    state = RuntimeState(session_id=session_mgr.session_id, max_steps=50)
    wire_raw_events(metrics)

    if deleted:
        print(f"[INFO] Cleaned {deleted} old session(s).")
    print(f"[+] Session Initialized: {session_mgr.session_id}")

    base_inst = (
        "You are an advanced Autonomous Agent running on a Linux environment.\n"
        "CRITICAL RULE: You must respond ONLY and exclusively in English. \n"
        "Never use Arabic characters or any other RTL language in your thoughts, plans, or responses. \n"
        "Keep all terminal outputs in clean, standard English."
    )
    state.messages.append({"role": "system", "content": base_inst})

    # 🛡️ حقن درع الحماية من اللمس العشوائي بداخل الشاشة المستقلة
    input_session = PromptSession(
        history=InMemoryHistory(),
        mouse_support=True
    )

    # حلقة الإدخال المصفحة ضد تداخل اللمسات والأسهم
    while True:
        try:
            user_input = input_session.prompt(ANSI("\n\033[1;37;45m USER \033[0m ")).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            break

        if user_input.lower() == "clear":
            state.messages = [{"role": "system", "content": base_inst}]
            state.step_count = 0
            print("[+] Local session memory cleared.")
            continue

        # بعد سطر جلب السؤال مباشرة:
        time.sleep(0.1)
        sys.stdout.write("\033[F\033[K")
        sys.stdout.flush()

        padding_left, eff_width = get_layout_margin()

        render_user_prompt_panel(user_input)

        # طباعة خط الفصل وشارة الـ PLAN الموحدة والمحمية بـ \033[K
        print(f"{padding_left}\033[90m" + "─" * eff_width + "\033[0m")
        print(f"{padding_left}\033[1;37;44m PLAN \033[0m \033[32mAnalyzing request...\033[0m\033[K")
        state.step_count = 0
        engine = ExecutionLoop(state=state, max_output_len=config.max_output)

        try:
            engine.run(user_input)

            session_mgr.messages = state.messages
            session_mgr.save()

            # طباعة الرد النهائي للوكيل مباشرة على الشاشة المستمرة بالمحاذاة الموحدة
            last_msg = state.messages[-1]
            if last_msg.get("role") == "assistant":
                print(f"\n{padding_left}\033[1;37;42m AGENT \033[0m")
                for line in last_msg.get('content', '').splitlines():
                    print(f"{padding_left}{line}")

        except KeyboardInterrupt:
            print("\n[!] Execution interrupted by user.")
        except Exception as exc:
            print(f"\n[SYSTEM ERROR] {exc}")
            logger.error(f"Execution failed: {exc}")


if __name__ == "__main__":
    main()
