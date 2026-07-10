from __future__ import annotations

import json
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

    BASE_COOLDOWN = 15

    MAX_COOLDOWN = 600

    STATE_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        ".provider_state.json",
    )

    def __init__(self, providers: list[ProviderState], state_key: str = ""):

        self.providers = providers
        self._state_key = state_key
        self._restore_state()

    # --------------------------------------------------------

    def set_state_key(self, key: str) -> None:
        """Update the state key post-construction (e.g. with session_id)."""
        self._state_key = key
        self._restore_state()

    # --------------------------------------------------------

    def _state_path(self) -> str:
        """Session-aware state path. With a key suffix, multiple instances
        don't clobber each other's cooldown state."""
        base = self.STATE_FILE
        if self._state_key:
            stem, ext = os.path.splitext(base)
            return f"{stem}_{self._state_key}{ext}"
        return base

    def _save_state(self) -> None:
        """Persist provider runtime state so cooldowns survive restarts."""
        data = []
        for p in self.providers:
            data.append({
                "name": p.name,
                "failures": p.failures,
                "successes": p.successes,
                "average_latency": p.average_latency,
                "cooldown_until": p.cooldown_until,
            })
        try:
            with open(self._state_path(), "w") as f:
                json.dump(data, f)
        except Exception:
            pass  # best-effort; non-critical

    def _restore_state(self) -> None:
        """Load persisted provider state on startup."""
        path = self._state_path()
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            saved = {d["name"]: d for d in data}
            for p in self.providers:
                if p.name in saved:
                    s = saved[p.name]
                    p.failures = s["failures"]
                    p.successes = s["successes"]
                    p.average_latency = s["average_latency"]
                    p.cooldown_until = s["cooldown_until"]
        except Exception:
            pass

    # --------------------------------------------------------

    def _cooldown_duration(self, consecutive_failures: int) -> float:
        """
        Exponential backoff: 15, 30, 60, 120, 240, ... capped at MAX_COOLDOWN.
        Resets on successful recovery.
        """
        duration = self.BASE_COOLDOWN * (2 ** (consecutive_failures - self.FAILURE_LIMIT))
        return min(duration, self.MAX_COOLDOWN)

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

        self._save_state()

    # --------------------------------------------------------

    def _record_failure(
        self,
        provider: ProviderState,
    ) -> None:

        provider.failures += 1

        if provider.failures >= self.FAILURE_LIMIT:

            provider.cooldown_until = (
                time.time()
                + self._cooldown_duration(provider.failures)
            )

        self._save_state()

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
                bus.emit("llm_provider_failover", {"provider": provider.name, "error": str(exc)[:60]})

                errors.append(
                    f"{provider.name}: {exc}"
                )

        raise RuntimeError(
            "[CRITICAL] All available LLM providers failed or rate-limited.\n"
            + "\n".join(errors)
        )

    # --------------------------------------------------------

    def generate_stream(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Streaming generation. Attempts Local first with SSE; falls back
        to non-streaming generate() if the provider doesn't support it."""
        _load_env_files()
        errors: list[str] = []

        for provider in self._sorted():
            # Only Local supports streaming currently
            if provider.name == "Local" and hasattr(provider.client, "generate_stream"):
                started = time.perf_counter()
                try:
                    response = provider.client.generate_stream(messages, **kwargs)
                    latency = time.perf_counter() - started
                    self._record_success(provider, latency)
                    bus.emit("llm_provider_success", {"provider": provider.name, "latency": latency})
                    return response
                except Exception as exc:
                    self._record_failure(provider)
                    bus.emit("llm_provider_failure", {"provider": provider.name, "error": str(exc)[:60]})
                    bus.emit("llm_provider_failover", {"provider": provider.name, "error": str(exc)[:60]})
                    errors.append(f"{provider.name} stream: {exc}")
                    # Fall through to non-streaming fallback
                    continue

            # Non-streaming fallback for all providers
            started = time.perf_counter()
            try:
                response = provider.client.generate_response(messages, **kwargs)
                latency = time.perf_counter() - started
                self._record_success(provider, latency)
                bus.emit("llm_provider_success", {"provider": provider.name, "latency": latency})
                return response
            except Exception as exc:
                self._record_failure(provider)
                bus.emit("llm_provider_failure", {"provider": provider.name, "error": str(exc)[:60]})
                bus.emit("llm_provider_failover", {"provider": provider.name, "error": str(exc)[:60]})
                errors.append(f"{provider.name}: {exc}")

        raise RuntimeError(
            "[CRITICAL] All available LLM providers failed.\n"
            + "\n".join(errors)
        )

    generate_response = generate_stream


# ============================================================
# Build Providers
# ============================================================

router = ProviderRouter(
    [
        ProviderState(
            name="OpenRouter",
            client=OpenRouterClient(),
            priority=0,
            enabled=True,
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

    return router.generate_stream(
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
