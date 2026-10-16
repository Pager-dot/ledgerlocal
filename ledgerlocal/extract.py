"""The extraction pipeline: render, ask the local model, validate, repair once.

The shape of this file is the project's central bet. A 7B open-weight model run
on a laptop is cheaper and more private than a frontier API, and slightly less
reliable per call. We close that gap not with a bigger model but with structure:
schema-constrained decoding, deterministic parsing, arithmetic audits, and one
targeted repair attempt. The result is good enough to bill from, and it costs
nothing per document, so re-running the whole archive after a prompt change is
free.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ledgerlocal import prompts
from ledgerlocal.config import Config
from ledgerlocal.errors import ExtractionError
from ledgerlocal.models import Extraction
from ledgerlocal.providers.base import Provider
from ledgerlocal.render import Rendered, render

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass
class Result:
    path: Path
    digest: str
    extraction: Extraction
    pages: int
    used_vision: bool
    attempts: int
    raw: str


def parse_model_json(answer: str) -> dict:
    """Pull a JSON object out of a model answer that may be wrapped in prose.

    Schema-constrained decoding usually makes this unnecessary. Usually.
    """
    text = answer.strip()
    if not text:
        raise ExtractionError("model returned nothing")

    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ExtractionError(f"no JSON object in model answer: {answer[:200]!r}") from None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"model answer was not valid JSON: {exc}") from exc

    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ExtractionError("model answer was JSON, but not an object")
    return payload


def extract_document(
    path: Path,
    provider: Provider,
    config: Config,
    *,
    prepared: Rendered | None = None,
) -> Result:
    """Read one document and return a validated :class:`Result`."""
    prepared = prepared or render(path, max_pages=config.max_pages, dpi=config.render_dpi)
    schema = prompts.EXTRACTION_SCHEMA
    schema_text = json.dumps(schema, indent=2)

    if prepared.is_visual:
        page_note = "page" if len(prepared.images) == 1 else f"{len(prepared.images)} pages"
        prompt = prompts.VISION_PROMPT.format(page_note=page_note, schema=schema_text)
        ask = lambda text: provider.complete_vision(  # noqa: E731
            text, prepared.images, system=prompts.SYSTEM, schema=schema
        )
    else:
        prompt = prompts.TEXT_PROMPT.format(schema=schema_text, document=prepared.text)
        ask = lambda text: provider.complete_text(  # noqa: E731
            text, system=prompts.SYSTEM, schema=schema
        )

    answer = ask(prompt)
    attempts = 1
    try:
        extraction = Extraction.from_raw(parse_model_json(answer), config.date_order)
        problem = _blocking_problem(extraction)
    except ExtractionError as exc:
        extraction, problem = None, str(exc)

    if problem is not None:
        # One repair pass, with the specific complaint. Free to attempt, since
        # there is no per-token bill and no rate limit on our own hardware.
        attempts = 2
        repaired = ask(
            prompts.REPAIR_PROMPT.format(problem=problem, previous=answer[:2000], schema=schema_text)
        )
        try:
            candidate = Extraction.from_raw(parse_model_json(repaired), config.date_order)
        except ExtractionError:
            candidate = None
        if candidate is not None and (extraction is None or _score(candidate) >= _score(extraction)):
            extraction, answer = candidate, repaired

    if extraction is None:
        raise ExtractionError(f"{path.name}: the model never returned a usable document")

    if not extraction.currency:
        extraction.currency = config.default_currency
    if extraction.confidence < config.review_threshold:
        extraction.warnings.append(f"low model confidence ({extraction.confidence:.2f})")

    return Result(
        path=path,
        digest=prepared.digest,
        extraction=extraction,
        pages=prepared.page_count,
        used_vision=prepared.is_visual,
        attempts=attempts,
        raw=answer,
    )


def _blocking_problem(extraction: Extraction) -> str | None:
    """Only things worth spending a second model call on."""
    missing = [
        label
        for label, value in (
            ("vendor", extraction.vendor),
            ("issue_date", extraction.issue_date),
            ("total", extraction.total),
        )
        if not value
    ]
    if missing:
        return f"these required fields were missing or empty: {', '.join(missing)}"
    arithmetic = [w for w in extraction.warnings if "differs from" in w]
    if arithmetic:
        return "; ".join(arithmetic) + ". Re-read the amounts on the document."
    return None


def _score(extraction: Extraction) -> int:
    """Crude completeness score, used to pick between two candidate answers."""
    filled = sum(
        1
        for value in (
            extraction.vendor,
            extraction.issue_date,
            extraction.total,
            extraction.subtotal,
            extraction.tax,
            extraction.invoice_number,
        )
        if value
    )
    return filled * 2 - len(extraction.warnings)
