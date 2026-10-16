import csv
from io import StringIO

from ledgerlocal.export import records_to_csv, summary_csv, summary_markdown, total_of
from ledgerlocal.models import Extraction


def save(store, config, digest, **fields):
    extraction = Extraction.from_raw(
        {"vendor": "V", "issue_date": "2026-01-15", "total": "10", "confidence": 0.9, **fields}
    )
    store.save(digest, extraction, source_path=config.library / f"{digest}.txt")


def test_csv_has_one_row_per_document_and_a_stable_header(store, config):
    save(store, config, "a" * 64, vendor="Hetzner", category="hosting", total="32.73", currency="EUR")
    save(store, config, "b" * 64, vendor="Adobe", category="software", total="65.09")

    rows = {row["vendor"]: row for row in csv.DictReader(StringIO(records_to_csv(store.query())))}
    assert set(rows) == {"Hetzner", "Adobe"}
    assert rows["Hetzner"]["total"] == "32.73"
    assert rows["Hetzner"]["currency"] == "EUR"
    assert rows["Hetzner"]["needs_review"] == "no"
    assert rows["Hetzner"]["digest"] == "a" * 12


def test_summary_csv_groups_and_keeps_currencies_apart(store, config):
    save(store, config, "c" * 64, category="hosting", total="10", tax="1", currency="EUR")
    save(store, config, "d" * 64, category="hosting", total="20", tax="2", currency="EUR")
    save(store, config, "e" * 64, category="hosting", total="30", tax="3", currency="USD")

    rows = list(csv.DictReader(StringIO(summary_csv(store.query()))))
    by_name = {row["category"]: row for row in rows}
    assert by_name["hosting [EUR]"]["total"] == "30.00"
    assert by_name["hosting [EUR]"]["documents"] == "2"
    assert by_name["hosting [USD]"]["total"] == "30.00"


def test_markdown_surfaces_what_needs_a_human(store, config):
    save(store, config, "f" * 64, vendor="Broken Co", subtotal="10", tax="1", total="99")
    text = summary_markdown(store.query(), "Q1")
    assert "# Q1" in text
    assert "Needs a human look" in text
    assert "Broken Co" in text


def test_markdown_handles_an_empty_ledger(store):
    assert "No documents matched." in summary_markdown([])


def test_total_of(store, config):
    save(store, config, "g" * 64, total="1.50")
    save(store, config, "h" * 64, total="2.25")
    assert str(total_of(store.query())) == "3.75"
