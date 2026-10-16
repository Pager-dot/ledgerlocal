from __future__ import annotations

from ledgerlocal.config import Config
from ledgerlocal.errors import ConfigError
from ledgerlocal.providers.base import Provider
from ledgerlocal.providers.fake import FakeProvider
from ledgerlocal.providers.ollama import OllamaProvider
from ledgerlocal.providers.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "Provider",
    "FakeProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "build_provider",
]


def build_provider(config: Config) -> Provider:
    kind = config.provider.strip().lower()
    if kind == "fake":
        return FakeProvider()
    shared = {
        "host": config.host,
        "vision_model": config.vision_model,
        "text_model": config.text_model,
        "timeout": config.timeout,
        "temperature": config.temperature,
        "num_ctx": config.num_ctx,
    }
    if kind == "ollama":
        return OllamaProvider(**shared)
    if kind in {"openai-compatible", "openai", "llamacpp", "llama.cpp", "vllm", "lmstudio"}:
        return OpenAICompatibleProvider(**shared)
    raise ConfigError(
        f"unknown provider {config.provider!r}; expected one of: ollama, openai-compatible, fake"
    )
