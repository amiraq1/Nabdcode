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
    def generate_token_stream(self, messages, logger=None, **kwargs):
        """Yield individual token deltas from the best available provider.

        Uses ``client.stream()`` when available (token-level SSE). Falls back to
        yielding the full response as a single delta. Follows the same
        provider-priority / cooldown / failover pattern as ``generate_stream()``.
        """
        available = self._sorted()
        if not available:
            # Mirror the actionable "all unavailable" messaging from
            # generate_stream() so operators get a clear reason instead of a
            # bare RuntimeError.
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
        for p in available:
            try:
                if hasattr(p.client, "stream"):
                    gen = p.client.stream(messages, **kwargs)
                    for delta in gen:
                        yield delta
                    p.record_success()
                    return  # streaming succeeded
                else:
                    # Client doesn't support streaming — yield full response as one chunk
                    res = p.client.generate_response(messages, **kwargs)
                    yield {"content": res}
                    p.record_success()
                    return
            except Exception as e:
                rate = is_rate_limit(e)
                nf = is_not_found(e)
                p.record_failure(rate=rate, notfound=nf)
                log_msg = f"[Stream] Provider '{p.name}' failed: {e}"
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
                continue
        # All providers failed — raise the last error
        raise RuntimeError("All providers failed for streaming")

    def cheapest_model(self) -> str:
        """Return the lowest-priority (cheapest) model name.

        Used by the subagent ``task`` tool to delegate work to a cheaper
        model. Prefers the lowest-priority configured provider; falls back to
        the last ``FALLBACK_MODELS`` entry when no providers are registered.
        """
        if not self.providers:
            return FALLBACK_MODELS[-1]
        last = sorted(self.providers, key=lambda p: p.priority)[-1]
        return getattr(last.client, "model", None) or FALLBACK_MODELS[-1]

    def generate_response(self, m, logger=None, **kwargs):
        return "".join(self.generate_stream(m, logger=logger, **kwargs))

base_model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
FALLBACK_MODELS = [
    "deepseek/deepseek-v4-flash",        # فلاش مجاني وسريع جداً من Orca/OpenRouter
    "deepseek/deepseek-v4-pro",          # برو مجاني عالي الدقة من Orca/OpenRouter
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
# Phase F: if OPENROUTER_MODEL is explicitly set to a non-default model,
# use that model as the PRIMARY provider (priority 0) instead of forcing ORCA-FLASH.
# This ensures the banner and actual model match what the user configured.
_env_model = os.getenv("OPENROUTER_MODEL", "")
_is_default = not _env_model or _env_model in ("deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash-free")

if not _is_default:
    # Non-default model → use it as primary with OpenRouterClient.
    try:
        providers.append(ProviderState(name=f"OR-0:{_env_model.split('/')[-1]}", client=OpenRouterClient(model=_env_model), priority=0))
    except Exception:
        pass

# 1. Vanguard: OrcaRouter DeepSeek models (#1 & #2) — only when default or no explicit override.
if OrcaRouterClient and _is_default:
    try:
        providers.append(ProviderState(name="ORCA-FLASH", client=OrcaRouterClient(model="deepseek/deepseek-v4-flash"), priority=0 if _is_default else 10))
        providers.append(ProviderState(name="ORCA-PRO", client=OrcaRouterClient(model="deepseek/deepseek-v4-pro"), priority=1 if _is_default else 11))
    except Exception:
        pass

# 2. OpenRouter primary base model (fallback when ORCA is available, primary otherwise)
try:
    _or0_priority = 0 if (not _is_default and not any(p.priority == 0 for p in providers)) else (2 if _is_default else 12)
    providers.append(ProviderState(name="OR-0", client=OpenRouterClient(model=base_model), priority=_or0_priority))
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


# ── Independent verifier router (Maker ≠ Checker, step6) ────────────────────
# A SEPARATE ProviderRouter instance, same provider (gemini-2.5-flash) but an
# isolated state_key so its circuit-breaker/cooldown state never couples to the
# main agent's routing. The verifier sees ONLY {goal, final_answer, evidence
# summary} — never the maker's full conversation memory — preserving checker
# independence (see phase6 spec R3).
verifier_providers = [
    ProviderState(
        name="VERIFIER",
        client=OpenRouterClient(model="google/gemini-2.5-flash"),
        priority=0,
    )
]
verifier_router = ProviderRouter(verifier_providers, state_key="verifier")


VERIFIER_SYSTEM_PROMPT = (
    "You are a STRICT, adversarial verification reviewer. Your ONLY job is to "
    "judge whether the agent's final answer is actually supported by the "
    "evidence it collected — NOT to be helpful, NOT to agree, NOT to give the "
    "benefit of the doubt.\n\n"
    "You will receive THREE things and NOTHING ELSE: (1) the original task/goal, "
    "(2) the agent's final answer, (3) a summary of the evidence records the "
    "agent collected. You do NOT see the agent's reasoning chain or chat "
    "history, so you cannot be biased by its self-assessment.\n\n"
    "REJECT the answer (fail) if ANY of these hold:\n"
    "  • It makes claims not directly backed by the evidence summary.\n"
    "  • The evidence is insufficient, vague, or consists only of listings/"
    "directory scans without reading actual source content.\n"
    "  • It goes off-topic or answers a different question than the goal.\n"
    "  • It is a raw tool call, a thought block, or non-substantive filler.\n"
    "  • It hedges/guesses file paths or APIs not present in the evidence.\n\n"
    "ACCEPT (pass) ONLY when the answer is concretely grounded in the supplied "
    "evidence and directly addresses the goal.\n\n"
    "Respond with STRICT JSON only, no prose:\n"
    '{"verdict": "pass" | "fail", "reasons": ["..."], "missing": ["..."]}\n'
    "verdict must be exactly \"pass\" or \"fail\". reasons = why you judged it. "
    "missing = evidence/criteria still absent (empty list if pass)."
)


def run_verifier_check(
    goal_prompt: str,
    final_answer: str,
    evidence_summary: str,
    logger=None,
    **kwargs: Any,
) -> str:
    """Run the independent checker LLM on a MINIMAL, isolated context.

    The checker receives ONLY {goal, final_answer, evidence_summary} — the
    maker's full conversation memory is deliberately NOT passed, so the checker
    cannot be biased by the maker's own self-assessment (Maker ≠ Checker).
    Temperature is forced to 0 for deterministic, non-lenient judgments.
    """
    user_content = (
        f"TASK/GOAL:\n{goal_prompt}\n\n"
        f"AGENT FINAL ANSWER:\n{final_answer}\n\n"
        f"EVIDENCE SUMMARY (collected records):\n{evidence_summary}"
    )
    messages = [
        {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    # Force deterministic, strict judgment regardless of caller kwargs.
    kwargs["temperature"] = 0
    return verifier_router.generate_response(messages, logger=logger, **kwargs)


class LiteLLMModel:
    """LiteLLM model wrapper compatible with Nabd Agent OS."""
    def __init__(self, model_id: str = "gemini/gemini-1.5-pro", **kwargs: Any) -> None:
        self.model_id = model_id
        self.kwargs = kwargs
        self._nvidia_client = None
        self._openrouter_client = None

    def _get_nvidia(self):
        if self._nvidia_client is None:
            if NvidiaClient is not None:
                self._nvidia_client = NvidiaClient()
            else:
                from core.llm import NvidiaClient as NV
                self._nvidia_client = NV()
        return self._nvidia_client

    def generate(self, task: str, **kwargs: Any) -> str:
        """Generate a response using the real LLM router."""
        if not task or not task.strip():
            return ""
        messages = [
            {"role": "system", "content": "You are a precise code and system analysis assistant. Read the user's request carefully and respond with a thorough analysis, using evidence from the available tools."},
            {"role": "user", "content": task},
        ]
        return self.chat(messages)

    def chat(self, messages: list[dict[str, Any]]) -> str:
        """Send a structured chat conversation to the LLM and return the response.

        Tries NVIDIA first (confirmed working), falls back to ProviderRouter chain.
        """
        if not messages:
            return ""
        errors = []

        # Convert tool messages to user messages for NVIDIA compatibility
        adapted = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "tool":
                adapted.append({"role": "user", "content": f"[Tool Result]\n{str(content)[:4000]}"})
            elif role == "assistant":
                adapted.append({"role": "assistant", "content": str(content)[:2000]})
            elif role in ("system", "user"):
                adapted.append({"role": role, "content": str(content)[:4000]})

        # Try NVIDIA first
        try:
            nv = self._get_nvidia()
            return nv.generate_response(adapted)
        except Exception as exc:
            errors.append(f"NVIDIA: {exc}")
            if logger is not None:
                logger.warning(f"NVIDIA failed, falling back to router: {exc}")

        # Fallback: ProviderRouter (OpenRouter chain)
        try:
            return execute_agent_with_memory(messages)
        except Exception as exc:
            errors.append(f"Router: {exc}")
            raise RuntimeError(f"All LLM backends failed: {'; '.join(errors)}")


def get_secure_model(model_id: str = "gemini/gemini-1.5-pro") -> Any:
    """Return a secure model instance for agent initialization."""
    return LiteLLMModel(model_id=model_id)
