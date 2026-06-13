"""YAML loaders for the four config files.

``load_config()`` loads + validates all four and returns a single
``KeystoneConfig``. Individual loaders are exposed for targeted use and tests.
A missing file falls back to that schema's defaults (the only hard requirement
is at least one account in accounts.yaml).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from .schema import (
    AccountsConfig,
    InvestingConfig,
    KeystoneConfig,
    RiskConfig,
    UniverseConfig,
)

CONFIG_DIR = Path(__file__).resolve().parent


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def load_accounts(config_dir: Path = CONFIG_DIR) -> AccountsConfig:
    return AccountsConfig(**_read_yaml(Path(config_dir) / "accounts.yaml"))


def load_universe(config_dir: Path = CONFIG_DIR) -> UniverseConfig:
    return UniverseConfig(**_read_yaml(Path(config_dir) / "universe.yaml"))


def load_investing(config_dir: Path = CONFIG_DIR) -> InvestingConfig:
    return InvestingConfig(**_read_yaml(Path(config_dir) / "investing.yaml"))


def load_risk(config_dir: Path = CONFIG_DIR) -> RiskConfig:
    return RiskConfig(**_read_yaml(Path(config_dir) / "risk.yaml"))


def load_config(config_dir: Optional[Path] = None) -> KeystoneConfig:
    """Load + validate all four config files into one ``KeystoneConfig``."""

    cdir = Path(config_dir) if config_dir is not None else CONFIG_DIR
    return KeystoneConfig(
        accounts=load_accounts(cdir),
        universe=load_universe(cdir),
        investing=load_investing(cdir),
        risk=load_risk(cdir),
    )
