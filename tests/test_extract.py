import json
from decimal import Decimal

import pytest

from ledgerlocal.errors import ExtractionError
from ledgerlocal.extract import extract_document, parse_model_json
from ledgerlocal.providers.fake import FakeProvider
from tests.conftest import SAMPLES, provider_returning


def test_parse_model_json_survives_a_chatty_model():
    assert parse_model_json('Sure! ```json\n{"vendor": "X"}\n```') == {"vendor": "X"}
    assert parse_model_json('Here you go: {"vendor": "X"} Hope that helps!') == {"vendor": "X"}
    assert parse_model_json('[{"vendor": "X"}]') == {"vendor": "X"}


def test_parse_model_json_rejects_junk():
    with pytest.raises(ExtractionError):
        parse_model_json("I could not read that document, sorry.")


def test_extracts_a_text_invoice(config):
    provider = provider_returning(
        {
            "kind": "invoice",
            "vendor": "Hetzner Online GmbH",
            "issue_date": "14.02.2026",
            "currency": "EUR",
            "subtotal": "27,50",
            "tax": "5,23",
            "total": "32,73",
            "confidence": 0.93,
        }
    )
    result = extract_document(SAMPLES / "hetzner-invoice.txt", provider, config)
    assert result.extraction.vendor == "Hetzner Online GmbH"
    assert result.extraction.total == Decimal("32.73")
    assert result.extraction.currency == "EUR"
    assert result.used_vision is False
    assert result.attempts == 1
    assert not result.extraction.needs_review


def test_a_bad_first_answer_triggers_exactly_one_repair(config):
    provider = provider_returning(
        {"vendor": "", "total": "", "confidence": 0.2},
        {
            "vendor": "Blue Fox Coffee",
            "issue_date": "2026-04-03",
            "total": "11.77",
            "currency": "EUR",
            "confidence": 0.8,
        },
    )
    result = extract_document(SAMPLES / "cafe-receipt.txt", provider, config)
    assert result.attempts == 2
    assert result.extraction.vendor == "Blue Fox Coffee"
    assert len(provider.calls) == 2
    assert "Problem:" in provider.calls[1]["prompt"]


def test_a_worse_repair_is_discarded(config):
    good = {
        "vendor": "Adobe Inc.",
        "issue_date": "2026-01-07",
        "subtotal": "59.99",
        "tax": "5.10",
        "total": "65.00",  # off by 9c, so a repair is attempted
        "currency": "USD",
        "confidence": 0.9,
    }
    provider = provider_returning(good, {"vendor": "", "confidence": 0.1})
    result = extract_document(SAMPLES / "adobe-subscription.txt", provider, config)
    assert result.extraction.vendor == "Adobe Inc."


def test_unusable_answers_raise_rather_than_inventing_data(config):
    provider = FakeProvider(["not json at all", "still not json"])
    with pytest.raises(ExtractionError):
        extract_document(SAMPLES / "cafe-receipt.txt", provider, config)


def test_low_confidence_is_flagged_for_review(config):
    provider = provider_returning(
        {
            "vendor": "Blue Fox Coffee",
            "issue_date": "2026-04-03",
            "total": "11.77",
            "confidence": 0.2,
        }
    )
    result = extract_document(SAMPLES / "cafe-receipt.txt", provider, config)
    assert result.extraction.needs_review
    assert any("low model confidence" in w for w in result.extraction.warnings)


def test_the_schema_is_handed_to_the_runtime(config):
    # Schema-constrained decoding is what makes a 7B model return usable JSON,
    # so losing it silently would be a real regression.
    captured = {}

    class Recording(FakeProvider):
        def complete_text(self, prompt, *, system="", schema=None):
            captured["schema"] = schema
            captured["system"] = system
            return json.dumps({"vendor": "X", "issue_date": "2026-01-01", "total": "1.00"})

    extract_document(SAMPLES / "cafe-receipt.txt", Recording(), config)
    assert captured["schema"]["required"]
    assert "bookkeeper" in captured["system"]
