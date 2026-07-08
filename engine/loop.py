from __future__ import annotations

import time
from typing import Any, Callable, Final

from engine.dispatcher import Dispatcher
from engine.events import bus
from engine.state import RuntimeState

from core.parser import extract_command, extract_json_from_response, validate_tool_call, ToolCall
from core.security import is_safe_command
from core.utils import truncate

from llm_router import execute_agent_with_memory


class ExecutionLoop:
    """
    Autonomous execution engine.

    Flow:

        User
          ↓
        LLM
          ↓
        Parser
          ↓
        Dispatcher
          ↓
        Tool
          ↓
        Feedback
          ↓
        LLM
    """

    POLL_DELAY: Final[float] = 0.5

    def __init__(
        self,
        state: RuntimeState,
        *,
        max_output_len: int = 2000,
        llm_provider: Callable[[list[dict[str, Any]]], str] | None = None,
        dispatcher: Dispatcher | None = None,
    ) -> None:

        self.state = state
        self.dispatcher = dispatcher or Dispatcher(state)
        self.llm_provider = llm_provider or execute_agent_with_memory
        self.max_output_len = max_output_len

    def run(self, user_prompt: str) -> None:
        """
        Starts the autonomous execution loop.
        """

        self.state.messages.append(
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

        try:

            while (
                self.state.status == "RUNNING"
                and self.state.is_loop_safe()
            ):

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

                response = self.llm_provider(
                    self.state.messages
                )

                elapsed = time.perf_counter() - started

                if not response.strip():
                    raise RuntimeError(
                        "LLM returned an empty response."
                    )

                self.state.messages.append(
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
                        self.state.messages.append(
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

                if not hasattr(self, "_recent_calls"):
                    self._recent_calls = []

                if tool_call == last_command or tool_call in self._recent_calls[-4:]:
                    repeated += 1
                    if repeated >= 1 or tool_call == last_command:
                        bus.emit("ui_repeated_tool", {"tool": tool_name, "step": self.state.step_count})
                        self.state.messages.append({
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
                        self.state.messages.append(
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
                    elif "timeout" in output.lower():
                        guidance = "\n[CRITICAL HINT] Execution timed out waiting for input or EOF. Never execute interactive REPL scripts (like 'python main.py') directly."

                    feedback = (
                        f"[{tool_name} Error]\n"
                        f"{output}\n"
                        f"{guidance}\n"
                        "Please analyze the error and fix your command or strategy."
                    )

                self.state.messages.append(
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
