from __future__ import annotations

from collections import deque
import re
import time
from typing import Any, Callable, Final

from engine.dispatcher import Dispatcher
from engine.events import bus
from engine.state import RuntimeState

from core.parser import extract_command, extract_json_from_response, validate_tool_call, ToolCall
from core.security import is_safe_command
from core.utils import truncate
from pathlib import Path
from core.evidence import EvidenceLog, VerifierError
from core.constants import is_chitchat
from core.memory import load_memory, write_lesson
from core.sanitize import sanitize
from llm_router import execute_agent_with_memory


def _prompt_requires_investigation(text: str) -> bool:
    """Return True if this prompt asks for real work, not chitchat or simple math."""
    if is_chitchat(text)[0]:
        return False
    if re.search(r'^\s*\d+\s*[\+\-\*\/]\s*\d+', text):
        return False
    return True


MAX_SELF_CORRECT: Final[int] = 3
MAX_THOUGHTS_WITHOUT_ACTION: Final[int] = 3
MAX_BUDGET_SECONDS: Final[int] = 180  # سقف الميزانية: 3 دقائق لكل مهمة على Termux
MAX_BUDGET_TOKENS: Final[int] = 12000  # سقف التوكنات التقريبي


class ToolRequiredError(RuntimeError):
    """Raised when the agent answered without using required tools."""
    pass


class ExecutionLoop:
    """
    Autonomous execution engine with Self-Correction Loop.
    """

    POLL_DELAY: Final[float] = 0.5

    def __init__(
        self,
        state: RuntimeState,
        *,
        max_output_len: int = 2000,
        llm_provider: Callable[[list[dict[str, Any]]], str] | None = None,
        dispatcher: Dispatcher | None = None,
        evidence_log: EvidenceLog | None = None,
    ) -> None:

        self.state = state
        self.dispatcher = dispatcher or Dispatcher(state)
        self.llm_provider = llm_provider or execute_agent_with_memory
        self.max_output_len = max_output_len
        self._recent_calls: deque[ToolCall] = deque(maxlen=16)
        self.evidence_log = evidence_log or EvidenceLog()
        self._self_correct_count = 0

    def _build_critique(self, result: Any, last_tool_call: Any = None) -> str:
        findings_str = str(getattr(result, "findings", result))
        if "technical anchors" in findings_str:
            return (
                f"[VERIFIER CRITIQUE L1]: {findings_str} "
                f"قاعدتك الحالية لا تحتوي على دليل نصي. "
                f"يجب عليك أولا استدعاء file_system.read أو shell، "
                f"ثم اقتبس سطرا حرفيا من المخرجات في ردك. "
                f"ممنوع الادعاء بدون اقتباس."
            )
        if "enumeration" in findings_str:
            return f"[VERIFIER CRITIQUE]: ادعيت عددا بدون دليل. استخدم الأداة ثم اذكر المخرجات."

        return f"[VERIFIER CRITIQUE]: {findings_str}. صحح مسارك وأعد المحاولة بالأداة الصحيحة."

    def _safe_shutdown(self, task: str, last_result: Any) -> str:
        try:
            if hasattr(self, "executor") and hasattr(self.executor, "close_all"):
                self.executor.close_all()
            if hasattr(self, "session") and hasattr(self.session, "flush"):
                self.session.flush()
        except Exception:
            pass
        findings_str = str(getattr(last_result, "findings", last_result))
        return f"تعذر إكمال المهمة بعد {MAX_SELF_CORRECT} محاولات تصحيح ذاتي. آخر خطأ: {findings_str}"

    def _compact_messages(
        self, messages: list[dict[str, Any]], keep_last_tools: int = 2
    ) -> list[dict[str, Any]]:
        if len(messages) <= 8:
            return messages

        system_msg = messages[0]
        first_user = messages[1]

        # Keep only the last keep_last_tools tool messages + last critique
        tail = []
        tool_count = 0
        for m in reversed(messages[2:]):
            if m.get("role") == "tool" and tool_count < keep_last_tools:
                tail.append(m)
                tool_count += 1
            elif "[VERIFIER CRITIQUE" in str(m.get("content", "")):
                tail.append(m)
                break

        tail.reverse()
        return [system_msg, first_user] + tail

    def run(self, user_prompt: str) -> None:
        """
        Starts the autonomous execution loop.
        """

        self.state.append_message(
            {
                "role": "user",
                "content": user_prompt,
            }
        )

        self.state.update_status("RUNNING")

        bus.emit(
            "loop_started",
            {
                "session_id": self.state.session_id,
            },
        )

        last_command = None
        repeated = 0
        interrupted = False
        start_time = time.time()
        self._self_correct_count = 0
        last_response_fingerprints = []

        try:

            while (
                self.state.status == "RUNNING"
                and self.state.is_loop_safe()
            ):

                # 1. Budget Ceiling
                elapsed_total = time.time() - start_time
                token_est = sum(len(str(m.get("content", ""))) // 4 for m in self.state.get_messages())
                if elapsed_total > MAX_BUDGET_SECONDS or token_est > MAX_BUDGET_TOKENS:
                    self.state.update_status("COMPLETED")
                    safe_msg = self._safe_shutdown(user_prompt, f"Budget Ceiling: time={int(elapsed_total)}s tokens~{token_est}")
                    bus.emit(
                        "loop_completed",
                        {
                            "reason": "budget_exhausted",
                            "output": safe_msg,
                        },
                    )
                    return

                #
                # LLM
                #

                started = time.perf_counter()

                bus.emit(
                    "llm_request_started",
                    {
                        "step": self.state.step_count,
                    },
                )

                compacted = self._compact_messages(self.state.get_messages())
                if compacted and compacted[0].get("role") == "system":
                    agent_md = Path("AGENT.md")
                    rules = sanitize(agent_md.read_text(encoding="utf-8"))[:4000] if agent_md.exists() else ""
                    memory = sanitize(load_memory() or "")[:4000]
                    prefix = ""
                    if rules:
                        prefix += f"{rules}\n\n"
                    if memory:
                        prefix += f"# ذاكرة سابقة:\n{memory}\n\n"
                    if prefix:
                        compacted = [
                            {
                                "role": "system",
                                "content": f"{prefix}{compacted[0]['content']}",
                            }
                        ] + compacted[1:]
                response = self.llm_provider(compacted)

                # ================================
                # [REPETITION GUARD LOGIC]
                # ================================
                fingerprint = response.strip()[:200]
                if fingerprint and last_response_fingerprints.count(fingerprint) >= 2:
                    self.state.update_status("COMPLETED")
                    safe_msg = self._safe_shutdown(
                        user_prompt,
                        "CRITICAL: Infinite Replication Loop Detected (Entropy = 0). "
                        "Aborting session to preserve API budget and memory."
                    )
                    bus.emit(
                        "loop_completed",
                        {
                            "reason": "infinite_replication_loop",
                            "output": safe_msg,
                        },
                    )
                    return

                if fingerprint:
                    last_response_fingerprints.append(fingerprint)
                    if len(last_response_fingerprints) > 3:
                        last_response_fingerprints.pop(0)
                # ================================
                # [END OF GUARD LOGIC]
                # ================================

                elapsed = time.perf_counter() - started

                if not response.strip():
                    bus.emit("ui_validation_failed", {"error": "LLM returned an empty response.", "step": self.state.step_count})
                    self.state.append_message(
                        {
                            "role": "system",
                            "content": "Your previous response was empty. Please provide either a tool call or your answer.",
                        }
                    )
                    self.state.increment_step()
                    time.sleep(self.POLL_DELAY)
                    continue

                self.state.append_message(
                    {
                        "role": "assistant",
                        "content": response,
                    }
                )

                bus.emit(
                    "llm_request_completed",
                    {
                        "duration": elapsed,
                        "length": len(response),
                    },
                )

                todos = []
                for line in response.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- [ ] "):
                        todos.append({"task": stripped[6:].strip(), "done": False})
                    elif stripped.startswith("- [x] ") or stripped.startswith("- [X] "):
                        todos.append({"task": stripped[6:].strip(), "done": True})
                if todos:
                    bus.emit("show_todo_list", {"todos": todos, "step": self.state.step_count})

                #
                # Parse & Gatekeeper Validation
                #

                raw_json = extract_json_from_response(response)
                tool_call = None

                if raw_json:
                    is_valid, parsed, error = validate_tool_call(raw_json)
                    if not is_valid:
                        bus.emit("ui_validation_failed", {"error": error, "step": self.state.step_count})
                        bus.emit("tool_validation_failed", {"error": error, "raw_json": raw_json, "step": self.state.step_count})
                        correction_prompt = (
                            "Your previous tool call was rejected.\n\n"
                            f"Reason:\n{error}\n\n"
                            "Output ONLY one valid JSON object.\n\n"
                            "Allowed tools:\n\n"
                            "execute_shell\n"
                            "file_system\n"
                            "web_search\n"
                            "search_memory\n\n"
                            "Do not explain.\n"
                            "Do not use markdown.\n"
                            "Do not wrap inside ```.\n\n"
                            "Return valid JSON only."
                        )
                        self.state.append_message(
                            {
                                "role": "system",
                                "content": correction_prompt,
                            }
                        )
                        self.state.increment_step()
                        time.sleep(self.POLL_DELAY)
                        continue
                    else:
                        tool_call = ToolCall(tool=parsed["tool"], args=parsed["args"])
                else:
                    tool_call = extract_command(response)

                if tool_call is None:
                    bus.emit("ui_no_tool_call", {"step": self.state.step_count})

                    # Verification stage: run the Verifier before returning.
                    # Catches: missing evidence, failed evidence, type mismatch.
                    require_tools = _prompt_requires_investigation(user_prompt)
                    try:
                        self.evidence_log.verify_fresh(
                            require_tools=require_tools,
                            claim=response,
                        )
                    except VerifierError as verr:
                        if self._self_correct_count < MAX_SELF_CORRECT:
                            self._self_correct_count += 1
                            critique = self._build_critique(verr)
                            self.state.append_message({"role": "user", "content": critique})
                            bus.emit("verifier_critique", {
                                "step": self.state.step_count,
                                "attempt": self._self_correct_count,
                                "max_attempts": MAX_SELF_CORRECT,
                                "critique": critique,
                            })
                            self.state.increment_step()
                            time.sleep(self.POLL_DELAY)
                            continue
                        else:
                            self.state.update_status("COMPLETED")
                            safe_msg = self._safe_shutdown(user_prompt, verr)
                            bus.emit(
                                "loop_completed",
                                {
                                    "reason": "self_correct_exhausted",
                                    "output": safe_msg,
                                },
                            )
                            return

                    if self._self_correct_count > 0:
                        write_lesson(
                            problem=f"فشل أولي في التحقق وتم حله بعد {self._self_correct_count} محاولة تصحيح",
                            solution=f"تم الحل عبر الالتزام بقواعد دستور العميل والاقتباس من المخرجات",
                        )
                    self.state.update_status("COMPLETED")

                    bus.emit(
                        "loop_completed",
                        {
                            "reason": "no_tool_call",
                            "output": response,
                        },
                    )

                    return

                tool_name = tool_call.tool
                tool_args = tool_call.args

                #
                # Infinite loop & Cycle detection
                #

                recent_slice = list(self._recent_calls)[-4:]
                if tool_call == last_command or tool_call in recent_slice:
                    repeated += 1
                    if repeated >= 2 or (tool_call == last_command and repeated >= 1):
                        bus.emit("ui_repeated_tool", {"tool": tool_name, "step": self.state.step_count})
                        self.state.append_message({
                            "role": "system",
                            "content": f"STOP! You have already executed '{tool_name}' with these exact arguments recently. Do NOT repeat failed commands or oscillate between them. Try a different strategy or inspect files directly."
                        })
                        self.state.increment_step()
                        time.sleep(self.POLL_DELAY)
                        continue
                else:
                    repeated = 0

                self._recent_calls.append(tool_call)
                last_command = tool_call

                #
                # Security Layer
                #

                if tool_name == "execute_shell":
                    command = tool_args.get("command", "")
                    if not is_safe_command(command):
                        bus.emit("ui_security_blocked", {"command": command, "step": self.state.step_count})
                        bus.emit("tool_security_blocked", {"command": command, "step": self.state.step_count})
                        self.state.append_message(
                            {
                                "role": "system",
                                "content": "Your shell command violated security policy. Generate a safer alternative.",
                            }
                        )
                        self.state.increment_step()
                        time.sleep(self.POLL_DELAY)
                        continue

                #
                # Execute Tool
                #

                result = self.dispatcher.dispatch(
                    tool_name,
                    tool_args,
                )

                #
                # Evidence — every successful tool call gets a traceable ID
                #

                cmd_summary = (
                    tool_args.get("command")
                    or tool_args.get("path")
                    or tool_args.get("query")
                    or str(tool_args)[:60]
                )
                self.evidence_log.record(
                    tool=tool_name,
                    command_or_path=cmd_summary,
                    success=getattr(result, "success", False),
                    output_snippet=getattr(result, "output", "") or getattr(result, "stderr", ""),
                )

                #
                # Feedback
                #

                output_val = getattr(result, "output", "") or getattr(result, "stderr", "") or str(result)
                output = truncate(
                    output_val,
                    self.max_output_len,
                )

                if getattr(result, "success", False):

                    feedback = (
                        f"[{tool_name} Output]\n"
                        f"{output}"
                    )

                else:

                    guidance = ""
                    if "can't open file" in output and "python" in str(tool_args):
                        guidance = "\n[CRITICAL HINT] To execute inline Python statements via bash, you MUST use python3 -c \"import ...\". Never write unflagged 'python import ...'."
                    elif any(msg in output.lower() for msg in ("timed out after", "timeoutexpired", "command execution timed out")):
                        guidance = "\n[CRITICAL HINT] Execution timed out waiting for input or EOF. Never execute interactive REPL scripts directly."

                    feedback = (
                        f"[{tool_name} Error]\n"
                        f"{output}\n"
                        f"{guidance}\n"
                        "Please analyze the error and fix your command or strategy."
                    )

                self.state.append_message(
                    {
                        "role": "user",
                        "content": feedback,
                    }
                )

                self.state.increment_step()
                self.state.prune_history()

                time.sleep(self.POLL_DELAY)

        except KeyboardInterrupt:

            self.state.update_status("PAUSED")
            interrupted = True

            bus.emit(
                "loop_interrupted",
                {},
            )

        except Exception as exc:

            self.state.update_status("ERROR")

            bus.emit(
                "loop_error",
                {
                    "step": self.state.step_count,
                    "error": str(exc),
                },
            )

            raise

        finally:

            if not interrupted:
                if (
                    self.state.status == "RUNNING"
                    and not self.state.is_loop_safe()
                ):

                    self.state.update_status("PAUSED")

                    bus.emit(
                        "loop_max_steps_reached",
                        {
                            "max_steps": self.state.max_steps,
                        },
                    )

                bus.emit(
                    "loop_finished",
                    {
                        "status": self.state.status,
                        "steps": self.state.step_count,
                    },
                )
