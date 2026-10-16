"""An OpenAI-shaped local server: llama.cpp, vLLM, LM Studio, text-generation-webui.

Same interface as the Ollama provider, so switching runtimes is one config
line. Note that no API key is read from the environment and none is sent: this
client is only ever pointed at something on your own machine.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

from ledgerlocal.errors import ProviderError

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(
        self,
        host: str = "http://127.0.0.1:8080",
        vision_model: str = "local-model",
        text_model: str = "local-model",
        *,
        timeout: float = 240.0,
        temperature: float = 0.0,
        num_ctx: int = 8192,
    ) -> None:
        self.host = host.rstrip("/")
        self.vision_model = vision_model
        self.text_model = text_model
        self.timeout = timeout
        self.temperature = temperature
        self.num_ctx = num_ctx

    def complete_text(self, prompt: str, *, system: str = "", schema: dict | None = None) -> str:
        return self._chat(self.text_model, [{"type": "text", "text": prompt}], system, schema)

    def complete_vision(
        self,
        prompt: str,
        images: Sequence[bytes],
        *,
        system: str = "",
        schema: dict | None = None,
    ) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            encoded = base64.b64encode(image).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
            )
        return self._chat(self.vision_model, content, system, schema)

    def health(self) -> dict:
        try:
            body = self._request("/v1/models", None, method="GET")
        except ProviderError as exc:
            return {"provider": self.name, "host": self.host, "reachable": False, "error": str(exc)}
        names = [entry.get("id", "") for entry in body.get("data", [])]
        return {"provider": self.name, "host": self.host, "reachable": True, "models": names}

    def pull_hint(self, model: str) -> str:
        return f"load {model} in your local server"

    def _chat(self, model: str, content: list[dict], system: str, schema: dict | None) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "schema": schema, "strict": False},
            }

        body = self._request("/v1/chat/completions", payload)
        try:
            answer = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected response shape from {self.host}") from exc
        if not isinstance(answer, str) or not answer.strip():
            raise ProviderError(f"{model} returned an empty response")
        return answer

    def _request(self, path: str, payload: dict | None, *, method: str = "POST") -> dict:
        url = f"{self.host}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with _opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ProviderError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"could not reach a local server at {self.host} ({exc.reason})") from exc
        except (TimeoutError, OSError) as exc:
            raise ProviderError(f"request to {url} failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{url} returned a non-JSON body") from exc
