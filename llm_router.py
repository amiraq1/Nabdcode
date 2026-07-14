from __future__ import annotations
import os, time, json
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
    def record_failure(self, rate=False, notfound=False):
        if notfound:
            self.enabled = False
            return
        self.failure_count += 1
        self.cooldown_until = time.time() + (65 if rate else 10 * self.failure_count)
    def record_success(self):
        self.failure_count = 0
        self.cooldown_until = 0

def is_rate_limit(e):
    s = str(e).lower()
    return "429" in s or "rate-limited" in s or "20 requests" in s

def is_not_found(e):
    s = str(e).lower()
    return "404" in s or "no endpoints" in s or "unavailable for free" in s

class ProviderRouter:
    def __init__(self, providers, state_key: str = ""):
        self.providers = sorted(providers, key=lambda x: x.priority)
        self.state_key = state_key
        # Per-key state isolation: a named key yields a distinct on-disk state
        # file so concurrent sessions don't clobber each other's router state.
        self._restore_state()
    def set_state_key(self, key: str) -> None:
        self.state_key = key
        self._restore_state()
    def _state_path(self) -> str:
        """Return the on-disk provider-state path for this router.

        A named ``state_key`` yields ``<key>.provider_state.json``; the default
        (no key) yields the shared ``provider_state.json``. Used by callers that
        need to reason about state isolation between sessions.
        """
        if self.state_key:
            return f"{self.state_key}.provider_state.json"
        return ".provider_state.json"
    def _restore_state(self) -> None:
        """Load (or initialize) per-key router state.

        Fail-open: a missing/unreadable state file simply leaves the router in a
        fresh default state rather than crashing session startup.
        """
        try:
            path = self._state_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # Re-apply persisted failure counters so a resumed session keeps
                # its cooldowns/backoffs. Providers are matched by name.
                by_name = {p.name: p for p in self.providers}
                for name, info in (data.get("providers", {}) or {}).items():
                    p = by_name.get(name)
                    if p is not None and isinstance(info, dict):
                        if "failure_count" in info:
                            p.failure_count = int(info["failure_count"])
                        if "cooldown_until" in info:
                            p.cooldown_until = float(info["cooldown_until"])
                        if "enabled" in info:
                            p.enabled = bool(info["enabled"])
        except Exception:
            # Fail-open: never let state restore break provider routing.
            pass
    def set_state_key(self, key: str) -> None:
        self.state_key = key
        self._restore_state()
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
                rate = is_rate_limit(e)
                nf = is_not_found(e)
                p.record_failure(rate=rate, notfound=nf)
                print(f"[fallback] {p.name} {'RATE-LIMIT' if rate else '404' if nf else 'FAIL'} -> next")
                if rate and ("openrouter" in p.name.lower() or "OR-" in p.name):
                    # If free OR account is rate-limited, put all OR-* on 65s cooldown and jump straight to NVIDIA
                    for op in self.providers:
                        if "OR-" in op.name and op.is_available():
                            op.cooldown_until = time.time() + 65
                    continue
                continue
        raise RuntimeError(f"All failed: {last}")
    def generate_response(self, m, **kwargs): return "".join(self.generate_stream(m, **kwargs))

base_model = os.getenv("OPENROUTER_MODEL", "tencent/hunyuan-3:free")
FALLBACK_MODELS = [
    "tencent/hunyuan-3:free",  # الحارس المجاني الجديد والمستقر حالياً
    "google/gemini-2.5-flash:free",
    "google/gemma-2-9b-it",
]
FREE_FALLBACK = FALLBACK_MODELS


def handle_provider_fallback(exception_error: Exception) -> str:
    """حقن كفاءة التوجيه التلقائي البديل عند ارتداد NVIDIA أو OpenRouter بـ 404/429/502/504."""
    current_fallback = FALLBACK_MODELS[0]
    return current_fallback

providers = []
try:
    providers.append(ProviderState(name="OR-0", client=OpenRouterClient(model=base_model), priority=0))
except Exception:
    pass

if NvidiaClient:
    try:
        providers.append(ProviderState(name="NVIDIA", client=NvidiaClient(), priority=1))
    except Exception:
        pass

for i, mdl in enumerate(FREE_FALLBACK, start=2):
    try:
        providers.append(ProviderState(name=f"OR-{i}", client=OpenRouterClient(model=mdl), priority=i))
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
