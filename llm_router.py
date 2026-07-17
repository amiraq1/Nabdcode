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
try:
    from core.llm import OrcaRouterClient
except Exception:
    OrcaRouterClient = None

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
    def _sorted(self): return [p for p in self.providers if p.is_available()]
    def generate_stream(self, messages, logger=None, **kwargs):
        available = self._sorted()
        if not available:
            # No provider is currently usable: either every provider is on
            # cooldown, was disabled by a 404 (model-not-found), or none were
            # configured at startup. Distinguish this from "all attempted and
            # failed" so the operator gets an actionable message instead of a
            # bare "All failed: None".
            disabled = [p.name for p in self.providers if not p.enabled]
            cooled = [
                p.name for p in self.providers
                if p.enabled and time.time() < p.cooldown_until
            ]
            if disabled:
                detail = (
                    f"all providers disabled (model-not-found or config error): "
                    f"{', '.join(disabled)}"
                )
            elif cooled:
                detail = (
                    f"all providers on cooldown (retry after "
                    f"{max(int(p.cooldown_until - time.time()) for p in self.providers if p.enabled)}s): "
                    f"{', '.join(cooled)}"
                )
            else:
                detail = "no providers configured"
            raise RuntimeError(f"All failed: {detail}")
        last = None
        for p in available:
            try:
                res = p.client.generate_response(messages, **kwargs)
                p.record_success()
                yield res
                return
            except Exception as e:
                last = e
                err_text = str(e) if str(e) else repr(e)
                # 🚨 [الانسحاب التكتيكي والتوجيه الذكي]: عند انتهاء الرصيد 402، نعطل سلسلة المزود الحالي وننتقل فوراً للبدائل (DeepSeek/NVIDIA)
                if "402" in err_text or "Insufficient credits" in err_text or "payment required" in err_text.lower():
                    is_openrouter = p.name.startswith("OR-") or "openrouter" in p.name.lower()
                    is_orca = p.name.startswith("ORCA") or "orca" in p.name.lower()
                    
                    for op in self.providers:
                        if is_openrouter and (op.name.startswith("OR-") or "openrouter" in op.name.lower()):
                            op.enabled = False
                        elif is_orca and (op.name.startswith("ORCA") or "orca" in op.name.lower()):
                            op.enabled = False
                    
                    log_msg = f"[LLM Router] ⚠️ Credits depleted (HTTP 402) on provider '{p.name}'. Disabling depleted chain and transitioning to next fallback..."
                    if logger is not None:
                        logger.warning(log_msg)
                        flush = getattr(logger, "flush", None)
                        if callable(flush):
                            try:
                                flush()
                            except Exception:
                                pass
                    else:
                        import logging as _logging
                        _logging.warning(log_msg)
                    
                    if any(op.is_available() for op in self.providers):
                        continue
                    raise RuntimeError("Task aborted: OpenRouter credits depleted.") from e
                rate = is_rate_limit(e)
                nf = is_not_found(e)
                p.record_failure(rate=rate, notfound=nf)
                # Route provider fallback through the caller's logger instead of
                # printing raw text to stdout (which pollutes the REPL UI). When
                # no logger is supplied (e.g. isolated unit tests) fall back to
                # the stdlib root logger so output stays decoupled but visible.
                err_text = str(e) if str(e) else repr(e)
                log_msg = (
                    f"[LLM Router Fallback] Provider '{p.name}' failed"
                    f"{' (rate-limited)' if rate else ' (model not found)' if nf else ''}"
                    f": {err_text}. Transitioning to next provider..."
                )
                if logger is not None:
                    logger.warning(log_msg)
                    # Best-effort immediate flush so the session log reflects the
                    # failure even if the process is killed moments later. The
                    # Logger wrapper exposes flush(); stdlib loggers flush too.
                    flush = getattr(logger, "flush", None)
                    if callable(flush):
                        try:
                            flush()
                        except Exception:
                            pass
                else:
                    import logging as _logging
                    _logging.warning(log_msg)
                if rate and ("openrouter" in p.name.lower() or "OR-" in p.name):
                    # If free OR account is rate-limited, put all OR-* on 65s cooldown and jump straight to NVIDIA
                    for op in self.providers:
                        if "OR-" in op.name and op.is_available():
                            op.cooldown_until = time.time() + 65
                    continue
                continue
        raise RuntimeError(f"All failed: {str(last) if last is not None else 'no providers attempted'}")
    def generate_response(self, m, logger=None, **kwargs):
        return "".join(self.generate_stream(m, logger=logger, **kwargs))

base_model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-free")
FALLBACK_MODELS = [
    "deepseek/deepseek-v4-flash-free",        # فلاش مجاني وسريع جداً من Orca/OpenRouter
    "deepseek/deepseek-v4-pro-free",          # برو مجاني عالي الدقة من Orca/OpenRouter
    "google/gemini-2.5-flash",                # سريع جداً وممتاز للاستنتاج
    "meta-llama/llama-3.1-8b-instruct:free",  # مستقر جداً للأوامر
    "mistralai/mistral-nemo:free",            # خفيف وسريع
    "microsoft/phi-3-mini-128k-instruct:free" # رائع للسياقات الطويلة
]
FREE_FALLBACK = FALLBACK_MODELS


def handle_provider_fallback(exception_error: Exception) -> str:
    """حقن كفاءة التوجيه التلقائي البديل عند ارتداد NVIDIA أو OpenRouter أو Orca بـ 404/429/502/504."""
    current_fallback = FALLBACK_MODELS[0]
    return current_fallback

providers = []
# 1. Vanguard: OrcaRouter DeepSeek models (#1 & #2)
if OrcaRouterClient:
    try:
        providers.append(ProviderState(name="ORCA-FLASH", client=OrcaRouterClient(model="deepseek/deepseek-v4-flash-free"), priority=0))
        providers.append(ProviderState(name="ORCA-PRO", client=OrcaRouterClient(model="deepseek/deepseek-v4-pro-free"), priority=1))
    except Exception:
        pass

# 2. OpenRouter primary base model
try:
    providers.append(ProviderState(name="OR-0", client=OpenRouterClient(model=base_model), priority=2))
except Exception:
    pass

# 3. NVIDIA fallback
if NvidiaClient:
    try:
        providers.append(ProviderState(name="NVIDIA", client=NvidiaClient(), priority=3))
    except Exception:
        pass

# 4. OpenRouter/Orca multi-provider fallback loop
for i, mdl in enumerate(FREE_FALLBACK, start=4):
    try:
        client_cls = OrcaRouterClient if ("deepseek" in mdl or "orca" in mdl) and OrcaRouterClient else OpenRouterClient
        name_prefix = "ORCA" if client_cls == OrcaRouterClient else "OR"
        providers.append(ProviderState(name=f"{name_prefix}-{i}", client=client_cls(model=mdl), priority=i))
    except Exception:
        pass

router = ProviderRouter(providers)

def execute_agent_with_memory(state_or_messages: Any, logger=None, **kwargs: Any) -> str:
    if isinstance(state_or_messages, list):
        messages = state_or_messages
    elif hasattr(state_or_messages, "messages"):
        messages = state_or_messages.messages
    elif isinstance(state_or_messages, dict) and "messages" in state_or_messages:
        messages = state_or_messages["messages"]
    else:
        messages = str(state_or_messages)
    return router.generate_response(messages, logger=logger, **kwargs)
