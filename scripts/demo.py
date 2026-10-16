#!/usr/bin/env python3
"""Run the whole pipeline over samples/ with no model and no downloads.

    python scripts/demo.py

Uses a scripted provider standing in for the local 7B, so you can see exactly
what LedgerLocal does — including how it catches a document whose numbers do
not add up — before deciding whether to install anything.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ledgerlocal import export  # noqa: E402
from ledgerlocal.categorize import Ruleset  # noqa: E402
from ledgerlocal.config import Config  # noqa: E402
from ledgerlocal.ingest import ingest  # noqa: E402
from ledgerlocal.store import Store  # noqa: E402

# What a 7B vision model typically returns for each sample. The Adobe one is
# deliberately wrong by nine cents, to show the arithmetic audit working.
SCRIPTED = {
    "hetzner-invoice.txt": {
        "kind": "invoice", "vendor": "Hetzner Online GmbH", "issue_date": "14.02.2026",
        "invoice_number": "R0029481773", "currency": "€", "subtotal": "27,50",
        "tax": "5,23", "total": "32,73 €", "confidence": 0.94,
        "line_items": [
            {"description": "CX42 Cloud Server", "amount": "22,90"},
            {"description": "Primary IPv4", "amount": "0,60"},
            {"description": "Volume storage 100 GB", "amount": "4,00"},
        ],
    },
    "cafe-receipt.txt": {
        "kind": "receipt", "vendor": "Blue Fox Coffee", "issue_date": "03/04/2026",
        "invoice_number": "4471", "currency": "EUR", "subtotal": "10.80",
        "tax": "0.97", "total": "11.77", "payment_method": "VISA ****4417",
        "notes": "Client meeting - Northwind", "confidence": 0.88,
    },
    "acme-consulting-invoice.txt": {
        "kind": "invoice", "vendor": "Bright Path Legal LLP", "issue_date": "March 2, 2026",
        "due_date": "April 1, 2026", "invoice_number": "BPL-2026-0188", "currency": "$",
        "subtotal": "990.00", "tax": "0.00", "total": "990.00", "confidence": 0.91, "client": "Acme Corp",
        "line_items": [
            {"description": "Contract review - Acme Corp MSA", "amount": "770.00"},
            {"description": "Trademark filing advice", "amount": "220.00"},
        ],
    },
    "adobe-subscription.txt": {
        "kind": "receipt", "vendor": "Adobe Inc.", "issue_date": "2026-01-07",
        "invoice_number": "AD-99381028", "currency": "USD", "subtotal": "59.99",
        "tax": "5.10", "total": "65.00", "confidence": 0.72,  # misread: should be 65.09
    },
}

# Matched against the document text, the way a real model would see it.
MARKERS = {
    "hetzner": "hetzner-invoice.txt",
    "blue fox": "cafe-receipt.txt",
    "bright path": "acme-consulting-invoice.txt",
    "adobe": "adobe-subscription.txt",
}


class ScriptedProvider:
    """Answers from a lookup table, so the demo is deterministic and offline."""

    name = "scripted"

    def __init__(self) -> None:
        self.current = ""

    def complete_text(self, prompt, *, system="", schema=None):
        haystack = prompt.lower()
        for marker, name in MARKERS.items():
            if marker in haystack:
                return json.dumps(SCRIPTED[name])
        return json.dumps({"vendor": "", "total": "", "confidence": 0.1})

    def complete_vision(self, prompt, images, *, system="", schema=None):
        return self.complete_text(prompt, system=system, schema=schema)

    def health(self):
        return {"provider": self.name, "reachable": True, "models": ["scripted"]}


def main() -> int:
    with tempfile.TemporaryDirectory() as workspace:
        config = Config(provider="fake", library=Path(workspace) / "library", enforce_offline=False)
        rules = Ruleset.default()
        rules.clients["Northwind Trading"] = ["northwind"]

        with Store(config.database) as store:
            report = ingest(
                [ROOT / "samples"],
                config=config,
                provider=ScriptedProvider(),
                store=store,
                rules=rules,
            )

            print(f"Read {len(report.ingested)} documents\n")
            print(f"{'Date':<12}{'Vendor':<26}{'Category':<18}{'Amount':>12}")
            print("-" * 68)
            for outcome in report.ingested:
                doc = outcome.result.extraction
                when = doc.issue_date.isoformat() if doc.issue_date else "undated"
                amount = "?" if doc.total is None else f"{doc.total} {doc.currency}"
                print(f"{when:<12}{doc.vendor[:25]:<26}{doc.category:<18}{amount:>12}")

            print("\nFlagged for review:")
            for outcome in report.needs_review:
                doc = outcome.result.extraction
                print(f"  {doc.vendor}: {'; '.join(doc.warnings)}")
            if not report.needs_review:
                print("  (none)")

            print("\nFiled as:")
            for outcome in report.ingested:
                if outcome.filed_path:
                    print(f"  {outcome.filed_path.relative_to(config.filed_root)}")

            print()
            print(export.summary_markdown(store.query(), "Demo ledger"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
