from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from core.sanitize import sanitize
from core.config import ConfigManager
import core._env  # auto-load .env variables

logger = logging.getLogger("nabd.llm")


class PostPreservingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    معالج مخصص يمنع urllib من تحويل طلبات POST إلى GET عند مواجهة 
    إعادة توجيه (301, 302, 307, 308)، ويحافظ على الحمولة (Payload).
    """
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if req.get_method() == "POST" and code in (301, 302, 303, 307, 308):
            new_req.method = "POST"
            new_req.data = req.data
            if req.has_header("Content-type"):
                new_req.add_unredirected_header("Content-Type", req.get_header("Content-type"))
            elif req.has_header("Content-Type"):
                new_req.add_unredirected_header("Content-Type", req.get_header("Content-Type"))
        return new_req


# تنشيط المعالج المضاد للرصاص عالمياً في جميع استدعاءات urllib.request
urllib.request.install_opener(urllib.request.build_opener(PostPreservingRedirectHandler()))

DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")


# ── Provider configuration ─────────────────────────────────────────────────

@dataclass(slots=True)
class OpenRouterConfig:
    timeout: int = 300
    max_retries: int = 3
    temperature: float = 0.1
    max_tokens: int = 4000
    top_p: float = 1.0
    referer: str = os.getenv("NABD_REFERER", "https://localhost/nabd")
    title: str = "Nabd Agent OS"


@dataclass(slots=True)
class LocalConfig:
    base_url: str = "http://127.0.0.1:8080/v1/chat/completions"
    model: str = ""
    timeout: int = 15
    connect_timeout: float = 3.0  # first-byte timeout before failover
    temperature: float = 0.1
    max_tokens: int = 2048
    top_p: float = 0.95
    stream: bool = False
    retries: int = 1
    retry_delay: float = 0.5
    user_agent: str = "Nabd-AgentOS/2.0"
    extra_headers: dict[str, str] = field(default_factory=dict)


# ── Errors ─────────────────────────────────────────────────────────────────

class OpenRouterError(RuntimeError):
    pass


class AuthenticationError(OpenRouterError):
    pass


class RateLimitError(OpenRouterError):
    pass


class ServerError(OpenRouterError):
    pass


class MissingAPIKeyError(OpenRouterError):
    """Raised when no API key can be resolved for a provider.

    Distinguishes a missing/invalid credential from generic runtime errors so
    callers (and the CLI) can show a user-friendly, actionable message instead
    of a generic traceback.
    """


# ── Unified, config-first, lazy key resolution ─────────────────────────────

_PROVIDER_ENV_VARS: dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY", "ORCAROUTER_API_KEY", "AGENTROUTER_API_KEY", "NVIDIA_API_KEY"),
    "orcarouter": ("ORCAROUTER_API_KEY", "OPENROUTER_API_KEY"),
    "nvidia": ("NVIDIA_API_KEY",),
}


def _resolve_api_key(provider_name: str, api_key: str | None = None) -> str:
    """Resolve an LLM provider API key via a Config-First flow.

    Resolution order:
        1. Explicit ``api_key`` argument (highest precedence for injection/tests).
        2. Environment variables associated with ``provider_name``.
        3. Persistent config (``ConfigManager``), prompting interactively when
           absent and stdin is interactive.

    Args:
        provider_name: Logical provider key (e.g. ``"openrouter"``, ``"nvidia"``).
        api_key: Optional pre-supplied key; short-circuits all other sources.

    Returns:
        The resolved API key string.

    Raises:
        MissingAPIKeyError: If no key can be resolved from any source.
    """
    env_vars = _PROVIDER_ENV_VARS.get(provider_name, ())

    if api_key:
        logger.debug("API key for %s supplied explicitly.", provider_name)
        return api_key

    for env_var in env_vars:
        value = os.getenv(env_var)
        if value:
            logger.debug("Fetched API key for %s from env (%s).", provider_name, env_var)
            return value

    logger.debug("No env key for %s; checking persistent config.", provider_name)
    try:
        key = ConfigManager().get_or_prompt_api_key(provider=provider_name)
    except ValueError:
        key = None

    if key:
        logger.debug("Fetched API key for %s from persistent config.", provider_name)
        return key

    tried = ", ".join(env_vars) if env_vars else "(none configured)"
    raise MissingAPIKeyError(
        f"No API key found for provider '{provider_name}'. "
        f"Checked environment variables: {tried}. "
        "Set one, or run the CLI to be prompted interactively."
    )


# ── OpenRouter client ──────────────────────────────────────────────────────

class OpenRouterClient:
    BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        config: OpenRouterConfig | None = None,
        base_url: str | None = None,
    ) -> None:
        # Key is intentionally NOT resolved at construction time: this keeps
        # module import / client instantiation cheap (responsive --help). The
        # real lookup happens lazily on first network use.
        self._api_key: str | None = api_key
        self.model = model
        self.config = config or OpenRouterConfig()
        self.base_url = base_url or os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")

    @property
    def api_key(self) -> str:
        """Lazily resolve the OpenRouter key (Env -> Config -> prompt)."""
        if self._api_key is None:
            self._api_key = _resolve_api_key("openrouter", self._api_key)
        return self._api_key

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.config.referer,
            "X-Title": self.config.title,
            "User-Agent": "NabdAgent/1.0",
        }

    def _payload(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        model = self.model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
        }
        payload.update(kwargs)
        return payload

    def generate_response(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        payload = self._payload(messages, **kwargs)
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url,
            headers=self.headers,
            data=body,
            method="POST",
        )
        delay = 1
        for attempt in range(self.config.max_retries):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    choices = data.get("choices")
                    if not choices:
                        raise OpenRouterError("No choices returned.")
                    message = choices[0].get("message", {})
                    content = message.get("content")
                    # Native function-calling: if the provider returns structured
                    # tool_calls, normalize to the canonical {"tool":name,"args":args}
                    # text form so the rest of the pipeline (parser/verifier) is
                    # unchanged. This is the primary path; XML/JSON text parsing
                    # remains a fallback for providers without FC support.
                    tool_calls = message.get("tool_calls")
                    if tool_calls:
                        fc = (tool_calls[0] or {}).get("function", {}) or {}
                        _name = fc.get("name", "") or ""
                        _raw = fc.get("arguments", "{}")
                        try:
                            _args = json.loads(_raw) if isinstance(_raw, str) else (_raw or {})
                        except (json.JSONDecodeError, TypeError):
                            _args = {}
                        return json.dumps({"tool": _name, "args": _args}, ensure_ascii=False)
                    if content is None:
                        raise OpenRouterError("Empty model response.")
                    return sanitize(content)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")
                if e.code == 401:
                    # Refresh the resolved key on auth failure for clearer error.
                    raise AuthenticationError(body)
                if e.code == 429:
                    if attempt + 1 < self.config.max_retries:
                        time.sleep(delay)
                        delay *= 2
                        continue
                    raise RateLimitError(body)
                if e.code >= 500:
                    if attempt + 1 < self.config.max_retries:
                        time.sleep(delay)
                        delay *= 2
                        continue
                    raise ServerError(body)
                raise OpenRouterError(body)
            except urllib.error.URLError as e:
                if attempt + 1 < self.config.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise OpenRouterError(str(e.reason))
        raise OpenRouterError("Maximum retries exceeded.")


# ── Local (in-process) client ──────────────────────────────────────────────

class LocalClient:
    def __init__(self, config: LocalConfig | None = None) -> None:
        self.config = config or LocalConfig()
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer local",
            "User-Agent": self.config.user_agent,
            **self.config.extra_headers,
        }

    def _build_payload(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        payload = {
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
            "stream": self.config.stream,
        }
        if self.config.model:
            payload["model"] = self.config.model
        payload.update(kwargs)
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            headers=self.headers,
            method="POST",
            data=body,
        )
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                opener = urllib.request.build_opener(PostPreservingRedirectHandler())
                with opener.open(request, timeout=self.config.timeout) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}")
                    raw = response.read()
                    if not raw:
                        raise RuntimeError("Local model returned empty body.")
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt >= self.config.retries:
                    break
                time.sleep(self.config.retry_delay * (attempt + 1))
            except TimeoutError as exc:
                last_error = exc
                if attempt >= self.config.retries:
                    break
                time.sleep(self.config.retry_delay * (attempt + 1))
            except Exception as exc:
                raise RuntimeError(f"Local LLM Failure: {exc}") from exc
        raise RuntimeError(f"Unable to reach local server ({last_error})")

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Response contains no choices.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Response contains invalid message.")
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Model returned empty content.")
        return sanitize(content.strip())

    def generate_response(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        payload = self._build_payload(messages, **kwargs)
        response = self._post(payload)
        return self._extract_content(response)

    def health_check(self) -> bool:
        try:
            self.generate_response([{"role": "user", "content": "ping"}], max_tokens=1)
            return True
        except Exception:
            return False

    def generate_stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        """Send a streaming request and accumulate the full response.

        Emits bus events for each token chunk; yields the full accumulated
        response string.
        """
        payload = self._build_payload(messages, **kwargs)
        payload["stream"] = True  # Force stream=True for this code path
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            headers=self.headers,
            method="POST",
            data=body,
        )
        from core.kernel.events import bus

        accumulated: list[str] = []
        STREAM_READ_TIMEOUT = 60.0
        try:
            opener = urllib.request.build_opener(PostPreservingRedirectHandler())
            with opener.open(request, timeout=STREAM_READ_TIMEOUT) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            try:
                                chunk = json.loads(sanitize(data_str, strip_control=False))
                            except json.JSONDecodeError:
                                continue
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = sanitize(delta.get("content", ""))
                        if content:
                            accumulated.append(content)
                            bus.emit("llm_token", {"token": content})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 429:
                raise RateLimitError(f"Local Server Rate Limit: {detail}")
            raise ServerError(f"Local Server Error ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise OpenRouterError(f"Local Server Unreachable: {exc.reason}") from exc
        full_text = sanitize("".join(accumulated).strip())
        if not full_text:
            raise RuntimeError("Stream returned empty response")
        return full_text


# ── OrcaRouter client ──────────────────────────────────────────────────────

class OrcaRouterClient(OpenRouterClient):
    BASE_URL = os.getenv("ORCAROUTER_BASE_URL", "https://www.orcarouter.ai/api/v1/chat/completions")

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        config: OpenRouterConfig | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            config=config,
            base_url=base_url or os.getenv("ORCAROUTER_BASE_URL", "https://www.orcarouter.ai/api/v1/chat/completions"),
        )

    @property
    def api_key(self) -> str:
        """Lazily resolve the OrcaRouter key (Env -> Config -> prompt)."""
        if self._api_key is None:
            self._api_key = _resolve_api_key("orcarouter", self._api_key)
        return self._api_key


# ── NVIDIA client ──────────────────────────────────────────────────────────

class NvidiaClient:
    BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "meta/llama-3.1-8b-instruct",
        timeout: int = 60,
    ) -> None:
        # Key resolved lazily; model is read from env at construction (cheap,
        # non-blocking) to preserve prior behavior.
        self._api_key: str | None = api_key
        self.model = os.getenv("NVIDIA_MODEL", model)
        self.timeout = timeout

    @property
    def api_key(self) -> str:
        """Lazily resolve the NVIDIA key (Env -> Config -> prompt)."""
        if self._api_key is None:
            self._api_key = _resolve_api_key("nvidia", self._api_key)
        return self._api_key

    def generate_response(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "NabdAgent/1.0",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.1),
            "max_tokens": kwargs.get("max_tokens", 4000),
        }
        request = urllib.request.Request(
            self.BASE_URL,
            headers=headers,
            data=json.dumps(payload).encode(),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if not content:
                raise RuntimeError("Empty response from NVIDIA API")
            return sanitize(content)


# ── Lazy factory ───────────────────────────────────────────────────────────

def get_llm_client(provider: str = "openrouter", **kwargs: Any) -> OpenRouterClient | OrcaRouterClient | NvidiaClient:
    """Lazily construct an LLM client without resolving keys at call time.

    The returned client defers key resolution until its first network call,
    keeping CLI startup (e.g. ``--help``) fast and non-blocking.

    Args:
        provider: ``"openrouter"``, ``"orcarouter"``, or ``"nvidia"``.
        **kwargs: Forwarded to the underlying client constructor.

    Returns:
        An instantiated client whose API key is resolved on first use.
    """
    if provider == "nvidia":
        logger.debug("Constructing lazy NvidiaClient.")
        return NvidiaClient(**kwargs)
    elif provider == "orcarouter":
        logger.debug("Constructing lazy OrcaRouterClient.")
        return OrcaRouterClient(**kwargs)
    logger.debug("Constructing lazy OpenRouterClient.")
    return OpenRouterClient(**kwargs)


def get_secure_model(model_id: str = "gemini/gemini-1.5-pro") -> Any:
    """Return a secure model instance for agent initialization."""
    from smolagents import LiteLLMModel
    return LiteLLMModel(model_id=model_id)
