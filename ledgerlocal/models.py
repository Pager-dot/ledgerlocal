"""The shape of a parsed document, and the only place loose JSON becomes typed."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from ledgerlocal.parsing import (
    parse_currency,
    parse_date,
    parse_money,
    quarter_of,
    slugify,
)

DOC_KINDS = ("invoice", "receipt", "credit_note", "statement", "other")


@dataclass
class LineItem:
    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None

    @classmethod
    def from_raw(cls, raw: Any) -> LineItem | None:
        if isinstance(raw, str):
            return cls(description=raw.strip()) if raw.strip() else None
        if not isinstance(raw, dict):
            return None
        description = str(
            raw.get("description") or raw.get("item") or raw.get("name") or ""
        ).strip()
        amount = parse_money(raw.get("amount") or raw.get("total") or raw.get("line_total"))
        if not description and amount is None:
            return None
        return cls(
            description=description or "(unlabelled)",
            quantity=parse_money(raw.get("quantity") or raw.get("qty")),
            unit_price=parse_money(raw.get("unit_price") or raw.get("price") or raw.get("rate")),
            amount=amount,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "quantity": _str_or_none(self.quantity),
            "unit_price": _str_or_none(self.unit_price),
            "amount": _str_or_none(self.amount),
        }


@dataclass
class Extraction:
    """What we believe a single document says, after validation."""

    kind: str = "other"
    vendor: str = ""
    vendor_address: str = ""
    invoice_number: str = ""
    issue_date: date | None = None
    due_date: date | None = None
    currency: str = "USD"
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    tax_id: str = ""
    payment_method: str = ""
    category: str = ""
    client: str = ""
    line_items: list[LineItem] = field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""
    warnings: list[str] = field(default_factory=list)

    # -- construction ---------------------------------------------------

    @classmethod
    def from_raw(cls, raw: dict[str, Any], date_order: str = "dmy") -> Extraction:
        if not isinstance(raw, dict):
            raise TypeError("extraction payload must be a JSON object")

        kind = str(raw.get("kind") or raw.get("document_type") or "other").strip().lower()
        if kind not in DOC_KINDS:
            kind = "invoice" if "invoice" in kind else "receipt" if "receipt" in kind else "other"

        item_source = raw.get("line_items") or raw.get("items") or []
        items = [LineItem.from_raw(entry) for entry in item_source] if isinstance(item_source, list) else []

        extraction = cls(
            kind=kind,
            vendor=_clean(raw.get("vendor") or raw.get("merchant") or raw.get("supplier")),
            vendor_address=_clean(raw.get("vendor_address") or raw.get("address")),
            invoice_number=_clean(raw.get("invoice_number") or raw.get("receipt_number") or raw.get("number")),
            issue_date=parse_date(raw.get("issue_date") or raw.get("date"), date_order),
            due_date=parse_date(raw.get("due_date"), date_order),
            currency=parse_currency(raw.get("currency") or raw.get("currency_code")),
            subtotal=parse_money(raw.get("subtotal") or raw.get("net")),
            tax=parse_money(raw.get("tax") or raw.get("vat") or raw.get("gst") or raw.get("tax_amount")),
            total=parse_money(raw.get("total") or raw.get("amount_due") or raw.get("grand_total")),
            tax_id=_clean(raw.get("tax_id") or raw.get("vat_number") or raw.get("gstin")),
            payment_method=_clean(raw.get("payment_method")),
            category=_clean(raw.get("category")).lower(),
            client=_clean(raw.get("client") or raw.get("project")),
            line_items=[item for item in items if item is not None],
            confidence=_clamp_confidence(raw.get("confidence")),
            notes=_clean(raw.get("notes")),
        )
        extraction.warnings = extraction.audit()
        return extraction

    # -- checks ---------------------------------------------------------

    def audit(self) -> list[str]:
        """Arithmetic and completeness checks the model does not get to skip.

        These are what make a small local model trustworthy enough to bill
        from: we never take its numbers on faith, we check that they add up and
        surface the ones that do not for human review.
        """
        problems: list[str] = []
        if not self.vendor:
            problems.append("no vendor found")
        if self.issue_date is None:
            problems.append("no date found")
        if self.total is None:
            problems.append("no total found")
        if self.total is not None and self.total < 0 and self.kind != "credit_note":
            problems.append("negative total on a non-credit document")

        if self.subtotal is not None and self.tax is not None and self.total is not None:
            drift = abs((self.subtotal + self.tax) - self.total)
            if drift > Decimal("0.02"):
                problems.append(f"subtotal + tax differs from total by {drift}")

        # Line items are only checked for *overshoot*. A model that transcribes
        # three of a document's seven rows is incomplete, not wrong, and we bill
        # from `total` regardless — so a shortfall is not worth a human's time.
        # Items summing to more than the subtotal is a genuine contradiction.
        item_total = sum((item.amount for item in self.line_items if item.amount is not None), Decimal(0))
        if item_total and self.subtotal is not None and item_total - self.subtotal > Decimal("0.02"):
            problems.append(f"line items exceed the subtotal by {item_total - self.subtotal}")

        if self.due_date and self.issue_date and self.due_date < self.issue_date:
            problems.append("due date precedes issue date")
        return problems

    @property
    def needs_review(self) -> bool:
        return bool(self.warnings)

    @property
    def fiscal_period(self) -> str:
        if self.issue_date is None:
            return "undated"
        return f"{self.issue_date.year}-Q{quarter_of(self.issue_date)}"

    @property
    def vendor_slug(self) -> str:
        return slugify(self.vendor or "unknown-vendor")

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "vendor": self.vendor,
            "vendor_address": self.vendor_address,
            "invoice_number": self.invoice_number,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "currency": self.currency,
            "subtotal": _str_or_none(self.subtotal),
            "tax": _str_or_none(self.tax),
            "total": _str_or_none(self.total),
            "tax_id": self.tax_id,
            "payment_method": self.payment_method,
            "category": self.category,
            "client": self.client,
            "line_items": [item.to_dict() for item in self.line_items],
            "confidence": self.confidence,
            "notes": self.notes,
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return "" if text.lower() in {"none", "null", "n/a", "unknown", "-"} else text


def _clamp_confidence(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:  # some models answer in percent
        number /= 100.0
    return max(0.0, min(1.0, number))


def _str_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
