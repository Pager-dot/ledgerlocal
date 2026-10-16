
from ledgerlocal.models import Extraction
from ledgerlocal.organize import apply_plan, plan_file, target_path


def doc(**fields) -> Extraction:
    return Extraction.from_raw(
        {"vendor": "Hetzner Online GmbH", "issue_date": "2026-02-14", "total": "32.73",
         "currency": "EUR", "category": "hosting", **fields}
    )


def test_path_is_readable_by_a_human_and_an_accountant(tmp_path):
    path = target_path(doc(), tmp_path, ".pdf")
    assert path.relative_to(tmp_path).parts[:3] == ("2026", "Q1", "hosting")
    assert path.name.startswith("2026-02-14_hetzner-online-gmbh")
    assert path.name.endswith(".pdf")


def test_invoice_number_is_included_when_known(tmp_path):
    path = target_path(doc(invoice_number="R0029481773"), tmp_path, ".pdf")
    assert "r0029481773" in path.name


def test_undated_documents_still_get_filed(tmp_path):
    path = target_path(doc(issue_date=""), tmp_path, ".png")
    assert path.relative_to(tmp_path).parts[:2] == ("undated", "undated")
    assert "unknown-date" in path.name


def test_copy_leaves_the_original_alone(tmp_path):
    source = tmp_path / "in" / "receipt.txt"
    source.parent.mkdir()
    source.write_text("hello", "utf-8")

    destination = apply_plan(plan_file(doc(), source, tmp_path / "filed"))
    assert destination.exists()
    assert source.exists()
    assert destination.read_text("utf-8") == "hello"


def test_move_relocates_the_original(tmp_path):
    source = tmp_path / "in" / "receipt.txt"
    source.parent.mkdir()
    source.write_text("hello", "utf-8")

    destination = apply_plan(plan_file(doc(), source, tmp_path / "filed", move=True))
    assert destination.exists()
    assert not source.exists()


def test_two_identical_looking_documents_never_overwrite(tmp_path):
    root = tmp_path / "filed"
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_text("one", "utf-8")
    second.write_text("two", "utf-8")

    a = apply_plan(plan_file(doc(), first, root))
    b = apply_plan(plan_file(doc(), second, root))
    assert a != b
    assert a.read_text("utf-8") == "one"
    assert b.read_text("utf-8") == "two"
