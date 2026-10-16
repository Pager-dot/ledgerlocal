from decimal import Decimal

from ledgerlocal.models import Extraction
from ledgerlocal.store import Store, totals_by


def save(store, config, digest, **fields):
    extraction = Extraction.from_raw({"vendor": "V", "issue_date": "2026-01-15", "total": "10", **fields})
    store.save(digest, extraction, source_path=config.library / f"{digest}.txt")
    return extraction


def test_round_trip_keeps_decimal_precision(store, config):
    save(store, config, "a" * 64, vendor="Hetzner", total="32.73", tax="5.23", currency="EUR")
    record = store.query()[0]
    assert record.total == Decimal("32.73")
    assert record.tax == Decimal("5.23")
    assert record.currency == "EUR"
    assert record.period == "2026-Q1"


def test_digest_is_the_dedupe_key(store, config):
    save(store, config, "b" * 64, vendor="First")
    assert store.has("b" * 64)
    save(store, config, "b" * 64, vendor="Second")  # upsert, not a duplicate row
    records = store.query()
    assert len(records) == 1
    assert records[0].vendor == "Second"


def test_line_items_are_replaced_not_appended(store, config):
    extraction = Extraction.from_raw(
        {"vendor": "V", "issue_date": "2026-01-15", "total": "10",
         "line_items": [{"description": "one", "amount": "5"}, {"description": "two", "amount": "5"}]}
    )
    store.save("c" * 64, extraction, source_path=config.library / "x.txt")
    store.save("c" * 64, extraction, source_path=config.library / "x.txt")
    rows = store.connection.execute("SELECT COUNT(*) AS n FROM line_items").fetchone()["n"]
    assert rows == 2


def test_filters(store, config):
    save(store, config, "d" * 64, vendor="Hetzner", category="hosting", issue_date="2026-02-01")
    save(store, config, "e" * 64, vendor="Adobe", category="software", issue_date="2026-07-01")
    save(store, config, "f" * 64, vendor="Adobe", category="software", issue_date="2025-02-01")

    assert len(store.query(period="2026")) == 2
    assert len(store.query(period="2026-Q1")) == 1
    assert len(store.query(category="software")) == 2
    assert len(store.query(vendor="hetz")) == 1
    assert store.query(period="2026-Q3")[0].vendor == "Adobe"


def test_needs_review_filter(store, config):
    save(store, config, "1" * 64, vendor="Clean", subtotal="10", tax="0", total="10", confidence=0.9)
    save(store, config, "2" * 64, vendor="Broken", subtotal="10", tax="1", total="99")
    flagged = store.query(needs_review=True)
    assert [record.vendor for record in flagged] == ["Broken"]
    assert store.counts() == {"documents": 2, "needs_review": 1, "vendors": 2}


def test_currencies_are_never_summed_together(store, config):
    save(store, config, "3" * 64, vendor="A", total="10", currency="USD", category="software")
    save(store, config, "4" * 64, vendor="B", total="10", currency="EUR", category="software")
    buckets = totals_by(store.query(), "category")
    assert set(buckets) == {"software [USD]", "software [EUR]"}


def test_forget_removes_line_items_too(store, config):
    extraction = Extraction.from_raw(
        {"vendor": "V", "issue_date": "2026-01-15", "total": "10",
         "line_items": [{"description": "one", "amount": "10"}]}
    )
    store.save("9" * 64, extraction, source_path=config.library / "x.txt")
    assert store.forget("9" * 64)
    assert store.connection.execute("SELECT COUNT(*) AS n FROM line_items").fetchone()["n"] == 0


def test_store_creates_its_own_directory(tmp_path):
    path = tmp_path / "deep" / "nested" / "ledger.sqlite3"
    with Store(path) as store:
        assert store.counts()["documents"] == 0
    assert path.exists()
