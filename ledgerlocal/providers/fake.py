"""A deterministic provider, so the test suite needs no GPU and no download.

It is also how you develop against this codebase on a plane.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

DEFAULT_ANSWER = {
    "kind": "receipt",
    "vendor": "Fake Vendor Ltd",
    "issue_date": "2026-03-14",
    "currency": "USD",
    "subtotal": "100.00",
    "tax": "8.50",
    "total": "108.50",
    "confidence": 0.9,
    "line_items": [{"description": "Widget", "quantity": "1", "unit_price": "100.00", "amount": "100.00"}],
}


class FakeProvider:
    name = "fake"

    def __init__(self, answers: Sequence[str] | None = None) -> None:
        self.answers = list(answers) if answers else [json.dumps(DEFAULT_ANSWER)]
        self.calls: list[dict] = []

    def _next(self, kind: str, prompt: str) -> str:
        self.calls.append({"kind": kind, "prompt": prompt})
        index = min(len(self.calls) - 1, len(self.answers) - 1)
        return self.answers[index]

    def complete_text(self, prompt: str, *, system: str = "", schema: dict | None = None) -> str:
        return self._next("text", prompt)

    def complete_vision(self, prompt, images, *, system: str = "", schema: dict | None = None) -> str:
        return self._next("vision", prompt)

    def health(self) -> dict:
        return {"provider": "fake", "reachable": True, "models": ["fake"]}
