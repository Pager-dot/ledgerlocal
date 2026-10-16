from ledgerlocal.categorize import UNCATEGORISED, Ruleset
from ledgerlocal.models import Extraction


def extraction(**kwargs) -> Extraction:
    return Extraction.from_raw({"vendor": "", "issue_date": "2026-01-01", "total": "1", **kwargs})


def test_builtin_rules_match_common_vendors():
    rules = Ruleset.default()
    assert rules.categorise(extraction(vendor="Hetzner Online GmbH")) == ("hosting", "rule")
    assert rules.categorise(extraction(vendor="Adobe Inc."))[0] == "software"
    assert rules.categorise(extraction(vendor="Blue Fox Coffee"))[0] == "meals"


def test_longest_keyword_wins():
    rules = Ruleset.default()
    # "google ads" (marketing) must beat "google workspace"-style generic hits.
    assert rules.categorise(extraction(vendor="Google Ads Ireland"))[0] == "marketing"


def test_model_suggestion_is_the_fallback_not_the_default():
    rules = Ruleset.default()
    assert rules.categorise(extraction(vendor="Obscure Supplier Oy", category="Studio Rent")) == (
        "studio_rent",
        "model",
    )
    assert rules.categorise(extraction(vendor="Obscure Supplier Oy")) == (UNCATEGORISED, "default")


def test_user_rules_merge_with_and_beat_the_model(tmp_path):
    path = tmp_path / "rules.toml"
    path.write_text(
        '[categories]\nstudio_rent = ["blackwell properties"]\n'
        '[clients]\n"Northwind Trading" = ["northwind"]\n',
        "utf-8",
    )
    rules = Ruleset.load(path)

    doc = extraction(vendor="Blackwell Properties Ltd", category="office")
    assert rules.categorise(doc) == ("studio_rent", "rule")
    # defaults survive the merge
    assert rules.categorise(extraction(vendor="Adobe Inc."))[0] == "software"


def test_client_attribution_from_line_items():
    path_rules = Ruleset.default()
    path_rules.clients["Northwind Trading"] = ["northwind"]
    doc = extraction(vendor="Blue Fox Coffee", notes="Client meeting - Northwind")
    assert path_rules.attribute_client(doc) == ("Northwind Trading", "rule")


def test_apply_sets_both_fields():
    rules = Ruleset.default()
    doc = extraction(vendor="Hetzner Online GmbH")
    rules.apply(doc)
    assert doc.category == "hosting"
    assert doc.client == ""
