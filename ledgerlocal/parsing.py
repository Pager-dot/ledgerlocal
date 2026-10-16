"""Normalising the untidy strings a vision model reads off a receipt.

A 7B open-weight model is very good at finding the total on a crumpled photo
and noticeably worse at formatting it. Rather than fight that with a bigger
model, we let it answer loosely and do the strict part in Python, where it is
deterministic and testable.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CURRENCY_SYMBOLS = {
    "$": "USD", "US$": "USD", "usd": "USD",
    "€": "EUR", "eur": "EUR",
    "£": "GBP", "gbp": "GBP",
    "₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR",
    "¥": "JPY", "jpy": "JPY",
    "a$": "AUD", "aud": "AUD",
    "c$": "CAD", "cad": "CAD",
    "chf": "CHF", "sek": "SEK", "zar": "ZAR", "brl": "BRL", "sgd": "SGD",
}

_MONEY_CHARS = re.compile(r"[^0-9,.\-]")
_PAREN_NEGATIVE = re.compile(r"^\((.*)\)$")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_currency(value: object, default: str = "USD") -> str:
    """Map whatever the model said into an ISO-4217-ish code."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    lowered = text.lower()
    if lowered in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[lowered]
    if text in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[text]
    if re.fullmatch(r"[A-Za-z]{3}", text):
        return text.upper()
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in lowered:
            return code
    return default


def parse_money(value: object) -> Decimal | None:
    """Parse ``"$1,234.56"``, ``"1.234,56 EUR"``, ``"(42.00)"`` and friends.

    Returns ``None`` for anything we cannot read, which the caller treats as
    "the model did not find this field" rather than as zero. Conflating those
    two is how a tax export silently loses money.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    if not text:
        return None

    negative = False
    paren = _PAREN_NEGATIVE.match(text)
    if paren:
        negative, text = True, paren.group(1)

    cleaned = _MONEY_CHARS.sub("", text)
    if cleaned.startswith("-"):
        negative = True
    cleaned = cleaned.replace("-", "")
    if not cleaned or not any(ch.isdigit() for ch in cleaned):
        return None

    has_comma, has_dot = "," in cleaned, "." in cleaned
    if has_comma and has_dot:
        # Whichever separator comes last is the decimal point.
        decimal_sep = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        cleaned = cleaned.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma:
        head, _, tail = cleaned.rpartition(",")
        # "1,234" is thousands; "1,23" and "1,2345" are decimals.
        cleaned = f"{head}.{tail}" if len(tail) != 3 else f"{head}{tail}"
    elif cleaned.count(".") > 1:
        head, _, tail = cleaned.rpartition(".")
        cleaned = f"{head.replace('.', '')}.{tail}"

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def parse_date(value: object, date_order: str = "dmy") -> date | None:
    """Parse the date formats that actually turn up on receipts.

    ``date_order`` ("dmy" or "mdy") only breaks genuinely ambiguous ties such
    as ``03/04/2026``; anything the numbers themselves settle is settled.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    iso = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    named = re.search(
        r"(\d{1,2})\s*(?:st|nd|rd|th)?[\s\-/.]*"
        r"([A-Za-z]{3,9})[\s\-/.,]*(\d{2,4})",
        text,
    )
    if named and named.group(2)[:3].lower() in _MONTHS:
        return _safe_date(
            _expand_year(int(named.group(3))),
            _MONTHS[named.group(2)[:3].lower()],
            int(named.group(1)),
        )

    named = re.search(r"([A-Za-z]{3,9})[\s\-/.]*(\d{1,2})\s*(?:st|nd|rd|th)?[\s\-/.,]*(\d{2,4})", text)
    if named and named.group(1)[:3].lower() in _MONTHS:
        return _safe_date(
            _expand_year(int(named.group(3))),
            _MONTHS[named.group(1)[:3].lower()],
            int(named.group(2)),
        )

    numeric = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    if numeric:
        a, b = int(numeric.group(1)), int(numeric.group(2))
        year = _expand_year(int(numeric.group(3)))
        if a > 12:
            return _safe_date(year, b, a)
        if b > 12:
            return _safe_date(year, a, b)
        return _safe_date(year, b, a) if date_order == "dmy" else _safe_date(year, a, b)
    return None


def _expand_year(year: int) -> int:
    if year >= 100:
        return year
    # Receipts are not from the 1920s; two-digit years are this century.
    return 2000 + year


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def quarter_of(when: date) -> int:
    return (when.month - 1) // 3 + 1


def slugify(text: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return (slug[:max_length].rstrip("-")) or "unknown"
