"""The seam that makes the model swappable.

Every provider implements the same three methods, so changing from Ollama to
llama.cpp to vLLM to a fine-tune of your own is a config line, not a rewrite.
This indirection is cheap here precisely because the models are open: they all
speak either the Ollama API or an OpenAI-compatible one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Provider(Protocol):
    name: str

    def complete_text(self, prompt: str, *, system: str = "", schema: dict | None = None) -> str:
        """Return the model's raw answer to a text-only prompt."""

    def complete_vision(
        self,
        prompt: str,
        images: Sequence[bytes],
        *,
        system: str = "",
        schema: dict | None = None,
    ) -> str:
        """Return the model's raw answer to a prompt about ``images`` (PNG bytes)."""

    def health(self) -> dict:
        """Describe the runtime: reachable, which models are present."""
