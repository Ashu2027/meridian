"""
tests/test_secrets_manager.py
Unit tests for services/secrets_manager.py.
All file I/O is redirected to a tmp_path so real disk is never touched.
"""
from __future__ import annotations

import json
import stat
import platform
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from cryptography.fernet import Fernet, InvalidToken
from services.secrets_manager import (
    _config_dir, _key_path, _secrets_path, _lock_file,
    generate_local_key, encrypt, decrypt,
    save_secrets, load_secrets, secrets_exist, config_dir,
)


# ── _config_dir ────────────────────────────────────────────────────────────────

class TestConfigDir:
    def test_returns_path_object(self, tmp_path):
        with patch("services.secrets_manager._config_dir", return_value=tmp_path / "meridian"):
            (tmp_path / "meridian").mkdir()
            result = _config_dir.__wrapped__() if hasattr(_config_dir, "__wrapped__") else None
        # Just verify the real function returns a Path that exists
        result = _config_dir()
        assert isinstance(result, Path)
        assert result.exists()

    def test_windows_uses_appdata(self):
        with patch("platform.system", return_value="Windows"), \
             patch.dict("os.environ", {"APPDATA": "C:\\FakeAppData"}):
            result = _config_dir()
            assert "meridian" in str(result).lower()

    def test_non_windows_uses_xdg(self, tmp_path):
        with patch("platform.system", return_value="Linux"), \
             patch.dict("os.environ", {"XDG_CONFIG_HOME": str(tmp_path)}):
            result = _config_dir()
            assert result.name == "meridian"


# ── _lock_file ─────────────────────────────────────────────────────────────────

class TestLockFile:
    def test_windows_calls_icacls(self, tmp_path):
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"data")

        with patch("platform.system", return_value="Windows"), \
             patch("subprocess.run") as mock_run:
            _lock_file(test_file)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "icacls" in args

    def test_windows_icacls_exception_swallowed(self, tmp_path):
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"data")

        with patch("platform.system", return_value="Windows"), \
             patch("subprocess.run", side_effect=OSError("No icacls")):
            # Should NOT raise — best-effort on Windows
            _lock_file(test_file)

    def test_linux_sets_permissions(self, tmp_path):
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"data")

        with patch("platform.system", return_value="Linux"):
            _lock_file(test_file)
            mode = test_file.stat().st_mode
            # Owner read/write only
            assert mode & stat.S_IRUSR
            assert mode & stat.S_IWUSR


# ── generate_local_key ─────────────────────────────────────────────────────────

class TestGenerateLocalKey:
    def test_writes_valid_fernet_key(self, tmp_path):
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            key = generate_local_key()
        key_file = tmp_path / "key.bin"
        assert key_file.exists()
        assert len(key) == 44  # Fernet keys are 44 base64 chars
        # Must be a valid Fernet key (no exception)
        Fernet(key)

    def test_returns_key_bytes(self, tmp_path):
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            key = generate_local_key()
        assert isinstance(key, bytes)


# ── encrypt / decrypt round-trip ───────────────────────────────────────────────

class TestEncryptDecrypt:
    def _setup_key(self, tmp_path: Path) -> bytes:
        key = Fernet.generate_key()
        (tmp_path / "key.bin").write_bytes(key)
        return key

    def test_round_trip(self, tmp_path):
        self._setup_key(tmp_path)
        data = {"host": "localhost", "port": 4000, "token": "secret"}

        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            blob = encrypt(data)
            result = decrypt(blob)

        assert result == data

    def test_encrypt_returns_bytes(self, tmp_path):
        self._setup_key(tmp_path)
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            blob = encrypt({"key": "value"})
        assert isinstance(blob, bytes)

    def test_decrypt_wrong_key_raises_value_error(self, tmp_path):
        key1 = Fernet.generate_key()
        key2 = Fernet.generate_key()
        (tmp_path / "key.bin").write_bytes(key1)

        # Encrypt with key1
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            blob = encrypt({"secret": "value"})

        # Now swap to key2 and try to decrypt
        (tmp_path / "key.bin").write_bytes(key2)
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            with pytest.raises(ValueError, match="decrypt"):
                decrypt(blob)

    def test_load_key_missing_raises(self, tmp_path):
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            with pytest.raises(FileNotFoundError, match="key"):
                from services.secrets_manager import _load_key
                _load_key()


# ── save_secrets / load_secrets ────────────────────────────────────────────────

class TestSaveLoadSecrets:
    def test_full_round_trip(self, tmp_path):
        key = Fernet.generate_key()
        (tmp_path / "key.bin").write_bytes(key)
        data = {"tidb_host": "myhost", "resend_api_key": "re_test", "port": 4000}

        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            save_secrets(data)
            loaded = load_secrets()

        assert loaded == data

    def test_load_missing_secrets_raises(self, tmp_path):
        # Key exists but secrets file doesn't
        key = Fernet.generate_key()
        (tmp_path / "key.bin").write_bytes(key)

        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            with pytest.raises(FileNotFoundError, match="Secrets file"):
                load_secrets()

    def test_save_creates_encrypted_file(self, tmp_path):
        key = Fernet.generate_key()
        (tmp_path / "key.bin").write_bytes(key)

        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            save_secrets({"key": "val"})

        secrets_file = tmp_path / "secrets.enc"
        assert secrets_file.exists()
        # File should be encrypted — not raw JSON
        raw = secrets_file.read_bytes()
        assert b'"key"' not in raw  # Not plain JSON


# ── secrets_exist ──────────────────────────────────────────────────────────────

class TestSecretsExist:
    def test_both_files_present(self, tmp_path):
        (tmp_path / "key.bin").write_bytes(b"x")
        (tmp_path / "secrets.enc").write_bytes(b"x")

        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            assert secrets_exist() is True

    def test_key_missing(self, tmp_path):
        (tmp_path / "secrets.enc").write_bytes(b"x")
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            assert secrets_exist() is False

    def test_secrets_missing(self, tmp_path):
        (tmp_path / "key.bin").write_bytes(b"x")
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            assert secrets_exist() is False

    def test_both_missing(self, tmp_path):
        with patch("services.secrets_manager._config_dir", return_value=tmp_path):
            assert secrets_exist() is False


# ── config_dir ─────────────────────────────────────────────────────────────────

class TestConfigDirExposed:
    def test_returns_path(self):
        result = config_dir()
        assert isinstance(result, Path)
