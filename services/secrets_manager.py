"""
services/secrets_manager.py
Fernet-based encryption for the local secrets file.
Key and blob are stored in separate files so neither alone is useful.
"""
from __future__ import annotations

import json
import os
import platform
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


# ── Platform-aware config directory ───────────────────────────────────────────

def _config_dir() -> Path:
    """Return the platform-appropriate config directory for Meridian."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    directory = base / "meridian"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _key_path() -> Path:
    return _config_dir() / "key.bin"


def _secrets_path() -> Path:
    return _config_dir() / "secrets.enc"


def _lock_file(path: Path) -> None:
    """Restrict file permissions to owner read/write only."""
    if platform.system() == "Windows":
        import subprocess
        try:
            # Remove inherited permissions and grant only the current user
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r",
                 f"{os.environ.get('USERNAME', 'User')}:RW"],
                capture_output=True, check=False
            )
        except Exception:
            pass  # Best-effort on Windows
    else:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_local_key() -> bytes:
    """
    Generate a new Fernet key and persist it to disk.
    Called exactly once, during first-run setup.
    Returns the raw key bytes.
    """
    key = Fernet.generate_key()
    key_file = _key_path()
    key_file.write_bytes(key)
    _lock_file(key_file)
    return key


def _load_key() -> bytes:
    key_file = _key_path()
    if not key_file.exists():
        raise FileNotFoundError(
            f"Encryption key not found at {key_file}. "
            "Run the setup wizard to initialise Meridian."
        )
    return key_file.read_bytes()


def encrypt(data: dict) -> bytes:
    """Serialize *data* to JSON and encrypt with the local Fernet key."""
    key = _load_key()
    f = Fernet(key)
    return f.encrypt(json.dumps(data).encode("utf-8"))


def decrypt(blob: bytes) -> dict:
    """Decrypt *blob* and return the original dict."""
    key = _load_key()
    f = Fernet(key)
    try:
        return json.loads(f.decrypt(blob).decode("utf-8"))
    except InvalidToken as exc:
        raise ValueError(
            "Failed to decrypt secrets file. "
            "The key or secrets file may be corrupt."
        ) from exc


def save_secrets(data: dict) -> None:
    """Encrypt *data* and write to the secrets file."""
    blob = encrypt(data)
    secrets_file = _secrets_path()
    secrets_file.write_bytes(blob)
    _lock_file(secrets_file)


def load_secrets() -> dict:
    """Read and decrypt the secrets file. Raises FileNotFoundError if absent."""
    secrets_file = _secrets_path()
    if not secrets_file.exists():
        raise FileNotFoundError(
            f"Secrets file not found at {secrets_file}. "
            "Run the setup wizard first."
        )
    return decrypt(secrets_file.read_bytes())


def secrets_exist() -> bool:
    """Return True if both the key file and secrets file exist."""
    return _key_path().exists() and _secrets_path().exists()


def config_dir() -> Path:
    """Expose the config directory path (used by tests and CLI)."""
    return _config_dir()
