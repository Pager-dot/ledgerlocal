import json
import shutil

from ledgerlocal.categorize import Ruleset
from ledgerlocal.ingest import ingest, recategorise
from ledgerlocal.providers.fake import FakeProvider
from tests.conftest import SAMPLES


def answers_for_every_sample() -> FakeProvider:
    payload = {
        "kind": "invoice",
        "vendor": "Hetzner Online GmbH",
        "issue_date": "2026-02-14",
        "currency": "EUR",
        "subtotal": "27.50",
        "tax": "5.23",
        "total": "32.73",
        "confidence": 0.9,
    }
    return FakeProvider([json.dumps(payload)])


def test_ingest_reads_files_once_and_files_them(tmp_path, config, store):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for sample in SAMPLES.glob("*.txt"):
        shutil.copy2(sample, inbox / sample.name)

    report = ingest([inbox], config=config, provider=answers_for_every_sample(), store=store)

    assert len(report.ingested) == 4
    assert not report.failed
    assert all(outcome.filed_path and outcome.filed_path.exists() for outcome in report.ingested)
    assert store.counts()["documents"] == 4
    # Originals are copied, not consumed.
    assert len(list(inbox.iterdir())) == 4


def test_re_running_the_same_folder_is_a_no_op(tmp_path, config, store):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copy2(SAMPLES / "cafe-receipt.txt", inbox / "cafe.txt")

    first = ingest([inbox], config=config, provider=answers_for_every_sample(), store=store)
    second = ingest([inbox], config=config, provider=answers_for_every_sample(), store=store)

    assert len(first.ingested) == 1
    assert len(second.ingested) == 0
    assert len(second.skipped) == 1
    assert store.counts()["documents"] == 1


def test_the_same_document_under_two_names_is_stored_once(tmp_path, config, store):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copy2(SAMPLES / "cafe-receipt.txt", inbox / "cafe.txt")
    shutil.copy2(SAMPLES / "cafe-receipt.txt", inbox / "cafe-copy.txt")

    report = ingest([inbox], config=config, provider=answers_for_every_sample(), store=store)
    assert len(report.ingested) == 1
    assert len(report.skipped) == 1


def test_one_unreadable_file_does_not_abort_the_batch(tmp_path, config, store):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copy2(SAMPLES / "cafe-receipt.txt", inbox / "good.txt")
    (inbox / "empty.txt").write_text("", "utf-8")

    report = ingest([inbox], config=config, provider=answers_for_every_sample(), store=store)
    assert len(report.ingested) == 1
    assert len(report.failed) == 1
    assert "empty" in report.failed[0].error


def test_no_file_flag_records_without_touching_the_disk(tmp_path, config, store):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copy2(SAMPLES / "cafe-receipt.txt", inbox / "cafe.txt")

    ingest([inbox], config=config, provider=answers_for_every_sample(), store=store, file_documents=False)
    assert not config.filed_root.exists()
    assert store.counts()["documents"] == 1


def test_changing_rules_and_replaying_costs_no_model_calls(tmp_path, config, store):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copy2(SAMPLES / "hetzner-invoice.txt", inbox / "hetzner.txt")

    provider = answers_for_every_sample()
    ingest([inbox], config=config, provider=provider, store=store, rules=Ruleset.default())
    assert store.query()[0].category == "hosting"
    calls_before = len(provider.calls)

    rules = Ruleset.default()
    rules.categories["infrastructure"] = ["hetzner online gmbh"]
    changed = recategorise(store, rules, config)

    assert changed == 1
    assert store.query()[0].category == "infrastructure"
    assert len(provider.calls) == calls_before  # the model was never asked again
