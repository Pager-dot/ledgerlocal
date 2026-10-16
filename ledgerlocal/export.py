"""Exports: the artefacts a freelancer actually hands to their accountant."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from decimal import Decimal
from io import StringIO
from pathlib import Path

from ledgerlocal.store import Record, totals_by

CSV_COLUMNS = [
    "issue_date",
    "vendor",
    "kind",
    "invoice_number",
    "category",
    "client",
    "currency",
    "subtotal",
    "tax",
    "total",
    "confidence",
    "needs_review",
    "warnings",
    "filed_path",
    "source_path",
    "digest",
]


def records_to_csv(records: Sequence[Record]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "issue_date": record.issue_date or "",
                "vendor": record.vendor,
                "kind": record.kind,
                "invoice_number": record.invoice_number,
                "category": record.category,
                "client": record.client,
                "currency": record.currency,
                "subtotal": _money(record.subtotal),
                "tax": _money(record.tax),
                "total": _money(record.total),
                "confidence": f"{record.confidence:.2f}",
                "needs_review": "yes" if record.needs_review else "no",
                "warnings": "; ".join(record.warnings),
                "filed_path": record.filed_path,
                "source_path": record.source_path,
                "digest": record.digest[:12],
            }
        )
    return buffer.getvalue()


def summary_csv(records: Sequence[Record], key: str = "category") -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([key, "documents", "tax", "total"])
    for name, bucket in totals_by(records, key).items():
        writer.writerow([name, int(bucket["count"]), _money(bucket["tax"]), _money(bucket["total"])])
    return buffer.getvalue()


def summary_markdown(records: Sequence[Record], title: str = "Expense summary") -> str:
    lines = [f"# {title}", ""]
    if not records:
        return "\n".join(lines + ["No documents matched.", ""])

    flagged = [record for record in records if record.needs_review]
    lines += [
        f"- Documents: **{len(records)}**",
        f"- Needing review: **{len(flagged)}**",
        f"- Vendors: **{len({r.vendor for r in records if r.vendor})}**",
        "",
        "## By category",
        "",
        "| Category | Docs | Tax | Total |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, bucket in totals_by(records, "category").items():
        lines.append(f"| {name} | {int(bucket['count'])} | {_money(bucket['tax'])} | {_money(bucket['total'])} |")

    clients = {name: b for name, b in totals_by(records, "client").items() if not name.startswith("(none)")}
    if clients:
        lines += ["", "## Billable by client", "", "| Client | Docs | Total |", "| --- | ---: | ---: |"]
        for name, bucket in clients.items():
            lines.append(f"| {name} | {int(bucket['count'])} | {_money(bucket['total'])} |")

    if flagged:
        lines += ["", "## Needs a human look", ""]
        for record in flagged[:50]:
            label = f"{record.issue_date or 'undated'} · {record.vendor or 'unknown vendor'}"
            lines.append(f"- **{label}** — {'; '.join(record.warnings)}")
    lines.append("")
    return "\n".join(lines)


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8")
    return path


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def total_of(records: Iterable[Record]) -> Decimal:
    return sum((record.total or Decimal(0) for record in records), Decimal(0))
