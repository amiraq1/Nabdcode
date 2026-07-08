from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.llm import (
    LocalClient,
    OpenRouterClient,
)
from engine.events import bus

# Terminal color setup for system logs
CYAN = "\033[96m"
PURPLE = "\033[95m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _load_env_files() -> None:
    for filepath in [os.path.join(os.path.expanduser("~"), ".env"), ".env"]:
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip("'").strip('"')
                            if key and not os.getenv(key):
                                os.environ[key] = val
            except Exception:
                pass


_load_env_files()


# ============================================================
# Provider Interface
# ============================================================

class LLMProvider(Protocol):

    def generate_response(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        ...


# ============================================================
# Provider State
# ============================================================

@dataclass(slots=True)
class ProviderState:

    name: str

    client: LLMProvider

    priority: int = 0

    enabled: bool = True

    failures: int = 0

    successes: int = 0

    average_latency: float = 0.0

    cooldown_until: float = 0.0


# ============================================================
# Router
# ============================================================

class ProviderRouter:

    FAILURE_LIMIT = 3

    COOLDOWN_SECONDS = 30

    def __init__(self, providers: list[ProviderState]):

        self.providers = providers

    # --------------------------------------------------------

    def _sorted(self) -> list[ProviderState]:

        now = time.time()

        available = [
            p
            for p in self.providers
            if p.enabled and p.cooldown_until <= now
        ]

        return sorted(
            available,
            key=lambda p: (
                p.priority,
                p.average_latency,
                p.failures,
            ),
        )

    # --------------------------------------------------------

    def _record_success(
        self,
        provider: ProviderState,
        latency: float,
    ) -> None:

        provider.successes += 1

        provider.failures = 0

        if provider.average_latency == 0:

            provider.average_latency = latency

        else:

            provider.average_latency = (
                provider.average_latency * 0.7
                + latency * 0.3
            )

    # --------------------------------------------------------

    def _record_failure(
        self,
        provider: ProviderState,
    ) -> None:

        provider.failures += 1

        if provider.failures >= self.FAILURE_LIMIT:

            provider.cooldown_until = (
                time.time()
                + self.COOLDOWN_SECONDS
            )

    # --------------------------------------------------------

    def generate(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:

        _load_env_files()
        errors: list[str] = []

        for provider in self._sorted():

            started = time.perf_counter()

            try:

                response = provider.client.generate_response(
                    messages,
                    **kwargs,
                )

                latency = (
                    time.perf_counter()
                    - started
                )

                self._record_success(
                    provider,
                    latency,
                )

                bus.emit("llm_provider_success", {"provider": provider.name, "latency": latency})
                return response

            except Exception as exc:

                self._record_failure(provider)
                bus.emit("llm_provider_failure", {"provider": provider.name, "error": str(exc)[:60]})
                err_msg = str(exc).replace('\n', ' ')[:50]
                print(f"\r\033[K\033[1;33m [FAILOVER] Provider '{provider.name}' failed ({err_msg}). Switching to next provider...\033[0m")

                errors.append(
                    f"{provider.name}: {exc}"
                )

        raise RuntimeError(
            "[CRITICAL] All available LLM providers failed or rate-limited.\n"
            + "\n".join(errors)
        )


# ============================================================
# Build Providers
# ============================================================

router = ProviderRouter(

    [

        ProviderState(

            name="Local",

            client=LocalClient(),

            priority=0,

        ),

        ProviderState(

            name="OpenRouter",

            client=OpenRouterClient(),

            priority=1,

        ),

    ]

)


# ============================================================
# Public API
# ============================================================

def execute_agent_with_memory(state_or_messages: Any, **kwargs: Any) -> str:
    if isinstance(state_or_messages, list):
        messages = state_or_messages
    elif hasattr(state_or_messages, "messages"):
        messages = state_or_messages.messages
    elif isinstance(state_or_messages, dict) and "messages" in state_or_messages:
        messages = state_or_messages["messages"]
    else:
        messages = str(state_or_messages)

    return router.generate(
        messages,
        **kwargs,
    )


# --- Execution test ---
if __name__ == "__main__":
    agent_messages = [
        {"role": "system", "content": "You are a highly efficient CLI agent."},
        {"role": "user", "content": "What is the result of 2+2? Answer in one word."}
    ]

    try:
        result = execute_agent_with_memory(agent_messages)
        print(f"\n{CYAN}--- Agent Output ---{RESET}\n{result}\n")
    except Exception as err:
        print(f"{RED}[ERROR] Task halted: {err}{RESET}")
