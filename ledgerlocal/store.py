"""A single SQLite file holding everything we know. No server, no account.

The user owns this file. They can open it in any SQLite browser, back it up to
a USB stick, or delete it. That is the whole storage design, and it is only
possible because nothing in the pipeline needs a remote service.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ledgerlocal.models import Extraction

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    digest           TEXT PRIMARY KEY,
    source_path      TEXT NOT NULL,
    filed_path       TEXT,
    ingested_at      TEXT NOT NULL,
    model            TEXT,
    pages            INTEGER,
    used_vision      INTEGER,
    attempts         INTEGER,
    kind             TEXT,
    vendor           TEXT,
    invoice_number   TEXT,
    issue_date       TEXT,
    due_date         TEXT,
    currency         TEXT,
    subtotal         TEXT,
    tax              TEXT,
    total            TEXT,
    category         TEXT,
    client           TEXT,
    confidence       REAL,
    warnings         TEXT,
    payload          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS line_items (
    digest       TEXT NOT NULL REFERENCES documents(digest) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    description  TEXT,
    quantity     TEXT,
    unit_price   TEXT,
    amount       TEXT,
    PRIMARY KEY (digest, position)
);

CREATE INDEX IF NOT EXISTS documents_issue_date ON documents(issue_date);
CREATE INDEX IF NOT EXISTS documents_vendor ON documents(vendor);
CREATE INDEX IF NOT EXISTS documents_category ON documents(category);
CREATE INDEX IF NOT EXISTS documents_client ON documents(client);
"""


@dataclass
class Record:
    digest: str
    source_path: str
    filed_path: str
    ingested_at: str
    vendor: str
    kind: str
    invoice_number: str
    issue_date: str | None
    currency: str
    subtotal: Decimal | None
    tax: Decimal | None
    total: Decimal | None
    category: str
    client: str
    confidence: float
    warnings: list[str]

    @property
    def needs_review(self) -> bool:
        return bool(self.warnings)

    @property
    def period(self) -> str:
        if not self.issue_date:
            return "undated"
        year, month = self.issue_date[:4], int(self.issue_date[5:7])
        return f"{year}-Q{(month - 1) // 3 + 1}"


class Store:
    """Thin, explicit SQLite wrapper. Usable as a context manager."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    # -- writes ---------------------------------------------------------

    def has(self, digest: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM documents WHERE digest = ?", (digest,)
        ).fetchone()
        return row is not None

    def save(
        self,
        digest: str,
        extraction: Extraction,
        *,
        source_path: Path,
        filed_path: Path | None = None,
        model: str = "",
        pages: int = 1,
        used_vision: bool = False,
        attempts: int = 1,
    ) -> None:
        payload = extraction.to_dict()
        self.connection.execute(
            """
            INSERT INTO documents (
                digest, source_path, filed_path, ingested_at, model, pages,
                used_vision, attempts, kind, vendor, invoice_number, issue_date,
                due_date, currency, subtotal, tax, total, category, client,
                confidence, warnings, payload
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(digest) DO UPDATE SET
                filed_path = excluded.filed_path,
                ingested_at = excluded.ingested_at,
                kind = excluded.kind,
                vendor = excluded.vendor,
                invoice_number = excluded.invoice_number,
                issue_date = excluded.issue_date,
                due_date = excluded.due_date,
                currency = excluded.currency,
                subtotal = excluded.subtotal,
                tax = excluded.tax,
                total = excluded.total,
                category = excluded.category,
                client = excluded.client,
                confidence = excluded.confidence,
                warnings = excluded.warnings,
                payload = excluded.payload
            """,
            (
                digest,
                str(source_path),
                str(filed_path) if filed_path else None,
                datetime.now(UTC).isoformat(timespec="seconds"),
                model,
                pages,
                int(used_vision),
                attempts,
                extraction.kind,
                extraction.vendor,
                extraction.invoice_number,
                payload["issue_date"],
                payload["due_date"],
                extraction.currency,
                payload["subtotal"],
                payload["tax"],
                payload["total"],
                extraction.category,
                extraction.client,
                extraction.confidence,
                json.dumps(extraction.warnings),
                json.dumps(payload, sort_keys=True),
            ),
        )
        self.connection.execute("DELETE FROM line_items WHERE digest = ?", (digest,))
        self.connection.executemany(
            "INSERT INTO line_items (digest, position, description, quantity, unit_price, amount)"
            " VALUES (?,?,?,?,?,?)",
            [
                (
                    digest,
                    position,
                    item.description,
                    _text(item.quantity),
                    _text(item.unit_price),
                    _text(item.amount),
                )
                for position, item in enumerate(extraction.line_items)
            ],
        )
        self.connection.commit()

    def set_filed_path(self, digest: str, filed_path: Path) -> None:
        self.connection.execute(
            "UPDATE documents SET filed_path = ? WHERE digest = ?", (str(filed_path), digest)
        )
        self.connection.commit()

    def set_category(self, digest: str, category: str) -> None:
        self.connection.execute(
            "UPDATE documents SET category = ? WHERE digest = ?", (category, digest)
        )
        self.connection.commit()

    def forget(self, digest: str) -> bool:
        cursor = self.connection.execute("DELETE FROM documents WHERE digest = ?", (digest,))
        self.connection.commit()
        return cursor.rowcount > 0

    # -- reads ----------------------------------------------------------

    def query(
        self,
        *,
        period: str = "",
        year: int | None = None,
        quarter: int | None = None,
        vendor: str = "",
        category: str = "",
        client: str = "",
        needs_review: bool = False,
        limit: int | None = None,
    ) -> list[Record]:
        clauses: list[str] = []
        params: list[object] = []

        if period:
            year, quarter = _split_period(period)
        if year is not None:
            clauses.append("substr(issue_date, 1, 4) = ?")
            params.append(f"{year:04d}")
        if quarter is not None:
            months = [f"{month:02d}" for month in range(quarter * 3 - 2, quarter * 3 + 1)]
            clauses.append(f"substr(issue_date, 6, 2) IN ({','.join('?' * 3)})")
            params.extend(months)
        if vendor:
            clauses.append("lower(vendor) LIKE ?")
            params.append(f"%{vendor.lower()}%")
        if category:
            clauses.append("lower(category) = ?")
            params.append(category.lower())
        if client:
            clauses.append("lower(client) LIKE ?")
            params.append(f"%{client.lower()}%")
        if needs_review:
            clauses.append("warnings != '[]'")

        sql = "SELECT * FROM documents"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY issue_date IS NULL, issue_date, vendor"
        if limit:
            sql += f" LIMIT {int(limit)}"

        return [_to_record(row) for row in self.connection.execute(sql, params)]

    def all_records(self) -> Iterator[Record]:
        for row in self.connection.execute("SELECT * FROM documents ORDER BY issue_date"):
            yield _to_record(row)

    def payload(self, digest: str) -> dict | None:
        row = self.connection.execute(
            "SELECT payload FROM documents WHERE digest = ?", (digest,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def counts(self) -> dict[str, int]:
        total = self.connection.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        flagged = self.connection.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE warnings != '[]'"
        ).fetchone()["n"]
        vendors = self.connection.execute(
            "SELECT COUNT(DISTINCT vendor) AS n FROM documents"
        ).fetchone()["n"]
        return {"documents": total, "needs_review": flagged, "vendors": vendors}

    def periods(self) -> list[str]:
        seen = {record.period for record in self.all_records()}
        return sorted(seen)


def totals_by(records: Iterable[Record], key: str) -> dict[str, dict[str, Decimal]]:
    """Group records and sum totals/tax, keeping currencies apart.

    Mixing currencies in a tax summary would be worse than useless, so the key
    carries the currency and the caller sees them separately.
    """
    buckets: dict[str, dict[str, Decimal]] = {}
    for record in records:
        raw = getattr(record, key, "") or UNSET
        bucket_key = f"{raw} [{record.currency}]"
        bucket = buckets.setdefault(
            bucket_key, {"total": Decimal(0), "tax": Decimal(0), "count": Decimal(0)}
        )
        bucket["total"] += record.total or Decimal(0)
        bucket["tax"] += record.tax or Decimal(0)
        bucket["count"] += 1
    return dict(sorted(buckets.items()))


UNSET = "(none)"


def _split_period(period: str) -> tuple[int | None, int | None]:
    text = period.strip().upper().replace("/", "-")
    if "-Q" in text:
        year, _, quarter = text.partition("-Q")
        return int(year), int(quarter)
    if text.isdigit():
        return int(text), None
    raise ValueError(f"could not read period {period!r}; use 2026 or 2026-Q1")


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value: object) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def _to_record(row: sqlite3.Row) -> Record:
    return Record(
        digest=row["digest"],
        source_path=row["source_path"] or "",
        filed_path=row["filed_path"] or "",
        ingested_at=row["ingested_at"] or "",
        vendor=row["vendor"] or "",
        kind=row["kind"] or "other",
        invoice_number=row["invoice_number"] or "",
        issue_date=row["issue_date"],
        currency=row["currency"] or "USD",
        subtotal=_decimal(row["subtotal"]),
        tax=_decimal(row["tax"]),
        total=_decimal(row["total"]),
        category=row["category"] or "",
        client=row["client"] or "",
        confidence=row["confidence"] or 0.0,
        warnings=json.loads(row["warnings"] or "[]"),
    )
