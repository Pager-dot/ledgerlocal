from datetime import date
from decimal import Decimal

from ledgerlocal.models import Extraction


def test_from_raw_normalises_a_messy_answer():
    extraction = Extraction.from_raw(
        {
            "document_type": "an invoice",
            "merchant": "  Hetzner   Online GmbH ",
            "date": "14.02.2026",
            "currency": "€",
            "net": "27,50",
            "vat": "5,23",
            "total": "32,73 €",
            "confidence": 85,  # answered in percent
            "items": [{"description": "CX42", "amount": "22,90"}, "Primary IPv4"],
        }
    )
    assert extraction.kind == "invoice"
    assert extraction.vendor == "Hetzner Online GmbH"
    assert extraction.issue_date == date(2026, 2, 14)
    assert extraction.currency == "EUR"
    assert extraction.total == Decimal("32.73")
    assert extraction.confidence == 0.85
    assert len(extraction.line_items) == 2
    assert extraction.fiscal_period == "2026-Q1"


def test_audit_catches_arithmetic_that_does_not_add_up():
    extraction = Extraction.from_raw(
        {"vendor": "X", "date": "2026-01-01", "subtotal": "100", "tax": "10", "total": "120"}
    )
    assert extraction.needs_review
    assert any("differs from total" in warning for warning in extraction.warnings)


def test_audit_accepts_a_consistent_document():
    extraction = Extraction.from_raw(
        {"vendor": "X", "date": "2026-01-01", "subtotal": "100", "tax": "10", "total": "110", "confidence": 0.9}
    )
    assert extraction.warnings == []
    assert not extraction.needs_review


def test_audit_reports_missing_essentials():
    extraction = Extraction.from_raw({"vendor": "", "total": ""})
    assert "no vendor found" in extraction.warnings
    assert "no total found" in extraction.warnings
    assert "no date found" in extraction.warnings


def test_placeholder_strings_are_treated_as_empty():
    extraction = Extraction.from_raw({"vendor": "N/A", "invoice_number": "unknown"})
    assert extraction.vendor == ""
    assert extraction.invoice_number == ""


def test_round_trips_through_json():
    extraction = Extraction.from_raw(
        {"vendor": "X", "date": "2026-05-05", "total": "9.99", "currency": "GBP"}
    )
    revived = Extraction.from_raw(extraction.to_dict())
    assert revived.total == extraction.total
    assert revived.issue_date == extraction.issue_date
    assert revived.currency == "GBP"


def test_partial_line_items_are_not_treated_as_an_error():
    # Models routinely transcribe some rows and not others. That is incomplete,
    # not wrong, and the total is what we bill from.
    extraction = Extraction.from_raw(
        {
            "vendor": "Hetzner", "date": "2026-02-14", "subtotal": "27.50",
            "tax": "5.23", "total": "32.73", "confidence": 0.9,
            "line_items": [{"description": "CX42", "amount": "22.90"}],
        }
    )
    assert extraction.warnings == []


def test_line_items_exceeding_the_subtotal_are_a_contradiction():
    extraction = Extraction.from_raw(
        {
            "vendor": "Hetzner", "date": "2026-02-14", "subtotal": "27.50",
            "tax": "5.23", "total": "32.73", "confidence": 0.9,
            "line_items": [{"description": "CX42", "amount": "90.00"}],
        }
    )
    assert any("exceed the subtotal" in warning for warning in extraction.warnings)
