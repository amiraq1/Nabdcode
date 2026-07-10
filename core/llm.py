from __future__ import annotations

import os
for _env_path in [os.path.join(os.path.expanduser("~"), ".env"), ".env"]:
    if os.path.exists(_env_path):
        try:
            with open(_env_path, "r", encoding="utf-8") as _ef:
                for _line in _ef:
                    _line=_line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k,_v=_line.split("=",1)
                        _k=_k.strip()
                        _v=_v.strip().strip("'").strip('"')
                        if _k and not os.getenv(_k):
                            os.environ[_k]=_v
        except Exception:
            pass



import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from core.sanitize import sanitize

DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")


@dataclass(slots=True)
class OpenRouterConfig:
    timeout: int = 300
    max_retries: int = 3
    temperature: float = 0.1
    max_tokens: int = 4000
    top_p: float = 1.0
    referer: str = os.getenv("NABD_REFERER", "https://localhost/nabd")
    title: str = "Nabd Agent OS"


class OpenRouterError(RuntimeError):
    pass


class AuthenticationError(OpenRouterError):
    pass


class RateLimitError(OpenRouterError):
    pass


class ServerError(OpenRouterError):
    pass


class OpenRouterClient:

    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        config: OpenRouterConfig | None = None,
    ):

        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("NVIDIA_API_KEY")
        self.model = model
        self.config = config or OpenRouterConfig()

    @property
    def headers(self) -> dict[str, str]:
        api_key = self.api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise AuthenticationError(
                "OPENROUTER_API_KEY environment variable is missing."
            )

        return {
            "Authorization": f"Bearer {api_key}",
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
            self.BASE_URL,
            headers=self.headers,
            data=body,
            method="POST",
        )

        delay = 1

        for attempt in range(self.config.max_retries):

            try:

                with urllib.request.urlopen(
                    request,
                    timeout=self.config.timeout,
                ) as response:

                    data = json.loads(
                        response.read().decode("utf-8")
                    )

                    choices = data.get("choices")

                    if not choices:
                        raise OpenRouterError(
                            "No choices returned."
                        )

                    message = choices[0].get("message", {})

                    content = message.get("content")

                    if content is None:
                        raise OpenRouterError(
                            "Empty model response."
                        )

                    return sanitize(content)

            except urllib.error.HTTPError as e:

                body = e.read().decode("utf-8", "ignore")

                if e.code == 401:
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


class LocalClient:

    def __init__(self, config: LocalConfig | None = None):

        self.config = config or LocalConfig()

        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer local",
            "User-Agent": self.config.user_agent,
            **self.config.extra_headers,
        }

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:

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
            self.config.base_url,
            headers=self.headers,
            method="POST",
            data=body,
        )

        last_error = None

        for attempt in range(self.config.retries + 1):

            try:

                with urllib.request.urlopen(
                    request,
                    timeout=self.config.timeout,
                ) as response:

                    if response.status != 200:
                        raise RuntimeError(
                            f"HTTP {response.status}"
                        )

                    raw = response.read()

                    if not raw:
                        raise RuntimeError(
                            "Local model returned empty body."
                        )

                    return json.loads(raw.decode("utf-8"))

            except urllib.error.HTTPError as exc:

                detail = exc.read().decode(
                    "utf-8",
                    errors="ignore",
                )

                raise RuntimeError(
                    f"HTTP {exc.code}: {detail}"
                ) from exc

            except urllib.error.URLError as exc:

                last_error = exc

                if attempt >= self.config.retries:
                    break

                time.sleep(
                    self.config.retry_delay * (attempt + 1)
                )

            except TimeoutError as exc:

                last_error = exc

                if attempt >= self.config.retries:
                    break

                time.sleep(
                    self.config.retry_delay * (attempt + 1)
                )

            except Exception as exc:

                raise RuntimeError(
                    f"Local LLM Failure: {exc}"
                ) from exc

        raise RuntimeError(
            f"Unable to reach local server ({last_error})"
        )

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:

        choices = response.get("choices")

        if not isinstance(choices, list) or not choices:
            raise RuntimeError(
                "Response contains no choices."
            )

        message = choices[0].get("message")

        if not isinstance(message, dict):
            raise RuntimeError(
                "Response contains invalid message."
            )

        content = message.get("content")

        if not isinstance(content, str):
            raise RuntimeError(
                "Model returned empty content."
            )

        return sanitize(content.strip())

    def generate_response(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:

        payload = self._build_payload(
            messages,
            **kwargs,
        )

        response = self._post(payload)

        return self._extract_content(response)

    def health_check(self) -> bool:

        try:

            self.generate_response(
                [
                    {
                        "role": "user",
                        "content": "ping",
                    }
                ],
                max_tokens=1,
            )

            return True

        except Exception:

            return False

    # ── Streaming (SSE) ──────────────────────────────────────────────────

    def generate_stream(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Send a streaming request and accumulate the full response.

        Emits bus events for each token chunk.
        Yields the full accumulated response string.
        """
        payload = self._build_payload(messages, **kwargs)
        # Force stream=True for this code path
        payload["stream"] = True

        body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            self.config.base_url,
            headers=self.headers,
            method="POST",
            data=body,
        )

        from engine.events import bus

        accumulated: list[str] = []

        try:
            with urllib.request.urlopen(request, timeout=self.config.connect_timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    # SSE: "data: ..."
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
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Stream connection failed: {exc.reason}") from exc

        full_text = sanitize("".join(accumulated).strip())
        if not full_text:
            raise RuntimeError("Stream returned empty response")

        return full_text


class NvidiaClient:
    BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "meta/llama-3.1-70b-instruct",
        timeout: int = 60,
    ):
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        self.model = os.getenv("NVIDIA_MODEL", model)
        self.timeout = timeout

    def generate_response(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        api_key = self.api_key or os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise AuthenticationError("NVIDIA_API_KEY environment variable is missing.")

        headers = {
            "Authorization": f"Bearer {api_key}",
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
