"""Filing documents into a folder tree an accountant can read without us.

The output is plain folders and plainly named files. If this project is
abandoned tomorrow, the user still has a sorted archive. Tools that lock the
archive inside their own cloud cannot offer that.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ledgerlocal.models import Extraction
from ledgerlocal.parsing import quarter_of, slugify


@dataclass
class FilePlan:
    source: Path
    destination: Path
    action: str  # "copy" | "move"

    @property
    def already_there(self) -> bool:
        return self.source.resolve() == self.destination.resolve()


def target_path(extraction: Extraction, root: Path, suffix: str) -> Path:
    """``root/2026/Q1/software/2026-02-14_github_12.00-USD.pdf``"""
    if extraction.issue_date:
        year = f"{extraction.issue_date.year:04d}"
        quarter = f"Q{quarter_of(extraction.issue_date)}"
        datestamp = extraction.issue_date.isoformat()
    else:
        year, quarter, datestamp = "undated", "undated", "unknown-date"

    category = slugify(extraction.category or "uncategorised", 32)
    amount = "no-total" if extraction.total is None else f"{extraction.total}-{extraction.currency}"
    number = f"_{slugify(extraction.invoice_number, 20)}" if extraction.invoice_number else ""
    name = f"{datestamp}_{extraction.vendor_slug}{number}_{slugify(amount, 24)}{suffix.lower()}"
    return root / year / quarter / category / name


def plan_file(
    extraction: Extraction, source: Path, root: Path, *, move: bool = False
) -> FilePlan:
    destination = _dedupe(target_path(extraction, root, source.suffix))
    return FilePlan(source=source, destination=destination, action="move" if move else "copy")


def apply_plan(plan: FilePlan) -> Path:
    """Carry out a plan. Never overwrites; never loses the original on copy."""
    if plan.already_there:
        return plan.destination
    plan.destination.parent.mkdir(parents=True, exist_ok=True)
    destination = _dedupe(plan.destination)
    if plan.action == "move":
        shutil.move(str(plan.source), str(destination))
    else:
        shutil.copy2(plan.source, destination)
    return destination


def _dedupe(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for counter in range(2, 1000):
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"too many files named like {path.name}")
