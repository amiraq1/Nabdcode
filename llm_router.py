from __future__ import annotations
import os, time
from dataclasses import dataclass
from typing import Any
import core._env
from core.llm import OpenRouterClient
try:
    from core.llm import NvidiaClient
except Exception:
    NvidiaClient = None

@dataclass
class ProviderState:
    name: str
    client: Any
    priority: int = 0
    enabled: bool = True
    failure_count: int = 0
    cooldown_until: float = 0
    def is_available(self): return self.enabled and time.time() >= self.cooldown_until
    def record_failure(self): self.failure_count+=1; self.cooldown_until=time.time()+10*self.failure_count
    def record_success(self): self.failure_count=0; self.cooldown_until=0

class ProviderRouter:
    def __init__(self, providers):
        self.providers = sorted(providers, key=lambda x: x.priority)
        self.state_key = ""
    def set_state_key(self, key: str) -> None:
        self.state_key = key
    def _sorted(self): return [p for p in self.providers if p.is_available()]
    def generate_stream(self, messages, **kwargs):
        last = None
        for p in self._sorted():
            try:
                res = p.client.generate_response(messages, **kwargs)
                p.record_success()
                yield res
                return
            except Exception as e:
                last = e
                p.record_failure()
                print(f"[fallback] {p.name} failed -> next")
                continue
        raise RuntimeError(f"All failed: {last}")
    def generate_response(self, m, **kwargs): return "".join(self.generate_stream(m, **kwargs))

FREE_MODELS = [
    os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b:free"),
    "google/gemma-3-27b:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3-32b:free",
    "openai/gpt-oss-20b:free",
    "deepseek/deepseek-chat-v3.1:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
]

providers = []
seen = set()
for i, mdl in enumerate(FREE_MODELS):
    if not mdl or mdl in seen:
        continue
    seen.add(mdl)
    try:
        providers.append(ProviderState(name=f"OR-{i}", client=OpenRouterClient(model=mdl), priority=i))
    except Exception:
        pass

if NvidiaClient:
    try:
        providers.append(ProviderState(name="NVIDIA", client=NvidiaClient(), priority=99))
    except Exception:
        pass

router = ProviderRouter(providers)

def execute_agent_with_memory(state_or_messages: Any, **kwargs: Any) -> str:
    if isinstance(state_or_messages, list):
        messages = state_or_messages
    elif hasattr(state_or_messages, "messages"):
        messages = state_or_messages.messages
    elif isinstance(state_or_messages, dict) and "messages" in state_or_messages:
        messages = state_or_messages["messages"]
    else:
        messages = str(state_or_messages)
    return router.generate_response(messages, **kwargs)
