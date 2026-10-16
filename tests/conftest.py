from __future__ import annotations

import json
from pathlib import Path

import pytest

from ledgerlocal import offline
from ledgerlocal.config import Config
from ledgerlocal.providers.fake import FakeProvider
from ledgerlocal.store import Store

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(autouse=True)
def _unwind_offline_guard():
    """The guard is process-wide by design, so a test that enables it must not
    leak that into the next one."""
    yield
    offline.release()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(provider="fake", library=tmp_path / "library", enforce_offline=False)


@pytest.fixture
def store(config: Config) -> Store:
    with Store(config.database) as handle:
        yield handle


def provider_returning(*payloads: dict) -> FakeProvider:
    return FakeProvider([json.dumps(payload) for payload in payloads])
