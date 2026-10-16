"""Orchestration: folder in, sorted archive and a populated ledger out."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ledgerlocal.categorize import Ruleset
from ledgerlocal.config import Config
from ledgerlocal.errors import LedgerLocalError
from ledgerlocal.extract import Result, extract_document
from ledgerlocal.organize import apply_plan, plan_file
from ledgerlocal.providers.base import Provider
from ledgerlocal.render import digest_file, discover, render
from ledgerlocal.store import Store

Progress = Callable[[str, Path, str | None], None]


@dataclass
class Outcome:
    path: Path
    status: str  # ingested | skipped | failed
    result: Result | None = None
    filed_path: Path | None = None
    error: str = ""


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)

    def of(self, status: str) -> list[Outcome]:
        return [outcome for outcome in self.outcomes if outcome.status == status]

    @property
    def ingested(self) -> list[Outcome]:
        return self.of("ingested")

    @property
    def skipped(self) -> list[Outcome]:
        return self.of("skipped")

    @property
    def failed(self) -> list[Outcome]:
        return self.of("failed")

    @property
    def needs_review(self) -> list[Outcome]:
        return [
            outcome
            for outcome in self.ingested
            if outcome.result and outcome.result.extraction.needs_review
        ]


def ingest(
    paths: Iterable[Path],
    *,
    config: Config,
    provider: Provider,
    store: Store,
    rules: Ruleset | None = None,
    file_documents: bool = True,
    move: bool = False,
    reprocess: bool = False,
    recursive: bool = True,
    progress: Progress | None = None,
) -> Report:
    """Read every supported document under ``paths`` exactly once."""
    rules = rules or Ruleset.default()
    report = Report()

    for target in _collect(paths, recursive=recursive):
        try:
            digest = digest_file(target)
            if store.has(digest) and not reprocess:
                report.outcomes.append(Outcome(path=target, status="skipped"))
                _notify(progress, "skipped", target, None)
                continue

            prepared = render(target, max_pages=config.max_pages, dpi=config.render_dpi)
            result = extract_document(target, provider, config, prepared=prepared)
            rules.apply(result.extraction)

            filed: Path | None = None
            if file_documents:
                filed = apply_plan(
                    plan_file(result.extraction, target, config.filed_root, move=move)
                )

            store.save(
                digest,
                result.extraction,
                source_path=target,
                filed_path=filed,
                model=config.vision_model if result.used_vision else config.text_model,
                pages=result.pages,
                used_vision=result.used_vision,
                attempts=result.attempts,
            )
            report.outcomes.append(
                Outcome(path=target, status="ingested", result=result, filed_path=filed)
            )
            _notify(progress, "ingested", target, None)

        except (LedgerLocalError, OSError) as exc:
            report.outcomes.append(Outcome(path=target, status="failed", error=str(exc)))
            _notify(progress, "failed", target, str(exc))

    return report


def recategorise(store: Store, rules: Ruleset, config: Config) -> int:
    """Re-run filing rules over everything already stored, without the model.

    Changing your rules and replaying your whole archive takes a second and
    costs nothing, because the expensive part is already on disk.
    """
    from ledgerlocal.models import Extraction

    changed = 0
    for record in list(store.all_records()):
        payload = store.payload(record.digest)
        if payload is None:
            continue
        extraction = Extraction.from_raw(payload, config.date_order)
        before = (extraction.category, extraction.client)
        rules.apply(extraction)
        if (extraction.category, extraction.client) != before:
            store.save(
                record.digest,
                extraction,
                source_path=Path(record.source_path),
                filed_path=Path(record.filed_path) if record.filed_path else None,
            )
            changed += 1
    return changed


def _collect(paths: Iterable[Path], *, recursive: bool) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        for candidate in discover(path, recursive=recursive):
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(candidate)
    return found


def _notify(progress: Progress | None, status: str, path: Path, detail: str | None) -> None:
    if progress is not None:
        progress(status, path, detail)
