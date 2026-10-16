"""Talk to a local Ollama daemon over its native HTTP API.

Deliberately written against the standard library: no SDK, no auth, no
retry-with-backoff-because-the-vendor-rate-limited-you. The whole client is
short enough to audit, which matters when the pitch is "your data stays here".
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

from ledgerlocal.errors import ProviderError

# Explicitly empty proxy config: a corporate http_proxy env var must never
# intercept a call we promised stays on this machine.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        vision_model: str = "qwen2.5vl:7b",
        text_model: str = "qwen2.5:7b",
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

    # -- public API -----------------------------------------------------

    def complete_text(self, prompt: str, *, system: str = "", schema: dict | None = None) -> str:
        return self._generate(self.text_model, prompt, [], system, schema)

    def complete_vision(
        self,
        prompt: str,
        images: Sequence[bytes],
        *,
        system: str = "",
        schema: dict | None = None,
    ) -> str:
        encoded = [base64.b64encode(image).decode("ascii") for image in images]
        return self._generate(self.vision_model, prompt, encoded, system, schema)

    def health(self) -> dict:
        try:
            tags = self._request("/api/tags", None, method="GET")
        except ProviderError as exc:
            return {"provider": self.name, "host": self.host, "reachable": False, "error": str(exc)}
        names = [model.get("name", "") for model in tags.get("models", [])]
        return {
            "provider": self.name,
            "host": self.host,
            "reachable": True,
            "models": names,
            "vision_model_present": _has_model(names, self.vision_model),
            "text_model_present": _has_model(names, self.text_model),
        }

    def pull_hint(self, model: str) -> str:
        return f"ollama pull {model}"

    # -- internals ------------------------------------------------------

    def _generate(
        self,
        model: str,
        prompt: str,
        images: list[str],
        system: str,
        schema: dict | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        }
        if system:
            payload["system"] = system
        if images:
            payload["images"] = images
        if schema:
            # Ollama enforces the schema during decoding, which is how a 7B
            # model reliably returns parseable JSON at all.
            payload["format"] = schema

        body = self._request("/api/generate", payload)
        answer = body.get("response")
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
            raise ProviderError(
                f"could not reach Ollama at {self.host} ({exc.reason}). "
                f"Start it with `ollama serve`."
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise ProviderError(f"request to {url} failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{url} returned a non-JSON body") from exc


def _has_model(available: list[str], wanted: str) -> bool:
    wanted_base = wanted.split(":")[0]
    return any(name == wanted or name.split(":")[0] == wanted_base for name in available)
