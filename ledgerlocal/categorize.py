"""Assigning a tax category, with the user's own rules winning over the model.

Deterministic keyword rules first, model suggestion second. A freelancer knows
their own books better than any model does, and a rule they wrote once keeps
working forever at zero cost. The model is the fallback for the long tail.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ledgerlocal.errors import ConfigError
from ledgerlocal.models import Extraction

UNCATEGORISED = "uncategorised"

DEFAULT_RULES: dict[str, list[str]] = {
    "software": [
        "adobe", "github", "jetbrains", "figma", "notion", "slack", "atlassian",
        "microsoft", "google workspace", "dropbox", "1password", "subscription",
        "saas", "license", "licence",
    ],
    "hosting": [
        "aws", "amazon web services", "digitalocean", "hetzner", "linode", "vercel",
        "netlify", "cloudflare", "namecheap", "godaddy", "domain", "hosting", "vps",
    ],
    "hardware": [
        "apple", "dell", "lenovo", "logitech", "monitor", "keyboard", "laptop",
        "ssd", "docking", "best buy", "micro center",
    ],
    "travel": [
        "uber", "lyft", "airline", "airways", "railway", "amtrak", "train ticket",
        "hotel", "airbnb", "booking.com", "taxi", "flight", "baggage", "toll",
    ],
    "meals": [
        "restaurant", "cafe", "coffee", "starbucks", "doordash", "ubereats",
        "deliveroo", "lunch", "dinner", "catering",
    ],
    "office": [
        "staples", "ikea", "office depot", "stationery", "printer paper", "desk",
        "chair", "rent", "coworking", "wework",
    ],
    "telecom": ["verizon", "at&t", "vodafone", "airtel", "jio", "t-mobile", "broadband", "internet", "mobile plan"],
    "professional_fees": ["accountant", "bookkeep", "legal", "solicitor", "attorney", "notary", "consultant", "audit"],
    "marketing": ["google ads", "meta platforms", "facebook ads", "linkedin ads", "mailchimp", "advertis", "sponsorship"],
    "education": ["course", "udemy", "coursera", "pluralsight", "conference", "training", "book", "ebook"],
    "banking_fees": ["stripe", "paypal", "wise", "payoneer", "bank charge", "service fee", "fx fee", "interest"],
    "insurance": ["insurance", "liability cover", "indemnity"],
    "income": ["payment received", "remittance", "paid in full", "thank you for your payment"],
}


@dataclass
class Ruleset:
    categories: dict[str, list[str]]
    clients: dict[str, list[str]]

    @classmethod
    def default(cls) -> Ruleset:
        return cls(categories={k: list(v) for k, v in DEFAULT_RULES.items()}, clients={})

    @classmethod
    def load(cls, path: Path) -> Ruleset:
        """Load ``rules.toml``, merging the user's keywords into the defaults."""
        ruleset = cls.default()
        if not path.exists():
            return ruleset
        try:
            raw = tomllib.loads(path.read_text("utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"could not read {path}: {exc}") from exc

        for section, target in (("categories", ruleset.categories), ("clients", ruleset.clients)):
            block = raw.get(section, {})
            if not isinstance(block, dict):
                raise ConfigError(f"[{section}] in {path} must be a table of lists")
            for name, keywords in block.items():
                if isinstance(keywords, str):
                    keywords = [keywords]
                if not isinstance(keywords, list):
                    raise ConfigError(f"{section}.{name} in {path} must be a list of keywords")
                merged = target.setdefault(str(name).strip().lower(), [])
                for keyword in keywords:
                    text = str(keyword).strip().lower()
                    if text and text not in merged:
                        merged.append(text)
        return ruleset

    def categorise(self, extraction: Extraction) -> tuple[str, str]:
        """Return ``(category, source)`` where source is rule/model/default."""
        haystack = _haystack(extraction)
        match = _best_match(self.categories, haystack)
        if match:
            return match, "rule"
        suggestion = extraction.category.strip().lower().replace(" ", "_")
        if suggestion:
            return suggestion, "model"
        return UNCATEGORISED, "default"

    def attribute_client(self, extraction: Extraction) -> tuple[str, str]:
        if extraction.client:
            return extraction.client, "model"
        match = _best_match(self.clients, _haystack(extraction))
        return (match, "rule") if match else ("", "none")

    def apply(self, extraction: Extraction) -> Extraction:
        extraction.category, _ = self.categorise(extraction)
        extraction.client, _ = self.attribute_client(extraction)
        return extraction


def _haystack(extraction: Extraction) -> str:
    parts = [
        extraction.vendor,
        extraction.notes,
        extraction.vendor_address,
        extraction.payment_method,
        *(item.description for item in extraction.line_items),
    ]
    return " ".join(part for part in parts if part).lower()


def _best_match(rules: dict[str, list[str]], haystack: str) -> str:
    """Longest matching keyword wins, so "google ads" beats "google"."""
    best_name, best_length = "", 0
    for name, keywords in rules.items():
        for keyword in keywords:
            if keyword and keyword in haystack and len(keyword) > best_length:
                best_name, best_length = name, len(keyword)
    return best_name


EXAMPLE_RULES = """\
# Your own filing rules. These beat whatever the model suggests, which is the
# point: you know your books. Keywords are matched case-insensitively against
# the vendor, address, notes and line items. The longest match wins.
#
# These entries are merged with the built-in defaults, so you only list what is
# specific to you.

[categories]
software = ["my-niche-cad-tool"]
hosting = ["my-colo-provider"]
studio_rent = ["blackwell properties", "unit 4b"]

[clients]
# Tag expenses to a client so you can bill them back.
"Northwind Trading" = ["northwind", "po-2026-nw"]
"Acme Corp" = ["acme", "po-2026-ac"]
"""
