"""User configuration: a small TOML file, with every value overridable by flag."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ledgerlocal.errors import ConfigError

DEFAULT_CONFIG_NAME = "config.toml"


def config_home() -> Path:
    base = os.environ.get("LEDGERLOCAL_HOME")
    if base:
        return Path(base).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return root / "ledgerlocal"


@dataclass
class Config:
    # Where inference happens. Loopback by default, and the offline guard will
    # not let it be anything else unless the user adds it to allow_hosts.
    provider: str = "ollama"
    host: str = "http://127.0.0.1:11434"
    vision_model: str = "qwen2.5vl:7b"
    text_model: str = "qwen2.5:7b"
    timeout: float = 240.0
    temperature: float = 0.0
    num_ctx: int = 8192
    max_pages: int = 4
    render_dpi: int = 180

    # Behaviour
    date_order: str = "dmy"
    default_currency: str = "USD"
    review_threshold: float = 0.55
    allow_hosts: list[str] = field(default_factory=list)
    enforce_offline: bool = True

    # Paths
    library: Path = field(default_factory=lambda: Path.home() / "Documents" / "LedgerLocal")

    @property
    def database(self) -> Path:
        return self.library / "ledger.sqlite3"

    @property
    def filed_root(self) -> Path:
        return self.library / "filed"

    @property
    def rules_path(self) -> Path:
        return config_home() / "rules.toml"


def load(path: Path | None = None) -> Config:
    """Read config from ``path`` (default: the user's config home)."""
    target = path or (config_home() / DEFAULT_CONFIG_NAME)
    config = Config()
    if not target.exists():
        return config

    try:
        raw: dict[str, Any] = tomllib.loads(target.read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"could not read {target}: {exc}") from exc

    flat: dict[str, Any] = {}
    for section in ("model", "behaviour", "behavior", "paths"):
        value = raw.get(section)
        if isinstance(value, dict):
            flat.update(value)
    flat.update({k: v for k, v in raw.items() if not isinstance(v, dict)})

    known = {f.name for f in Config.__dataclass_fields__.values()}
    unknown = sorted(set(flat) - known)
    if unknown:
        raise ConfigError(f"unknown config key(s) in {target}: {', '.join(unknown)}")

    if "library" in flat:
        flat["library"] = Path(str(flat["library"])).expanduser()
    if "date_order" in flat and flat["date_order"] not in ("dmy", "mdy"):
        raise ConfigError("date_order must be 'dmy' or 'mdy'")
    return replace(config, **flat)


EXAMPLE_CONFIG = """\
# LedgerLocal configuration. Everything here has a working default; this file
# exists so you can swap the model, point at a different local runtime, or
# change how documents are filed.

[model]
provider = "ollama"            # ollama | openai-compatible | fake
host = "http://127.0.0.1:11434"
vision_model = "qwen2.5vl:7b"  # anything your runtime can see
text_model = "qwen2.5:7b"
temperature = 0.0
num_ctx = 8192
max_pages = 4                  # pages read per PDF
render_dpi = 180

[behaviour]
date_order = "dmy"             # tie-breaker for 03/04/2026
default_currency = "USD"
review_threshold = 0.55        # below this, a document is flagged for review
enforce_offline = true         # refuse any socket that is not loopback
allow_hosts = []               # e.g. ["192.168.1.40"] for a GPU box on your LAN

[paths]
library = "~/Documents/LedgerLocal"
"""
