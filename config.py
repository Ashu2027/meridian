"""
config.py
AppConfig dataclass + load/save helpers.
Secrets are stored encrypted on disk via services/secrets_manager.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional

from services import secrets_manager


class ConfigMissingError(Exception):
    """Raised when no secrets file exists yet (triggers the setup wizard)."""


@dataclass
class AppConfig:
    # TiDB connection
    tidb_host: str = ""
    tidb_port: int = 4000
    tidb_user: str = ""
    tidb_password: str = ""
    tidb_database: str = "meridian"
    tidb_use_tls: bool = True
    tidb_ssl_ca: Optional[str] = None        # path to CA cert (TiDB Cloud)

    # Resend API
    resend_api_key: str = ""

    # Sender identity
    default_from_name: str = "Meridian Desk"
    default_from_email: str = ""

    # FastAPI server
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    api_secret_token: str = ""               # Bearer token for API auth


def load_config() -> AppConfig:
    """
    Load and decrypt the saved configuration.
    Raises ConfigMissingError when no secrets file exists.
    """
    try:
        data = secrets_manager.load_secrets()
    except FileNotFoundError as exc:
        raise ConfigMissingError(str(exc)) from exc
    return AppConfig(**{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__})


def save_config(cfg: AppConfig) -> None:
    """Serialize AppConfig to JSON, encrypt, and write to disk."""
    if not secrets_manager._key_path().exists():
        secrets_manager.generate_local_key()
    secrets_manager.save_secrets(asdict(cfg))
