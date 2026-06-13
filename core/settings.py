"""Persistent app settings + secrets (saved once, reused every run).

Stored OUTSIDE the repo in ``~/.keystone/secrets.yaml`` (override the directory
with the ``KEYSTONE_HOME`` env var) so the Finnhub key and TWS host/port survive
re-clones and never land in git. Resolution order for any value:

    environment variable  ->  persisted file  ->  default

So you can set the key once via the Settings page (writes the file) and never
re-enter it, while an env var still wins for ad-hoc overrides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_TWS_HOST = "127.0.0.1"
DEFAULT_TWS_PORT = 7496  # live; 7497 = paper

# setting name -> environment variable that overrides the persisted value
_ENV = {
    "finnhub_key": "FINNHUB_KEY",
    "tws_host": "KEYSTONE_TWS_HOST",
    "tws_port": "KEYSTONE_TWS_PORT",
}


def store_dir() -> Path:
    return Path(os.environ.get("KEYSTONE_HOME", str(Path.home() / ".keystone")))


def secrets_path() -> Path:
    return store_dir() / "secrets.yaml"


def _load() -> dict:
    path = secrets_path()
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _save(data: dict) -> None:
    d = store_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = secrets_path()
    path.write_text(yaml.safe_dump(data, default_flow_style=False), encoding="utf-8")
    try:  # best-effort lock-down (no-op on Windows)
        os.chmod(path, 0o600)
    except OSError:
        pass


def get_setting(name: str, default: Any = None) -> Any:
    env = _ENV.get(name)
    if env and os.environ.get(env):
        return os.environ[env]
    value = _load().get(name)
    return value if value is not None else default


def set_setting(name: str, value: Any) -> None:
    data = _load()
    if value in (None, ""):
        data.pop(name, None)
    else:
        data[name] = value
    _save(data)


# --- typed accessors -------------------------------------------------------- #
def get_finnhub_key() -> Optional[str]:
    key = get_setting("finnhub_key")
    return str(key) if key else None


def set_finnhub_key(value: Optional[str]) -> None:
    set_setting("finnhub_key", value)


def finnhub_key_present() -> bool:
    return bool(get_finnhub_key())


def get_tws_host() -> str:
    return str(get_setting("tws_host", DEFAULT_TWS_HOST))


def get_tws_port() -> int:
    try:
        return int(get_setting("tws_port", DEFAULT_TWS_PORT))
    except (TypeError, ValueError):
        return DEFAULT_TWS_PORT


def set_tws(host: Optional[str] = None, port: Optional[int] = None) -> None:
    if host is not None:
        set_setting("tws_host", host)
    if port is not None:
        set_setting("tws_port", int(port))


def masked_finnhub_key() -> str:
    key = get_finnhub_key()
    if not key:
        return ""
    return f"{key[:3]}…{key[-2:]}" if len(key) > 6 else "set"
