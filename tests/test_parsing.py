from datetime import date
from decimal import Decimal

import pytest

from ledgerlocal.parsing import parse_currency, parse_date, parse_money, quarter_of, slugify


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$1,234.56", Decimal("1234.56")),
        ("1.234,56 €", Decimal("1234.56")),
        ("32,73 EUR", Decimal("32.73")),
        ("1,234", Decimal("1234")),
        ("11.77", Decimal("11.77")),
        ("(42.00)", Decimal("-42.00")),
        ("-15.50", Decimal("-15.50")),
        ("₹ 2,45,000.00", Decimal("245000.00")),
        (65.09, Decimal("65.09")),
        (0, Decimal("0")),
    ],
)
def test_parse_money_reads_real_receipt_formats(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "n/a", "TOTAL", True])
def test_parse_money_returns_none_rather_than_zero(raw):
    # Conflating "not found" with zero is how a tax export silently loses money.
    assert parse_money(raw) is None


@pytest.mark.parametrize(
    "raw, order, expected",
    [
        ("2026-02-14", "dmy", date(2026, 2, 14)),
        ("14.02.2026", "dmy", date(2026, 2, 14)),
        ("03/04/2026", "dmy", date(2026, 4, 3)),
        ("03/04/2026", "mdy", date(2026, 3, 4)),
        ("25/12/26", "mdy", date(2026, 12, 25)),  # unambiguous: day > 12
        ("March 2, 2026", "dmy", date(2026, 3, 2)),
        ("2 March 2026", "mdy", date(2026, 3, 2)),
        ("14th Feb 2026", "dmy", date(2026, 2, 14)),
        ("Invoice date: 07 Jan 2026", "dmy", date(2026, 1, 7)),
    ],
)
def test_parse_date(raw, order, expected):
    assert parse_date(raw, order) == expected


@pytest.mark.parametrize("raw", ["", None, "whenever", "2026-13-45"])
def test_parse_date_rejects_nonsense(raw):
    assert parse_date(raw) is None


def test_parse_currency():
    assert parse_currency("€") == "EUR"
    assert parse_currency("32,73 €") == "EUR"
    assert parse_currency("usd") == "USD"
    assert parse_currency("₹") == "INR"
    assert parse_currency("", default="GBP") == "GBP"


def test_quarter_and_slug():
    assert quarter_of(date(2026, 1, 1)) == 1
    assert quarter_of(date(2026, 12, 31)) == 4
    assert slugify("Hetzner Online GmbH!") == "hetzner-online-gmbh"
    assert slugify("///") == "unknown"
