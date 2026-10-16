import shutil

import pytest

from ledgerlocal.cli import main
from tests.conftest import SAMPLES


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGERLOCAL_HOME", str(tmp_path / "config"))
    return tmp_path


def base_args(home):
    return ["--provider", "fake", "--library", str(home / "library")]


def test_init_writes_a_starter_config(home, capsys):
    assert main(base_args(home) + ["init"]) == 0
    assert (home / "config" / "config.toml").exists()
    assert (home / "config" / "rules.toml").exists()
    assert "wrote" in capsys.readouterr().out


def test_doctor_reports_a_working_runtime(home, capsys):
    assert main(base_args(home) + ["doctor"]) == 0
    out = capsys.readouterr().out
    assert "egress" in out
    assert "Ready." in out


def test_ingest_then_list_then_export(home, capsys):
    inbox = home / "inbox"
    inbox.mkdir()
    shutil.copy2(SAMPLES / "cafe-receipt.txt", inbox / "cafe.txt")

    assert main(base_args(home) + ["ingest", str(inbox)]) == 0
    assert "ingested" in capsys.readouterr().out

    assert main(base_args(home) + ["list"]) == 0
    assert "Fake Vendor Ltd" in capsys.readouterr().out

    assert main(base_args(home) + ["export", "--format", "csv"]) == 0
    assert (home / "library" / "exports" / "ledgerlocal-all.csv").exists()


def test_stats_on_an_empty_ledger_is_not_an_error(home, capsys):
    assert main(base_args(home) + ["stats"]) == 0
    assert "No documents stored yet" in capsys.readouterr().out


def test_unknown_provider_is_a_clean_config_error(home, capsys):
    code = main(["--provider", "nonsense", "--library", str(home / "l"), "doctor"])
    assert code == 1
    assert "unknown provider" in capsys.readouterr().err


def test_bare_invocation_prints_help(capsys):
    assert main([]) == 1
    assert "usage" in capsys.readouterr().out
